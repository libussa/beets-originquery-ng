from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import jsonpath_rw
import yaml
from beets import config, ui
from beets.plugins import BeetsPlugin
from beets.util import get_most_common_tags

BEETS_TO_LABEL = OrderedDict(
    [
        ("artist", "Artist"),
        ("album", "Name"),
        ("media", "Media"),
        ("year", "Edition year"),
        ("country", "Country"),
        ("label", "Record label"),
        ("barcode", "Barcode"),
        ("catalognum", "Catalog number"),
        ("albumdisambig", "Edition"),
    ]
)

# Conflicts will be reported if any of these fields don't match.
CONFLICT_FIELDS = ["barcode", "catalognum", "media", "artist"]

SUPPORTED_METADATA_SOURCES = ["musicbrainz"]

# Supported providers for URL extraction from origin files.
SUPPORTED_PROVIDERS = ["discogs", "bandcamp"]

# Artist/album always affect metadata-source search criteria even without extra_tags.
CORE_SEARCH_FIELDS = {"artist", "album"}


@dataclass
class TagComparison:
    tagged: str
    active: bool
    origin: str = ""


@dataclass
class TaskState:
    origin_path: Path
    missing_origin: bool = False
    parse_error: str | None = None
    conflict: bool = False
    tag_compare: OrderedDict[str, TagComparison] = field(default_factory=OrderedDict)
    display_fields: OrderedDict[str, str] = field(default_factory=OrderedDict)
    metadata_urls: dict[str, str] = field(default_factory=dict)


class OriginQueryError(Exception):
    """Raised when origin data cannot be parsed."""


def normalize_catno(catno: str) -> str:
    return catno.upper().replace(" ", "").replace("-", "")


def sanitize_value(key: str, value: str) -> str:
    if key == "media" and value == "WEB":
        return "Digital Media"
    if key in {"catalognum", "label"}:
        return re.split(r"[,/]", value)[0].strip()
    if key == "year" and value == "0":
        return ""
    return value


def scan_file_for_metadata_urls(file_path: Path, provider: str) -> str | None:
    """Scan an origin file for metadata URLs for a specific provider."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    provider_pattern = rf"https?://[^/]+\.{provider}\.com/[^\s\]]+"
    bbcode_match = re.search(rf"\[url\]({provider_pattern})\[/url\]", content)
    if bbcode_match:
        return bbcode_match.group(1)

    plain_match = re.search(provider_pattern, content)
    if plain_match:
        return plain_match.group(0)

    return None


def highlight(text: str, active: bool = True) -> str:
    if active:
        return ui.colorize("text_highlight_minor", text)
    return text


class OriginQuery(BeetsPlugin):
    def __init__(self) -> None:
        super().__init__()
        # Keep the config namespace stable even though this class lives in a submodule.
        self.name = "originquery"
        self.config = config[self.name]
        self.config.add(
            {
                "origin_type": "",
                "tag_patterns": {},
                "use_origin_on_conflict": False,
                "preserve_media_with_catalognum": False,
                "remove_conflicting_albumartist": False,
            }
        )

        self.extra_tags: list[str] = []
        self.extra_tags_source: str | None = None
        self.tag_patterns: dict[str, object] = {}
        self.tasks: dict[int, TaskState] = {}

        if not self._configure_extra_tags():
            return

        if not self._configure_patterns():
            return

        self.use_origin_on_conflict = self.config["use_origin_on_conflict"].get(bool)
        self.preserve_media_with_catalognum = self.config["preserve_media_with_catalognum"].get(bool)
        self.remove_conflicting_albumartist = self.config["remove_conflicting_albumartist"].get(bool)

        self.register_listener("import_task_start", self.import_task_start)
        self.register_listener("before_choose_candidate", self.before_choose_candidate)
        self.register_listener("import_task_choice", self.import_task_choice)

    def _configure_extra_tags(self) -> bool:
        for source in SUPPORTED_METADATA_SOURCES:
            try:
                source_extra_tags = config[source]["extra_tags"].as_str_seq()
            except Exception:
                continue

            if source_extra_tags:
                self.extra_tags = list(source_extra_tags)
                self.extra_tags_source = source
                break

        if self.extra_tags_source:
            self._log.info("Using extra tags from {}", self.extra_tags_source)
            self._log.info("Available extra tags: {}", ", ".join(self.extra_tags))
        else:
            self._log.warning(
                "No supported metadata-source extra_tags configured. "
                "Origin data will still affect artist/album search terms."
            )

        return True

    def _configure_patterns(self) -> bool:
        config_patterns = self.config["tag_patterns"].get()
        if not isinstance(config_patterns, dict) or not config_patterns:
            self._log.error("originquery.tag_patterns must be a non-empty dictionary of key -> pattern mappings.")
            self._log.error("Plugin disabled.")
            return False

        origin_file_value = self.config["origin_file"].get()
        if not origin_file_value:
            self._log.error("originquery.origin_file is not set.")
            self._log.error("Plugin disabled.")
            return False
        self.origin_file = Path(origin_file_value)

        origin_type = str(self.config["origin_type"].get() or "").lower()
        origin_type = origin_type if origin_type else self.origin_file.suffix.lower().lstrip(".")
        if origin_type == "yml":
            origin_type = "yaml"

        if origin_type == "json":
            self.match_fn = self.match_json
        elif origin_type == "yaml":
            self.match_fn = self.match_yaml
        else:
            self.match_fn = self.match_text

        for key, pattern in config_patterns.items():
            if key not in BEETS_TO_LABEL:
                self._log.debug('Display field "{}" will be shown during import', key)

            if origin_type in {"json", "yaml"}:
                try:
                    self.tag_patterns[key] = jsonpath_rw.parse(pattern)
                except Exception as exc:
                    self._log.error(
                        'Invalid JSONPath for "{}": {} ({})',
                        key,
                        pattern,
                        exc,
                    )
                    self._log.error("Plugin disabled.")
                    return False
                continue

            try:
                regex = re.compile(pattern)
            except re.error as exc:
                self._log.error(
                    'Invalid regex for "{}": {} ({})',
                    key,
                    pattern,
                    exc,
                )
                self._log.error("Plugin disabled.")
                return False

            if regex.groups != 1:
                self._log.error(
                    'Invalid regex for "{}": {} (must have exactly one capture group)',
                    key,
                    pattern,
                )
                self._log.error("Plugin disabled.")
                return False

            self.tag_patterns[key] = regex

        return True

    def _state_for(self, task) -> TaskState:
        return self.tasks[id(task)]

    def _emit_visible(self, message: str) -> None:
        self._log.warning("{}", message)

    def _active_for(self, tag: str) -> bool:
        return tag in CORE_SEARCH_FIELDS or tag in self.extra_tags

    def _album_directory(self, task) -> Path:
        if task.toppath:
            base_path = Path(os.fsdecode(task.toppath))
        elif len(task.paths) == 1:
            base_path = Path(os.fsdecode(task.paths[0])).parent
        else:
            base_path = Path(os.fsdecode(os.path.commonpath(task.paths)))

        if base_path.exists() and base_path.is_file():
            return base_path.parent
        return base_path

    def _find_origin_file(self, task) -> Path | None:
        base_path = self._album_directory(task)
        matches = sorted(base_path.glob(str(self.origin_file)))
        if matches:
            return matches[0]
        return None

    def _extract_metadata_urls(self, origin_path: Path) -> dict[str, str]:
        metadata_urls = {}
        for provider in SUPPORTED_PROVIDERS:
            try:
                should_extract = config[provider]["extract_urls_from_origin"].get(bool)
            except Exception:
                continue

            if not should_extract:
                continue

            if url := scan_file_for_metadata_urls(origin_path, provider):
                metadata_urls[provider] = url

        return metadata_urls

    def _remove_conflicting_albumartist(self, task, origin_artist: str) -> bool:
        if not self.remove_conflicting_albumartist or not origin_artist:
            return False

        likelies, consensus = get_most_common_tags(task.items)
        tagged_albumartist = str(likelies.get("albumartist") or "")
        if not tagged_albumartist or not consensus.get("albumartist"):
            return False

        if tagged_albumartist == origin_artist:
            return False

        for item in task.items:
            item.albumartist = ""

        self._emit_visible(
            f'Removing conflicting albumartist "{tagged_albumartist}" in favor of origin artist "{origin_artist}"'
        )
        return True

    def print_tags(self, items: list[tuple[str, TagComparison]], use_tagged: bool) -> None:
        if not items:
            return

        headers = ["Field", "Tagged Data", "Origin Data"]
        w_key = max(len(headers[0]), *(len(BEETS_TO_LABEL[k]) for k, _ in items))
        w_tagged = max(len(headers[1]), *(len(entry.tagged) for _, entry in items))
        w_origin = max(len(headers[2]), *(len(entry.origin) for _, entry in items))

        self._emit_visible(f"╔{'═' * (w_key + 2)}╤{'═' * (w_tagged + 2)}╤{'═' * (w_origin + 2)}╗")
        self._emit_visible(
            f"║ {headers[0].ljust(w_key)} │ "
            f"{highlight(headers[1].ljust(w_tagged), use_tagged)} │ "
            f"{highlight(headers[2].ljust(w_origin), not use_tagged)} ║"
        )
        self._emit_visible(f"╟{'─' * (w_key + 2)}┼{'─' * (w_tagged + 2)}┼{'─' * (w_origin + 2)}╢")
        for key, entry in items:
            if not entry.tagged and not entry.origin:
                continue

            tagged_active = use_tagged and entry.active
            origin_active = (not use_tagged) and entry.active
            self._emit_visible(
                f"║ {BEETS_TO_LABEL[key].ljust(w_key)} │ "
                f"{highlight(entry.tagged.ljust(w_tagged), tagged_active)} │ "
                f"{highlight(entry.origin.ljust(w_origin), origin_active)} ║"
            )
        self._emit_visible(f"╚{'═' * (w_key + 2)}╧{'═' * (w_tagged + 2)}╧{'═' * (w_origin + 2)}╝")

    def before_choose_candidate(self, task, session) -> None:
        task_state = self._state_for(task)

        if task_state.missing_origin:
            self._log.warning("No origin file found at {}", task_state.origin_path)
            return

        if task_state.parse_error:
            self._log.warning(
                "Skipping origin file {}: {}",
                task_state.origin_path,
                task_state.parse_error,
            )
            return

        self._emit_visible(f"Using origin file {task_state.origin_path}")
        use_tagged = task_state.conflict and not self.use_origin_on_conflict
        self.print_tags(list(task_state.tag_compare.items()), use_tagged)

        if task_state.display_fields:
            self._emit_visible("Additional origin information:")
            for key, value in task_state.display_fields.items():
                self._emit_visible(f"  {key.replace('_', ' ').title()}: {value}")

        if task_state.metadata_urls:
            self._emit_visible("Metadata URLs found:")
            for provider, url in task_state.metadata_urls.items():
                self._emit_visible(f"  {provider.title()}: {url}")

        if task_state.conflict:
            self._log.warning("Origin data conflicts with tagged data.")

    def import_task_choice(self, task, session) -> None:
        self.tasks.pop(id(task), None)

    def match_text(self, origin_path: Path):
        try:
            lines = origin_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise OriginQueryError(f"could not read file ({exc})") from exc

        for key, pattern in self.tag_patterns.items():
            pattern = cast(re.Pattern[str], pattern)
            for line in lines:
                match = pattern.match(line.strip())
                if match:
                    yield key, match.group(1)

    def match_json(self, origin_path: Path):
        try:
            data = json.loads(origin_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OriginQueryError(f"invalid JSON ({exc})") from exc

        for key, pattern in self.tag_patterns.items():
            pattern = cast(Any, pattern)
            matches = pattern.find(data)
            if matches:
                yield key, str(matches[0].value)

    def match_yaml(self, origin_path: Path):
        try:
            data = yaml.safe_load(origin_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise OriginQueryError(f"invalid YAML ({exc})") from exc

        if data is None:
            return

        for key, pattern in self.tag_patterns.items():
            pattern = cast(Any, pattern)
            matches = pattern.find(data)
            if matches and matches[0].value:
                yield key, str(matches[0].value)

    def import_task_start(self, task, session) -> None:
        origin_path = self._find_origin_file(task)
        if origin_path is None:
            self.tasks[id(task)] = TaskState(
                origin_path=self._album_directory(task) / self.origin_file,
                missing_origin=True,
            )
            return

        task_state = TaskState(origin_path=origin_path)
        self.tasks[id(task)] = task_state

        try:
            origin_matches = list(self.match_fn(origin_path))
        except OriginQueryError as exc:
            task_state.parse_error = str(exc)
            return

        origin_artist = next((sanitize_value(key, value) for key, value in origin_matches if key == "artist"), "")
        if self._remove_conflicting_albumartist(task, origin_artist):
            # Recompute likely tags after removing the conflicting field.
            pass

        likelies, _consensus = get_most_common_tags(task.items)
        for tag in BEETS_TO_LABEL:
            task_state.tag_compare[tag] = TagComparison(
                tagged=str(likelies.get(tag, "") or ""),
                active=self._active_for(tag),
            )

        for key, value in origin_matches:
            if key in BEETS_TO_LABEL:
                if task_state.tag_compare[key].origin:
                    continue

                tagged_value = task_state.tag_compare[key].tagged
                origin_value = sanitize_value(key, value)
                task_state.tag_compare[key].origin = origin_value

                if key not in CONFLICT_FIELDS or not tagged_value or not origin_value:
                    continue

                if key == "catalognum":
                    tagged_value = normalize_catno(tagged_value)
                    origin_value = normalize_catno(origin_value)

                if tagged_value != origin_value:
                    task_state.conflict = True
            else:
                task_state.display_fields[key] = value

        task_state.metadata_urls = self._extract_metadata_urls(origin_path)

        if task_state.conflict and not self.use_origin_on_conflict:
            return

        for item in task.items:
            for tag, entry in task_state.tag_compare.items():
                if tag not in self.tag_patterns:
                    continue

                origin_value: str | int = entry.origin
                if tag == "year" and entry.origin:
                    origin_value = int(entry.origin) if entry.origin.isdigit() else ""
                item[tag] = origin_value

            if item.get("media") and item.get("catalognum"):
                if self.preserve_media_with_catalognum:
                    self._log.debug(
                        "Preserving media for {} because preserve_media_with_catalognum is enabled",
                        item.path,
                    )
                else:
                    self._emit_visible("Removing media field (has catalognum)")
                    del item["media"]
                    task_state.tag_compare["media"].active = False

import os
from collections import OrderedDict
from pathlib import Path

from beets import config
from beets.importer import ImportTask
from beets.library import Item

from beetsplug.originquery import OriginQuery
from beetsplug.originquery.plugin import (
    BEETS_TO_LABEL,
    CONFLICT_FIELDS,
    SUPPORTED_METADATA_SOURCES,
    SUPPORTED_PROVIDERS,
    normalize_catno,
    scan_file_for_metadata_urls,
)


def configure_originquery(
    origin_file: str = "origin.yaml",
    *,
    musicbrainz_extra_tags: list[str] | None = None,
    remove_conflicting_albumartist: bool = False,
    preserve_media_with_catalognum: bool = False,
    use_origin_on_conflict: bool = False,
    tag_patterns: dict[str, str] | None = None,
):
    config.clear()
    config.add(
        {
            "originquery": {
                "origin_file": origin_file,
                "tag_patterns": tag_patterns or {"artist": "$.Artist", "album": "$.Name"},
                "remove_conflicting_albumartist": remove_conflicting_albumartist,
                "preserve_media_with_catalognum": preserve_media_with_catalognum,
                "use_origin_on_conflict": use_origin_on_conflict,
            }
        }
    )
    if musicbrainz_extra_tags is not None:
        config.add({"musicbrainz": {"extra_tags": musicbrainz_extra_tags}})


def make_task(album_dir: Path, **item_fields):
    track_path = album_dir / item_fields.pop("filename", "01.flac")
    track_path.write_bytes(b"")
    item = Item(path=os.fsencode(track_path), **item_fields)
    return ImportTask(os.fsencode(album_dir), [os.fsencode(track_path)], [item]), item


def test_plugin_importable():
    import beetsplug.originquery

    assert hasattr(beetsplug.originquery, "OriginQuery")


def test_beets_to_label_is_ordered_dict():
    assert isinstance(BEETS_TO_LABEL, OrderedDict)


def test_beets_to_label_keys_and_values():
    expected = OrderedDict(
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
    assert expected == BEETS_TO_LABEL


def test_beets_to_label_order_is_stable():
    assert list(BEETS_TO_LABEL.keys()) == [
        "artist",
        "album",
        "media",
        "year",
        "country",
        "label",
        "barcode",
        "catalognum",
        "albumdisambig",
    ]


def test_conflict_fields_content_and_type():
    assert isinstance(CONFLICT_FIELDS, list)
    assert CONFLICT_FIELDS == ["barcode", "catalognum", "media", "artist"]


def test_conflict_fields_are_known_keys():
    missing = [field for field in CONFLICT_FIELDS if field not in BEETS_TO_LABEL]
    assert missing == []


def test_supported_metadata_sources_are_stable():
    assert SUPPORTED_METADATA_SOURCES == ["musicbrainz"]


def test_supported_providers_are_stable():
    assert SUPPORTED_PROVIDERS == ["discogs", "bandcamp"]


def test_uppercase():
    assert normalize_catno("abc") == "ABC"


def test_remove_spaces():
    assert normalize_catno("AB 12") == "AB12"


def test_remove_hyphens():
    assert normalize_catno("AB-12") == "AB12"


def test_combined_normalization():
    assert normalize_catno("ab - 12 cd") == "AB12CD"


def test_already_normalized():
    assert normalize_catno("AB12CD") == "AB12CD"


def test_empty_string_catno():
    assert normalize_catno("") == ""


def test_scan_file_for_metadata_urls_finds_bbcode_link(tmp_path):
    origin_file = tmp_path / "origin.txt"
    origin_file.write_text(
        "[url]https://www.discogs.com/release/12345-sample[/url]\n",
        encoding="utf-8",
    )

    assert scan_file_for_metadata_urls(origin_file, "discogs") == "https://www.discogs.com/release/12345-sample"


def test_scan_file_for_metadata_urls_finds_plain_link(tmp_path):
    origin_file = tmp_path / "origin.txt"
    origin_file.write_text(
        "See https://artist.bandcamp.com/album/sample for details.\n",
        encoding="utf-8",
    )

    assert scan_file_for_metadata_urls(origin_file, "bandcamp") == "https://artist.bandcamp.com/album/sample"


def test_scan_file_for_metadata_urls_returns_none_for_missing_provider(tmp_path):
    origin_file = tmp_path / "origin.txt"
    origin_file.write_text("https://example.com/no-provider-here\n", encoding="utf-8")

    assert scan_file_for_metadata_urls(origin_file, "discogs") is None


def test_originquery_works_without_extra_tags(tmp_path):
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "origin.yaml").write_text("Artist: Origin Artist\nName: Origin Album\n", encoding="utf-8")
    configure_originquery(musicbrainz_extra_tags=None, use_origin_on_conflict=True)

    task, item = make_task(album_dir, artist="Tagged Artist", album="Tagged Album")
    plugin = OriginQuery()

    plugin.import_task_start(task, None)

    assert plugin.extra_tags == []
    assert plugin.extra_tags_source is None
    assert item.artist == "Origin Artist"
    assert item.album == "Origin Album"
    assert plugin.tasks[id(task)].tag_compare["artist"].active is True


def test_originquery_uses_album_directory_for_single_item_task(tmp_path):
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "origin.yaml").write_text("Artist: Origin Artist\nName: Origin Album\n", encoding="utf-8")
    configure_originquery(musicbrainz_extra_tags=["year"])

    task, _item = make_task(album_dir, artist="Tagged Artist", album="Tagged Album")
    plugin = OriginQuery()

    plugin.import_task_start(task, None)

    assert plugin.tasks[id(task)].origin_path == album_dir / "origin.yaml"
    assert plugin.tasks[id(task)].missing_origin is False


def test_originquery_uses_task_paths_before_toppath(tmp_path):
    import_root = tmp_path / "downloads"
    album_dir = import_root / "album"
    album_dir.mkdir(parents=True)
    track_path = album_dir / "01.flac"
    track_path.write_bytes(b"")
    (album_dir / "origin.yaml").write_text(
        "Artist: Origin Artist\nName: Origin Album\n",
        encoding="utf-8",
    )
    configure_originquery(musicbrainz_extra_tags=["year"])

    item = Item(path=os.fsencode(track_path), artist="Tagged Artist", album="Tagged Album")
    task = ImportTask(os.fsencode(import_root), [os.fsencode(album_dir)], [item])
    plugin = OriginQuery()

    plugin.import_task_start(task, None)

    assert plugin.tasks[id(task)].origin_path == album_dir / "origin.yaml"
    assert plugin.tasks[id(task)].missing_origin is False


def test_originquery_removes_conflicting_albumartist_when_enabled(tmp_path):
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "origin.yaml").write_text("Artist: Origin Artist\nName: Origin Album\n", encoding="utf-8")
    configure_originquery(
        musicbrainz_extra_tags=["year"],
        remove_conflicting_albumartist=True,
    )

    task, item = make_task(
        album_dir,
        artist="Origin Artist",
        album="Tagged Album",
        albumartist="Wrong Album Artist",
    )
    plugin = OriginQuery()

    plugin.import_task_start(task, None)

    assert item.albumartist == ""
    assert plugin.tasks[id(task)].tag_compare["artist"].tagged == "Origin Artist"
    assert item.artist == "Origin Artist"


def test_originquery_records_parse_errors_without_mutating_items(tmp_path):
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "origin.yaml").write_text("Artist: [broken\n", encoding="utf-8")
    configure_originquery(musicbrainz_extra_tags=["year"])

    task, item = make_task(album_dir, artist="Tagged Artist", album="Tagged Album")
    plugin = OriginQuery()

    plugin.import_task_start(task, None)

    assert plugin.tasks[id(task)].parse_error is not None
    assert item.artist == "Tagged Artist"
    assert item.album == "Tagged Album"


def test_originquery_removes_media_when_catalognum_present(tmp_path):
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "origin.yaml").write_text(
        "Artist: Tagged Artist\nName: Tagged Album\nMedia: WEB\nCatalog number: ABC-123\n",
        encoding="utf-8",
    )
    configure_originquery(
        musicbrainz_extra_tags=["media", "catalognum"],
        tag_patterns={
            "artist": "$.Artist",
            "album": "$.Name",
            "media": "$.Media",
            "catalognum": "$['Catalog number']",
        },
    )

    task, item = make_task(album_dir, artist="Tagged Artist", album="Tagged Album")
    plugin = OriginQuery()

    plugin.import_task_start(task, None)

    assert item.get("catalognum") == "ABC-123"
    assert not item.get("media")
    assert plugin.tasks[id(task)].tag_compare["media"].active is False


def test_originquery_media_removal_is_silent_by_default(tmp_path, capsys):
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "origin.yaml").write_text(
        "Artist: Tagged Artist\nName: Tagged Album\nMedia: WEB\nCatalog number: ABC-123\n",
        encoding="utf-8",
    )
    configure_originquery(
        musicbrainz_extra_tags=["media", "catalognum"],
        tag_patterns={
            "artist": "$.Artist",
            "album": "$.Name",
            "media": "$.Media",
            "catalognum": "$['Catalog number']",
        },
    )

    task, _item = make_task(album_dir, artist="Tagged Artist", album="Tagged Album")
    plugin = OriginQuery()

    plugin.import_task_start(task, None)
    captured = capsys.readouterr()

    assert "Removing media field (has catalognum)" not in captured.err


def test_emit_visible_uses_ui_output(capsys):
    plugin = OriginQuery()

    plugin._emit_visible("hello")
    captured = capsys.readouterr()

    assert captured.out == "plugin: hello\n"
    assert captured.err == ""


def test_originquery_cleans_task_state_after_choice(tmp_path):
    album_dir = tmp_path / "album"
    album_dir.mkdir()
    (album_dir / "origin.yaml").write_text("Artist: Origin Artist\nName: Origin Album\n", encoding="utf-8")
    configure_originquery(musicbrainz_extra_tags=["year"])

    task, _item = make_task(album_dir, artist="Tagged Artist", album="Tagged Album")
    plugin = OriginQuery()

    plugin.import_task_start(task, None)
    assert id(task) in plugin.tasks

    plugin.import_task_choice(task, None)

    assert id(task) not in plugin.tasks

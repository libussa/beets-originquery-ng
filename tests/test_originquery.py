from collections import OrderedDict

from beetsplug.originquery.plugin import (
    BEETS_TO_LABEL,
    CONFLICT_FIELDS,
    SUPPORTED_METADATA_SOURCES,
    SUPPORTED_PROVIDERS,
    escape_braces,
    normalize_catno,
    scan_file_for_metadata_urls,
)


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
    assert BEETS_TO_LABEL == expected


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
    missing = [f for f in CONFLICT_FIELDS if f not in BEETS_TO_LABEL]
    assert missing == []


def test_supported_metadata_sources_are_stable():
    assert SUPPORTED_METADATA_SOURCES == ["musicbrainz", "discogs"]


def test_supported_providers_are_stable():
    assert SUPPORTED_PROVIDERS == ["discogs", "bandcamp"]


def test_no_braces():
    assert escape_braces("hello") == "hello"


def test_opening_brace():
    assert escape_braces("{") == "{{"


def test_closing_brace():
    assert escape_braces("}") == "}}"


def test_both_braces():
    assert escape_braces("{}") == "{{}}"


def test_text_with_braces():
    assert escape_braces("a{b}c") == "a{{b}}c"


def test_multiple_braces():
    assert escape_braces("{x}{y}") == "{{x}}{{y}}"


def test_empty_string_escape_braces():
    assert escape_braces("") == ""


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

    assert (
        scan_file_for_metadata_urls(origin_file, "discogs")
        == "https://www.discogs.com/release/12345-sample"
    )


def test_scan_file_for_metadata_urls_finds_plain_link(tmp_path):
    origin_file = tmp_path / "origin.txt"
    origin_file.write_text(
        "See https://artist.bandcamp.com/album/sample for details.\n",
        encoding="utf-8",
    )

    assert (
        scan_file_for_metadata_urls(origin_file, "bandcamp")
        == "https://artist.bandcamp.com/album/sample"
    )


def test_scan_file_for_metadata_urls_returns_none_for_missing_provider(tmp_path):
    origin_file = tmp_path / "origin.txt"
    origin_file.write_text("https://example.com/no-provider-here\n", encoding="utf-8")

    assert scan_file_for_metadata_urls(origin_file, "discogs") is None

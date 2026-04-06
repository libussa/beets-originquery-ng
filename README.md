beets-originquery
=================

`originquery` is a beets plugin that reads supplemental metadata from an origin
file in each import directory and injects that data into the importer before
candidate lookup.

This is most useful when audio files only have minimal tags, but the release
directory also contains richer metadata such as edition year, catalog number,
label, media, or release notes.

What it does
------------

During `beet import`, the plugin can:

- read a text, JSON, YAML, or YML origin file from the album directory
- map fields from that file onto beets item fields before lookup
- surface the tagged-vs-origin values during candidate selection
- detect conflicts between tagged and origin data
- optionally remove a conflicting `albumartist` before beets derives search
  terms
- optionally scan the origin file for provider URLs such as Discogs or Bandcamp

Current beets behavior
----------------------

`originquery` is designed around current beets metadata-source behavior:

- `musicbrainz.extra_tags` is the supported way to add release-disambiguating
  search fields such as `year`, `catalognum`, `media`, and `label`
- Discogs can still be enabled alongside this plugin, but current beets does
  not document a matching `discogs.extra_tags` setting
- if no `musicbrainz.extra_tags` are configured, `originquery` still works for
  `artist` and `album`, but the richer MusicBrainz-specific search terms are
  unavailable

Installation
------------

Install a current beets release and then install this plugin:

    pip install beets
    pip install git+https://github.com/x1ppy/beets-originquery

The development bench in this repository currently validates the plugin against
beets `2.8.0`.

Minimal configuration:

    plugins:
      - musicbrainz
      - originquery

    musicbrainz:
      extra_tags: [year, catalognum, media, label, albumdisambig]

    originquery:
      origin_file: origin.yaml
      tag_patterns:
        artist: $.Artist
        album: $.Name
        year: $['Edition year']
        label: $['Record label']
        catalognum: $['Catalog number']
        media: $.Media
        albumdisambig: $.Edition

If you also use Discogs, enable it normally in beets:

    plugins:
      - musicbrainz
      - discogs
      - originquery

The plugin does not require Discogs, and it does not currently rely on any
Discogs-specific `extra_tags` setting.

Configuration
-------------

`originquery` looks for an origin file at the root of each import directory.
The filename may be a glob:

    originquery:
      origin_file: origin-*.yaml

If multiple files match, the first alphanumerically sorted match is used.

Supported options:

    originquery:
      origin_file: origin.yaml
      origin_type: yaml
      use_origin_on_conflict: no
      preserve_media_with_catalognum: no
      remove_conflicting_albumartist: no
      tag_patterns:
        artist: $.Artist
        album: $.Name
        year: $['Edition year']
        label: $['Record label']
        catalognum: $['Catalog number']
        media: $.Media
        albumdisambig: $.Edition
        tags: $.Tags

Options:

- `origin_file`: filename or glob, relative to the album directory
- `origin_type`: `text`, `json`, `yaml`, or `yml`; when omitted, the file
  extension is used
- `use_origin_on_conflict`: when `yes`, origin values win if conflict fields do
  not match
- `preserve_media_with_catalognum`: when `no`, the plugin removes `media` if
  both `media` and `catalognum` are present
- `remove_conflicting_albumartist`: when `yes`, a unanimous tagged
  `albumartist` that disagrees with origin `artist` is cleared before search

Import fields
-------------

The following `tag_patterns` keys are understood as beets fields:

- `artist`
- `album`
- `media`
- `year`
- `country`
- `label`
- `barcode`
- `catalognum`
- `albumdisambig`

Any additional keys are treated as display-only fields and are shown in the
import summary, but they are not mapped onto beets search fields.

File formats
------------

Text origin files
~~~~~~~~~~~~~~~~~

For `text` origin files, each pattern must be a regular expression with exactly
one capture group:

    originquery:
      origin_file: origin.txt
      origin_type: text
      tag_patterns:
        media: 'media=(.+)'
        year: 'year=(\d{4})'
        label: 'label=(.+)'
        catalognum: 'catalognum=(.+)'

JSON origin files
~~~~~~~~~~~~~~~~~

For `json` origin files, each pattern must be a JSONPath expression:

    originquery:
      origin_file: origin.json
      tag_patterns:
        artist: $.Artist
        album: $.Name
        year: $['Edition year']
        label: $['Record label']
        catalognum: $['Catalog number']

YAML / YML origin files
~~~~~~~~~~~~~~~~~~~~~~~

YAML files use the same JSONPath-based `tag_patterns` as JSON:

    originquery:
      origin_file: origin.yml
      tag_patterns:
        artist: $.Artist
        album: $.Name
        year: $['Edition year']
        label: $['Record label']
        catalognum: $['Catalog number']

Conflicts
---------

The plugin treats the following fields as conflict-sensitive:

- `artist`
- `barcode`
- `catalognum`
- `media`

When one of those fields differs between existing tags and origin data, the
plugin reports a conflict during import.

Default behavior:

- tagged data wins
- origin data is still displayed for inspection

To make origin data win instead:

    originquery:
      use_origin_on_conflict: yes

Albumartist cleanup
-------------------

beets derives the likely album artist from the imported items before lookup. If
all tracks agree on `albumartist`, that value can override `artist` in the
derived search terms.

When your files have a wrong `albumartist` but the origin file has the correct
`artist`, enable:

    originquery:
      remove_conflicting_albumartist: yes

If the tagged `albumartist` is unanimous and differs from the origin artist, it
is cleared before search.

Media workaround
----------------

Beets weighs `media` strongly during matching, and in practice that can drown
out a more useful catalog-number match. By default, `originquery` removes the
`media` field when both `media` and `catalognum` are present:

    originquery:
      preserve_media_with_catalognum: no

If you want to keep `media`:

    originquery:
      preserve_media_with_catalognum: yes

URL extraction
--------------

The plugin can scan the raw origin file for provider URLs and show them during
import. This is currently supported for:

- `discogs`
- `bandcamp`

Enable extraction in the provider configuration:

    discogs:
      extract_urls_from_origin: yes

    bandcamp:
      extract_urls_from_origin: yes

This feature is display-oriented at the moment; it does not automatically turn
those URLs into beets lookup IDs.

Development
-----------

Local checks:

    uv sync --group dev
    uv run ruff check .
    uv run ty check
    uv run pytest

The repository also includes a local importer bench wired to real sample albums:

    ./.bench/setup.sh
    ./.bench/reset-state.sh
    ./.bench/import-album.sh '2018-For Emma, Forever Ago (Reissue)'

The default development toolchain uses `ruff`, `ty`, and `pytest`.

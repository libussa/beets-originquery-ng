beets-originquery-ng
====================

The published package name is `beets-originquery-ng`. The beets plugin name is
`originquery`.

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

Installation
------------

Install beets and then install this plugin:

    pip install "beets>=2.5.1"
    pip install beets-originquery-ng

Supported Python versions: `3.10` through `3.13`.

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

If you use Discogs, enable it in beets:

    plugins:
      - musicbrainz
      - discogs
      - originquery

Configuration
-------------

`originquery` looks for an origin file in the source directory for each album
task. When you import a parent directory, it resolves against the album
subdirectory, not the top-level import root. The filename may be a glob:

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

For `json` origin files, each pattern may be either a JSONPath expression or
an ordered list of JSONPath expressions for fallback lookup:

    originquery:
      origin_file: origin.json
      tag_patterns:
        artist: $.Artist
        album: $.Name
        year: $['Edition year']
        label: $['Record label']
        catalognum: $['Catalog number']
        country:
          - $['Country']
          - $['Release country']

YAML / YML origin files
~~~~~~~~~~~~~~~~~~~~~~~

YAML files use the same JSONPath-based `tag_patterns` as JSON, including
fallback lists:

    originquery:
      origin_file: origin.yml
      tag_patterns:
        artist: $.Artist
        album: $.Name
        year:
          - $['Edition year']
          - $['Original year']
        label:
          - $['Record label']
          - $['Original release label']
        catalognum:
          - $['Catalog number']
          - $['Original catalog number']

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

Media handling
--------------

By default, `originquery` removes the `media` field when both `media` and
`catalognum` are present:

    originquery:
      preserve_media_with_catalognum: no

If you want to keep `media`:

    originquery:
      preserve_media_with_catalognum: yes

URL extraction
--------------

The plugin can scan the raw origin file for provider URLs and show them during
import. Supported providers:

- `discogs`
- `bandcamp`

Enable extraction in the provider configuration:

    discogs:
      extract_urls_from_origin: yes

    bandcamp:
      extract_urls_from_origin: yes

This feature displays matched URLs. It does not convert them into lookup IDs.

Development
-----------

Local checks:

    uv sync --group dev
    uv run ruff check .
    uv run ty check
    uv run pytest

The repository also includes a local importer bench for sample albums:

    ./.bench/setup.sh
    ./.bench/reset-state.sh
    ./.bench/import-album.sh '2018-For Emma, Forever Ago (Reissue)'

The default development toolchain uses `ruff`, `ty`, and `pytest`.

Release process
---------------

Releases are created from Git tags in GitHub Actions and published to PyPI.

1. Update `project.version` in `pyproject.toml`.
2. Merge the version bump to `master`.
3. Push a tag in the form `vX.Y.Z` that matches `project.version`.

The release workflow then:

- validates the tag against `pyproject.toml`
- reruns lint, type-check, tests, and packaging checks
- builds `sdist` and `wheel`
- publishes `beets-originquery-ng` to PyPI
- creates a GitHub Release with auto-generated notes and attached artifacts

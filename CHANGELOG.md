# Changelog

## Unreleased

- Made Playwright a standard runtime dependency so a normal installation includes all
  advertised Otter functionality; removed the obsolete Otter extra.

- Permanently renamed the transformation command and package area to `trweave`.
- Added schema-v1 provider, weave, and output profiles with case-insensitive lookup.
- Added Gemini REST transformation using credentials retrieved from `pass`.
- Added strict JSON response validation and deep preservation of input packets.
- Added timezone-aware atomic insert, append, and non-overwriting create output.
- Added date-only journal headings; same-date entries are retained with a warning.
- Added offline unit and five-category disposable-vault end-to-end coverage.
- Added an explicitly gated live Gemini functional test.

## 0.1.0

- Added `trwinp`, the schema-v1 packet contract, run correlation, safe optional
  diagnostics, configuration creation, Otter acquisition, and offline tests.

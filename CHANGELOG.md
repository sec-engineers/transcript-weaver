# Changelog

## Unreleased

- Consolidated cleaned text in `weave.update_transcript`, removing duplicate
  `weave.content` and top-level `updated_transcript` output while keeping the source
  `transcript` immutable.
- Added paired, sensitive original/provider JSON diagnostics for other preservation
  failures under a retention-bounded `packet-failures` directory.
- Renamed the packaged weave profile to `franks-example` and corrected its
  Gratitude, Dream, SEs, Sacred, and Unknown journal routing and filenames.
- Added reliable Otter duration metadata and deterministic Unknown routing for
  recordings longer than five minutes; updated cleanup guidance to 72 columns.
- Added dashed separation and date-specific stderr diagnostics for duplicate-date
  journal entries.
- Added the project `trw_version` packet field and an atomic, locked distribution-build
  command with automatic four-digit build increments and rollback on failure.
- Made packet `trw_version` informational-only bug-report metadata; downstream stages
  preserve it when present without using it as a compatibility gate.
- Updated live Otter compatibility for relative recording links, Today/Yesterday
  timestamps, and the current transcript More Options selector; unexpected browser
  failures now retain a concise underlying cause.
- Close each dedicated Otter Chrome process launched by Weaver after acquisition, including failure paths.
- Profile errors now list configured choices and suggest likely spelling corrections.
- Strengthened the Gemini system contract so `weave` is added at the packet top level.

- Added field-specific configuration diagnostics, safe first-run provisioning of the
  prototype-derived example prompt, and a ready-to-run CWD-relative test vault profile.
- Standardized documented vault configuration on a path object while retaining legacy
  path-string compatibility.

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

# Changelog

## 1.1.0003 - 2026-08-26

- Added `trwprep dom` and `trwprep otter` to prepare dedicated, reusable
  Windows Chrome profiles and consent-based WSL DevTools forwarding.
- Added `trwinp dom` to capture the current DOM, title, and URL from exactly
  one prepared Chrome tab without navigating or closing it.
- Made `trwprep` display its proposed elevated Windows commands before consent
  and accept the CIDR notation Windows uses when verifying scoped firewall rules.

## 1.1.0002 - 2026-08-22

- Made distribution builds reproducible by using the version recorded in source
  without incrementing or otherwise modifying it.

## 1.1.0001 - 2026-08-22

- Added dotted packet placeholders to output body formats while retaining the
  computed `{date}`, `{time}`, and soft-wrapped `{content}` placeholders.
- Restricted create-operation filename placeholders to `{date}` and `{time}`.

## 1.0.0011 - 2026-08-13 (Initial public release)

- Initial public release.

# Changelog

## 1.1.0009 - 2026-10-21

- Made the offline test suite portable across Linux, Windows, and macOS,
  including native path, home-directory, and file-mode behavior.
- Added Windows timezone data so configured IANA timezones work without a
  separately installed system timezone database.
- Clarified CI job names, pinned the Linux image, and updated GitHub actions
  to their current Node.js 24 releases.

## 1.1.0008 - 2026-10-21

- Added the GPL license file and project links to the separately
  distributed HighLevel plugin package.
- Added a repeatable release checklist covering coordinated core and
  plugin validation, publication, and post-publication verification.
- Corrected the pipeline contract documentation to state that
  distribution builds use the recorded version without modifying it.
- Added repository guidance for actionable, privacy-safe errors and
  contributor-friendly platform boundaries and tests.

## 1.1.0007 - 2026-10-21

- Added a versioned output-plugin boundary and an official, separately
  installable HighLevel plugin built from the same repository and project
  version as core TRW.
- Added a conservative HighLevel contact mapping example: every incoming
  field must be mapped or ignored, ambiguous identities and changed
  nonempty values stop before writes, missing input never clears a contact,
  and per-field preserve or replace policies are explicit.
- Added offline HighLevel mapping, identity, conflict, discovery, and
  packaging tests plus an opt-in live contact-lifecycle test using runtime
  credentials and ownership-checked cleanup.
- Added Windows and macOS offline CI coverage while retaining Linux
  coverage for every supported Python version.
- Added a 30-second current-DOM capture timeout so an unresponsive page
  produces a clean, retryable error instead of waiting indefinitely.
- Added optional phone extraction to the packaged LinkedIn profile prompt.
- Made missing HighLevel custom-field errors list the available contact field
  names, keys, and IDs so configuration spelling can be corrected directly.
- Matched David's sample output profile to his existing HighLevel About Contact
  and LinkedIn URL fields while explicitly ignoring unsupported headline and
  displayed-location values.
- Made HighLevel review conflicts show the existing and incoming values
  together so whitespace, spelling, and punctuation differences are visible.
- Rejected duplicate HighLevel destination mappings, including different
  references which resolve to the same custom field, before contact writes.
- Made Gemini per-minute quota failures use a fixed one-minute retry delay and
  report that wait in minutes while retaining normal transient backoff.

## 1.1.0006 - 2026-08-29

- Added `trwprep validate-config` to validate schema-2 configurations and offer
  a confirmed, backed-up, atomic migration for the shipped schema-1 form.
- Made ordinary schema-version failures identify the required version and lead
  directly to the validation and migration helper.

## 1.1.0005 - 2026-08-29

- Replaced named provider blocks with global provider, model, and explicit
  API-key-source defaults plus independent per-weave-profile overrides.
- Added environment, protected-file, command, and discouraged literal API-key
  sources with secret-safe failures and literal-use warnings.
- Added a dedicated configuration reference and reduced the README to stable
  configuration guidance and current-help pointers.
- Added offline coverage for a controlled `trwinp otter` failure when no usable
  recording is available.

## 1.1.0004 - 2026-08-26

- Generalized `trweave` so prompts may add any nonempty structured result
  beneath `weave` without requiring journal-specific `type` and
  `update_transcript` fields.
- Added David's LinkedIn structured-extraction example, with optional profile
  fields beneath `weave.linkedin` and no invented placeholders for missing
  information.
- Added one-hour, explicitly enabled permission for sensitive debug artifacts
  across pipeline commands and raw failed-provider-response capture for
  `trweave --debug-artifacts`.
- Clarified artifact subcommands in `trwprep --help`, wrapped interactive prose
  to 72 columns, and made repeated enablement extend permission without another
  confirmation.
- Wrapped pipeline diagnostics to 72 columns, placed available-profile lists on
  their own line, and removed the redundant per-invocation artifact warning.
- Made weave-only provider responses the preferred `trweave` protocol and merge
  them locally into the authoritative input packet, while retaining validation
  support for legacy complete-packet responses.

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

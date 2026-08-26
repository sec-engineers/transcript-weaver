# Pipeline contracts

## `trwinp`

Reads a configured source and emits one schema-v1 packet. `trw_version` identifies the
whole project build that created the packet; it is separate from `schema_version` and
uses `major.minor.build` with four build digits. `datetime` is recording time in
canonical UTC; `run.id` is correlation identity, not recording time. Reliable Otter
media duration is stored as `metadata.duration_seconds`.

## Configuration

First-run setup atomically provisions `config.json` and its example prompt files.
Existing files are never overwritten. Configuration errors identify their full field
path and list missing or unexpected fields. Vault path objects use `relative_to` values
`cwd` or `config` for relative paths and omit it for absolute or `~` paths. Reserved
`_comment` keys provide inline documentation and are ignored by runtime validation.

## `trweave PROMPT_OR_PROFILE`

Reads exactly one JSON object and emits exactly one enriched JSON object. Direct
prompt paths use Gemini; profiles name both provider and either inline `prompt`
or `prompt_file`. Every original field is immutable. The preferred provider response
contains only a nonempty top-level `weave` object; `trweave` merges it into the
authoritative input packet locally. The selected prompt defines the contents beneath
`weave`. When `weave.type` or `weave.update_transcript` is present, it must retain its
established nonempty-string form. Legacy providers may still return a complete enriched
packet and receive strict preservation validation. A legacy provider replacement for
`transcript` is retained as the added nested `weave.update_transcript` field when that
compatibility recovery is possible, while the original `transcript` remains exact. No
duplicate top-level transformed-transcript field is emitted.
Other changed or deleted input fields are errors. A packet's `trw_version` is
informational only: it is preserved exactly when present, but never used to reject a
packet or decide compatibility, and legacy packets without it remain accepted. A
reliable duration greater than 300 seconds deterministically overrides a returned
`weave.type` category to `unknown`; structured results without `weave.type` are
unaffected. Exactly 300 seconds does not trigger the override.

## `trwout OUTPUT_PROFILE`

Reads one enriched object, extracts category/content via dotted paths, converts
UTC recording time to the configured IANA timezone, renders documented
placeholders, and performs one safe operation. `insert` is ascending by local
calendar date. Same-date entries are both retained, with the newer arrival after
existing same-date entries, a `---` separator, and a date-specific warning on stderr. `append` and non-overwriting
`create` are deterministic. Existing-file changes use atomic replacement.

`weave.type` selects the case-insensitive destination key. `weave.update_transcript` is rendered into that destination's `format`. Neither output routing nor
classification is hard-coded into the commands.

## Process channels and diagnostics

Packet-producing success writes one JSON object to stdout. Failure writes no
partial JSON. `trwout` success has no stdout. Errors and warnings go to stderr.
Persistent logs are opt-in and must exclude packet text, prompts, response
content, secrets, and journal contents. The exception is an immutable-field failure:
`trweave` saves complete `original.json` and `provider.json` packets beneath the
per-user `packet-failures` directory. They are sensitive, named by run ID, and retained
according to `logging.retained_runs` so failures are diffable without unbounded growth.
Sensitive debug artifacts require both a current one-hour permission created by
`trwprep artifacts enable` and `--debug-artifacts` on the individual pipeline command.
An invalid `trweave` provider response is retained only with both forms of consent and
may contain the complete input packet. Successful provider responses are not retained.

## Distribution build

`src/transcript_weaver/_version.py` is authoritative. Run
`python -m transcript_weaver.build` for an intentional distribution build. It locks
against concurrency, increments the four-digit build exactly once, builds the wheel and
source distribution with that version, and restores the prior version on failure.
Metadata inspection, imports, tests, and installation do not increment it. Python package metadata canonicalizes `1.0.0001` to its PEP 440-equivalent `1.0.1`, while the packaged source and pipeline packets retain the four-digit application build.

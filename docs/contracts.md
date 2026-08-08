# Pipeline contracts

## `trwinp`

Reads a configured source and emits one schema-v1 packet. `datetime` is recording
time in canonical UTC; `run.id` is correlation identity, not recording time.

## `trweave PROMPT_OR_PROFILE`

Reads exactly one JSON object and emits exactly one enriched JSON object. Direct
prompt paths use Gemini; profiles name both provider and either inline `prompt`
or `prompt_file`. The model must preserve every original value and add a usable
`weave` object containing nonempty `type` and `content` strings. Validation is
strict and provider output is never silently repaired.

## `trwout OUTPUT_PROFILE`

Reads one enriched object, extracts category/content via dotted paths, converts
UTC recording time to the configured IANA timezone, renders documented
placeholders, and performs one safe operation. `insert` is ascending by local
calendar date. Same-date entries are both retained, with the newer arrival after
existing same-date entries and a warning on stderr. `append` and non-overwriting
`create` are deterministic. Existing-file changes use atomic replacement.

`weave.type` selects the case-insensitive destination key. `weave.content` is
rendered into that destination's `format`. Neither output routing nor
classification is hard-coded into the commands.

## Process channels and diagnostics

Packet-producing success writes one JSON object to stdout. Failure writes no
partial JSON. `trwout` success has no stdout. Errors and warnings go to stderr.
Persistent logs are opt-in and must exclude packet text, prompts, response
content, secrets, and journal contents.

# Pipeline contracts

## Schema version 1

A `trwinp` packet has these required top-level fields: integer `schema_version`
(currently `1`), `run`, UTC `datetime` in `YYYY-MM-DDTHH:MM:SSZ`, `source`, nonempty
original `transcript`, and reserved object `metadata`. `source.type` is required;
`source.name` and opaque `source.reference` are optional.

`run.id` has the filename-safe form `YYYYMMDD-HHMMSS-xxxx`, where the timestamp is UTC
and `xxxx` is random hexadecimal collision protection. It correlates pipeline stages
and diagnostics; it is not the transcript's recording time. Every command preserves a
valid incoming ID, generates one for a legacy or manually created packet when absent,
and rejects malformed values. Consumers must reject unsupported schema versions rather
than guessing.

## Future `trwclean`

`trwclean MASTER_PROMPT_FILE` will read one complete packet from stdin and a prompt
from the named UTF-8 file. A Gemini provider will receive both. The command must
validate that every input field, including `run`, is present and unchanged and that the
response adds a usable `clean` object with prompt-defined `type` and transformed
`content`. Categories will not be hard-coded. Success emits only the complete enriched
JSON packet.

The current placeholder may inspect an incoming packet only to preserve or create its
run ID for requested logging. It emits no success packet and does not claim cleaning is
implemented.

## Future `trwout`

`trwout OUTPUT_RULES.json` will read an enriched packet, preserve `run`, match
`clean.type`, and invoke a deterministic Python writer described by—not implemented
inside—the rules file. Likely writers are create-file, append, and chronological
insertion. Tests will use a disposable miniature vault. Existing-file writes must be
atomic. Source deletion is separate and may run only after persistence is verified.

The current placeholder may inspect an incoming packet only for run correlation. It
performs no output persistence.

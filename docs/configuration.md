# Configuration

Transcript Weaver creates `config.json` in the platform's per-user
configuration directory on first use. It never overwrites or automatically
migrates an existing file.

## Provider defaults and weave overrides

Schema version 2 defines one default provider, model, and API-key source:

```json
{
  "schema_version": 2,
  "provider": "gemini",
  "model": "gemini-3.5-flash-lite",
  "api_key": "command(pass show api/gemini)"
}
```

Every weave profile inherits those values. A profile may override any of them:

```json
{
  "weave": {
    "ordinary": {
      "prompt_file": "prompts/ordinary.md"
    },
    "special": {
      "provider": "gemini",
      "model": "another-gemini-model",
      "api_key": "env(SPECIAL_GEMINI_API_KEY)",
      "prompt_file": "prompts/special.md"
    }
  }
}
```

An override applies only to that profile. Provider, model, and API-key source
are inherited independently. Transcript Weaver currently implements Gemini;
the configuration fields allow future providers without implying that they are
already supported.

A prompt supplied directly as a path, rather than selected through a weave
profile, uses all three global defaults.

## API-key sources

The source is always explicit. Transcript Weaver never guesses whether a value
is an environment variable, path, command, or literal key.

### `command(...)`

```json
"api_key": "command(pass show api/gemini)"
```

The command runs when the provider needs the key. Its first output line is used.
This works with `pass`, operating-system credential tools, and other commands;
Transcript Weaver does not require `pass`. Command failures are reported without
printing the command, its output, or the secret.

Only put commands you trust in this field. The command is run through the user's
shell so normal command arguments and credential-tool invocations work.

### `env(...)`

```json
"api_key": "env(GEMINI_API_KEY)"
```

The named environment variable supplies the key. Environment variables are
familiar and useful in managed environments, but they are not encrypted storage.

### `file(...)`

```json
"api_key": "file(~/.config/trw/gemini.key)"
```

The first line of the UTF-8 file supplies the key. Restrict the file so only the
account running Transcript Weaver can read it, and keep it outside repositories
and synchronized folders unless those locations are deliberately protected.

### `literal(...)`

```json
"api_key": "literal(the-key-here)"
```

This form is supported as an escape hatch, but it stores the secret directly in
`config.json`. Each use prints a warning to standard error without printing the
key. Prefer an external credential command, an environment variable, or a
protected file.

Never commit a configuration containing `literal(...)`, paste it into a bug
report, or include it with diagnostic material.

## Migrating from schema version 1

Schema version 1 provider blocks are intentionally not supported during normal
TRW operation. Validate the active configuration and, for the shipped
single-provider schema-1 form, receive an interactive migration offer with:

```bash
trwprep validate-config
```

TRW shows the configuration path and planned changes before asking permission.
If approved, it validates the complete converted configuration, creates a
non-overwriting byte-for-byte schema-1 backup, and atomically replaces the
active file. Declining or encountering an unsupported legacy shape leaves the
configuration unchanged. API keys are not resolved or displayed during this
process.

For a manual migration, back up the existing file, move its provider name,
model, and credential to the three global fields, and change `schema_version`
to 2. For the former `pass` credential:

```json
"api_key": "command(pass show api/gemini)"
```

Remove each weave profile's `provider` when it should inherit the global value.
Keep or add `provider`, `model`, or `api_key` only where that profile needs an
override.

The remaining `logging`, `weave`, and `out` structures retain their existing
roles. See the packaged `default-config.json` for a complete, validated example.

## Paths and output profiles

Prompt and vault path objects use `path` plus `relative_to: "cwd"` or
`relative_to: "config"` for relative paths. Omit `relative_to` for absolute and
home-relative paths. Existing path strings remain supported.

Each output profile's `vault` is the common root for its destinations. Optional
`destination_roots` provide reusable relative paths beneath that vault.
Destinations cannot escape the resolved vault with `..` or symbolic links.

Keys beginning with `_comment` are embedded documentation and are ignored.
Other unexpected keys are rejected.

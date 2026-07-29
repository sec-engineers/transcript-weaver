# Transcript Weaver

Transcript Weaver is an open-source, Unix-style transcript pipeline:

```text
trwinp -> normalized JSON -> trwclean -> enriched JSON -> trwout
```

Milestone 1 fully implements `trwinp stdin`, `trwinp file PATH`, and `trwinp
otter`. `trwclean` and `trwout` are installed placeholders: they report that their
processing stage is unavailable and return nonzero. They already share configuration,
run correlation, logging, and retention behavior without claiming to clean or persist
content. No source deletion or Obsidian-vault writing exists.

## Packet contract

Successful pipeline output is JSON only. Ordinary successful operation is silent on
standard error; standard error is reserved for warnings and errors.

```json
{
  "schema_version": 1,
  "run": {
    "id": "20260728-143012-a7f3"
  },
  "datetime": "2026-07-28T18:30:00Z",
  "source": {
    "type": "file",
    "name": "meeting.txt",
    "reference": "/path/to/meeting.txt"
  },
  "transcript": "Original transcript text",
  "metadata": {}
}
```

`datetime` is the transcript recording time normalized to
`YYYY-MM-DDTHH:MM:SSZ`. `run.id` is a separate UTC-based, sortable correlation ID.
Every stage preserves a valid incoming ID and generates one when missing, even without
logging. Invalid IDs are rejected before use in filenames.

## Installation and use

Transcript Weaver requires Python 3.10 or newer.

```bash
python -m pip install transcript-weaver
printf 'A transcript' | trwinp stdin > packet.json
trwinp file meeting.txt > packet.json
```

Otter support is optional:

```bash
python -m pip install 'transcript-weaver[otter]'
trwinp otter > packet.json
```

The WSL/Windows adapter starts or reuses a dedicated Windows Chrome session, waits for
manual authentication when needed, opens the first/newest visible recording, and uses
Otter's Copy Transcript action. It stores no Otter password and never deletes a
recording. See `docs/otter.md` for setup details.

## Configuration

The first execution of any command atomically creates a user-owned `config.json` from
the packaged default. Installation and package building do not create it. Existing
configuration is never overwritten, reset, merged, or migrated during upgrades.
Malformed or invalid configuration causes an actionable failure and remains untouched.
Unrecognized fields are currently rejected.

Locations:

- Windows: `%APPDATA%\Transcript Weaver\config.json`
- Linux: `$XDG_CONFIG_HOME/transcript-weaver/config.json`, or
  `~/.config/transcript-weaver/config.json`
- macOS: `~/Library/Application Support/Transcript Weaver/config.json`

The complete initial schema is:

```json
{
  "schema_version": 1,
  "logging": {
    "retained_runs": 5
  }
}
```

## Logging and sensitive artifacts

Users do not choose a log directory. Transcript Weaver uses:

- Windows: `%LOCALAPPDATA%\Transcript Weaver\Logs`
- Linux: `$XDG_STATE_HOME/transcript-weaver/log`, or
  `~/.local/state/transcript-weaver/log`
- macOS: `~/Library/Logs/Transcript Weaver`

No persistent log or logging directory is created during ordinary operation.

- `--log` records stage startup/completion, safe milestones, durations where
  available, and concise failures.
- `--verbose` implies `--log` and adds detailed decisions, adapter operations,
  selectors, timings, and tracebacks.
- `--debug-artifacts` implies both and permits HTML and PNG browser captures.

Logs deliberately exclude transcripts, cleaned content, full prompts, complete model
requests/responses, passwords, API keys, tokens, cookies, browser storage, and
credential-manager output. HTML and screenshots can nevertheless contain transcripts,
account details, email addresses, and other private page content. They are not scrubbed
and must be inspected before sharing.

Examples from one correlated pipeline run:

```text
20260728-143012-a7f3-trwinp.log
20260728-143012-a7f3-trwinp-otter-list.html
20260728-143012-a7f3-trwinp-otter-list.png
20260728-143012-a7f3-trwclean.log
20260728-143012-a7f3-trwout.log
```

Retention counts complete run-ID groups, not individual files. The default retains all
supported files for the five newest logged runs. `retained_runs: 0` makes completed
older runs eligible for removal while protecting the current invocation. Values such
as 100 or 1,000 are valid, but large histories—especially HTML and PNG captures—can
consume substantial disk space. Cleanup is independent of pipeline success, output
persistence, source deletion, and whether the current command is logging.

## Development

```bash
python -m venv .venv
# Activate it, then:
python -m pip install -e '.[dev,otter]'
pytest -m 'not live_otter and not live_gemini'
ruff check .
ruff format --check .
mypy src
python -m build
```

Tests inject temporary configuration and logging paths and never touch the developer's
real user directories. Default tests require no network, Chrome, Otter, Gemini, `pass`,
credentials, production vault, or real recording. The opt-in live Otter test is:

```bash
TRANSCRIPT_WEAVER_LIVE_OTTER=1 pytest -m live_otter tests/test_live_otter.py
```

See `docs/contracts.md` for future-stage contracts. Contributions are licensed under
GPL-3.0-or-later.

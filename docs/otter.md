# Live Otter setup

The live adapter is designed for WSL with Windows Chrome. By default it starts Chrome
on port 9222 and reaches the Windows gateway port proxy on 9223, matching the supplied
prototype. Configure the Windows port proxy separately and use a dedicated browser
profile. Authentication is manual. An available CDP session is reused instead of
opening another Chrome window.

Optional environment variables:

- `TRANSCRIPT_WEAVER_CHROME_EXE`: WSL path to Windows Chrome.
- `TRANSCRIPT_WEAVER_OTTER_PROFILE`: Windows path to the dedicated profile.
- `TRANSCRIPT_WEAVER_OTTER_CDP_URL`: complete CDP base URL.
- `TRANSCRIPT_WEAVER_OTTER_START_CHROME=0`: connect without launching Chrome.
- `TRANSCRIPT_WEAVER_OTTER_LOGIN_TIMEOUT`: login wait in seconds (default 1800).

The adapter never reads an Otter password, calls Gemini, writes a vault, or deletes a
recording.

## Diagnostics

Ordinary successful acquisition is silent except for its JSON packet on stdout.
Warnings and errors use stderr.

```bash
trwinp otter --log > packet.json
trwinp otter --verbose > packet.json
trwinp otter --debug-artifacts > packet.json
```

`--log` and `--verbose` never deliberately store transcript text. `--debug-artifacts`
creates run-correlated HTML and full-page PNG files for the Otter list and recording
page. Those files may contain transcripts, account details, email addresses, or other
private information. They are not scrubbed or safe to share without inspection. The
option never deliberately exports cookies, browser storage, passwords, API keys,
authentication tokens, or credential-store output.

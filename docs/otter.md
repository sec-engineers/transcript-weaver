# Live Otter setup

## Platform support and prerequisites

The live Otter adapter currently supports **WSL on Windows with Windows Chrome**. This
platform limitation applies only to `trwinp otter`; `stdin`, `file`, `trweave`, and
`trwout` do not require this browser setup.

Install Transcript Weaver normally:

```bash
python3 -m pip install transcript-weaver
```

That installation includes the Playwright Python dependency used to control Chrome.
Transcript Weaver connects to the user's existing Windows Chrome through Chrome
DevTools Protocol (CDP); it does not need Playwright to download or maintain a separate
bundled Chromium browser.

Before using Otter, provide:

- WSL running on Windows.
- Windows Chrome installed and reachable from WSL.
- A dedicated Chrome profile for Otter automation rather than a daily-use profile.
- A Windows port proxy that exposes Chrome's localhost debugging port `9222` to WSL on
  gateway port `9223`, unless a custom reachable CDP endpoint is configured.
- Manual Otter authentication in the dedicated Chrome profile.

## Expected setup path

1. Install Transcript Weaver with the normal installation command above.
2. Configure the Windows port proxy for the WSL-to-Windows CDP connection.
3. Let Transcript Weaver start Windows Chrome with its dedicated automation profile, or
   start Chrome yourself and disable automatic launch.
4. Sign in to Otter manually when Chrome opens.
5. Verify acquisition with `trwinp otter > packet.json`.

By default, the adapter starts Windows Chrome on debugging port `9222` and reaches the
Windows gateway port proxy on `9223`, matching the working prototype. An available CDP
session is reused instead of opening another Chrome window.

Optional environment variables:

- `TRANSCRIPT_WEAVER_CHROME_EXE`: WSL path to Windows Chrome.
- `TRANSCRIPT_WEAVER_OTTER_PROFILE`: Windows path to the dedicated profile.
- `TRANSCRIPT_WEAVER_OTTER_CDP_URL`: complete CDP base URL.
- `TRANSCRIPT_WEAVER_OTTER_START_CHROME=0`: connect without launching Chrome.
- `TRANSCRIPT_WEAVER_OTTER_LOGIN_TIMEOUT`: login wait in seconds (default 1800).

If a damaged or incomplete installation cannot import Playwright, reinstall or upgrade
Transcript Weaver rather than looking for an optional Otter extra.

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

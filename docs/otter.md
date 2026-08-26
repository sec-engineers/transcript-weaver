# Live Otter setup

## Why Transcript Weaver uses browser automation

Transcript Weaver intentionally controls the authenticated Otter web interface
instead of using Otter's official public API. As of August 11, 2026, Otter
states that its public API is available only to Enterprise workspaces. Otter's
Business, Pro, and Basic plans do not include public API access; Enterprise
pricing requires contacting Otter sales. Enterprise customers who do not see
API access must contact their Otter account manager to have it enabled.

That restriction makes the official API unsuitable for a tool intended to work
with an ordinary individual Otter account. The `trwinp otter` adapter therefore
uses a dedicated, locally authenticated Chrome profile and Otter's visible web
controls to copy a transcript. It does not ask for, store, or transmit the
user's Otter password.

This choice has a trade-off: browser interfaces can change without notice, so
selectors may occasionally need maintenance. If Otter makes its supported API
available to non-Enterprise customers in the future, a documented API adapter
would be preferable to browser automation.

Official references, reviewed August 11, 2026:

- [Does Otter offer an open API?](https://help.otter.ai/hc/en-us/articles/4412365535895-Does-Otter-offer-an-open-API)
- [Otter.ai Public API](https://help.otter.ai/hc/en-us/articles/36130822688279-Otter-ai-Public-API)
- [Otter pricing](https://otter.ai/pricing)

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
- Manual Otter authentication in the dedicated Chrome profile.

## Expected setup path

1. Install Transcript Weaver with the normal installation command above.
2. Run `trwprep otter`.
3. Approve Windows elevation only if you want TRW to create missing local
   port-forwarding and firewall rules.
4. Sign in to Otter manually when Chrome opens.
5. Verify acquisition with `trwinp otter > packet.json`.

Preparation creates or reuses `%LOCALAPPDATA%\TRW-Chrome-Otter`, starts Windows
Chrome on debugging port `9222`, and reaches it through WSL-facing port `9223`.
The legacy `%LOCALAPPDATA%\Chrome-Otter-Automation` profile is detected and may
be retained so an existing authenticated session is not discarded. Running
`trwprep otter` repeatedly reuses the browser and leaves an Otter page visible.
An available CDP session is reused instead of opening another Chrome window.

## Why Windows elevation is requested

Windows Chrome listens only on its own loopback address, while TRW runs inside
WSL on a separate virtual network. If forwarding is missing, `trwprep otter`
shows the exact commands it proposes to elevate. They have this form, with the
current Windows-side and WSL IP addresses substituted before approval:

```powershell
netsh interface portproxy delete v4tov4 listenport=9223
netsh interface portproxy add v4tov4 listenport=9223 listenaddress=<WINDOWS_WSL_HOST_IP> connectport=9222 connectaddress=127.0.0.1
netsh advfirewall firewall delete rule name="TRW Chrome DevTools 9223"
netsh advfirewall firewall add rule name="TRW Chrome DevTools 9223" dir=in action=allow protocol=TCP localip=<WINDOWS_WSL_HOST_IP> remoteip=<WSL_IP> localport=9223
```

The first pair replaces the WSL-facing port proxy that carries connections from
port `9223` to Chrome's Windows-local DevTools port `9222`. The second pair
replaces its inbound firewall rule. That rule is limited to TCP port `9223`, the
current Windows WSL interface, and the current WSL address; it does not open the
port generally to the local network. The delete commands make repeated setup
safe and prevent stale definitions from accumulating.

WSL addresses can change after Windows or WSL restarts. Running `trwprep otter`
again displays the newly proposed addresses and can replace obsolete rules.

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

## Live functional test

After the offline suite passes, verify the configured browser connection with:

```bash
TRANSCRIPT_WEAVER_LIVE_OTTER=1 pytest --no-cov -m live_otter tests/test_live_otter.py
```

This opens the newest visible recording and copies its transcript into a temporary test
packet. It does not call Gemini, write a vault, or delete the recording.

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

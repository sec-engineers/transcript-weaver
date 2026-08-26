# Live DOM capture setup

`trwinp dom` captures the current main-document DOM from a dedicated Windows
Chrome profile without navigating, reloading, clicking, scrolling, or closing
the page. It records the current page title and URL as source information and
uses the acquisition time as the packet datetime.

The live DOM adapter currently supports **WSL on Windows with Windows Chrome**.
Prepare it with:

```bash
trwprep dom
```

The preparation command creates or reuses this Windows user-data directory:

```text
%LOCALAPPDATA%\TRW-Chrome-DOM
```

It starts Chrome with local DevTools port `9224` and uses WSL-facing port
`9225`. If the required Windows port proxy and firewall rule are missing,
`trwprep` displays the exact commands it proposes to run and asks before
requesting Windows elevation. Declining leaves the privileged setup unchanged.

## Why Windows elevation is requested

Windows Chrome listens only on its own loopback address, while TRW runs inside
WSL on a separate virtual network. The preparation step uses commands of this
form, with the current Windows-side and WSL IP addresses substituted and shown
before approval:

```powershell
netsh interface portproxy delete v4tov4 listenport=9225
netsh interface portproxy add v4tov4 listenport=9225 listenaddress=<WINDOWS_WSL_HOST_IP> connectport=9224 connectaddress=127.0.0.1
netsh advfirewall firewall delete rule name="TRW Chrome DevTools 9225"
netsh advfirewall firewall add rule name="TRW Chrome DevTools 9225" dir=in action=allow protocol=TCP localip=<WINDOWS_WSL_HOST_IP> remoteip=<WSL_IP> localport=9225
```

The first pair replaces the WSL-facing port proxy that carries connections from
port `9225` to Chrome's Windows-local DevTools port `9224`. The second pair
replaces its inbound firewall rule. That rule is limited to TCP port `9225`, the
current Windows WSL interface, and the current WSL address; it does not open the
port generally to the local network. The delete commands make repeated setup
safe and prevent stale definitions from accumulating.

WSL addresses can change after Windows or WSL restarts. Running `trwprep dom`
again displays the newly proposed addresses and can replace obsolete rules.

When it starts Chrome, `trwprep dom` opens one local, network-free welcome page
with preparation instructions and then exits, leaving Chrome running. Use that
same tab to navigate, authenticate, expand content, and otherwise prepare the
page. Leave exactly one tab open, then acquire it:

```bash
trwinp dom > packet.json
```

Acquisition requires exactly one browser context and one normal page. It fails
rather than guessing when either count differs. TRW does not intentionally
trigger page activity, although scripts already running in the page may continue
their own timers, connections, and requests.

The emitted HTML may contain private page content, account details, identifiers,
or other sensitive material. Inspect it before sharing. TRW does not export
cookies, browser storage, passwords, or credential-store contents.

Advanced installations may override the endpoint with
`TRANSCRIPT_WEAVER_DOM_CDP_URL` and the Chrome executable with
`TRANSCRIPT_WEAVER_CHROME_EXE`; normal setup does not require either variable.

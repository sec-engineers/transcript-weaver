"""Shared Windows Chrome and WSL CDP setup boundaries."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from transcript_weaver.inp.errors import SourceUnavailableError


@dataclass(frozen=True, slots=True)
class BrowserSpec:
    name: str
    profile_name: str
    debug_port: int
    proxy_port: int
    start_url: str
    legacy_profile_name: str | None = None
    legacy_firewall_names: tuple[str, ...] = ()

    @property
    def firewall_name(self) -> str:
        return f"TRW Chrome DevTools {self.proxy_port}"


DOM_WELCOME_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>TRW DOM Browser</title>
<style>
body { background:#111827; color:#f9fafb; font:24px system-ui,sans-serif;
       margin:0; min-height:100vh; display:grid; place-items:center; }
main { max-width:850px; padding:64px; }
h1 { color:#fbbf24; font-size:56px; margin:0 0 24px; }
li { margin:16px 0; }
code { color:#fbbf24; }
</style></head><body><main><h1>Transcript Weaver DOM Browser</h1>
<p>This is a dedicated Chrome window for TRW DOM capture.</p>
<ol><li>Use this tab to navigate to the page you want.</li>
<li>Sign in and prepare the page manually.</li>
<li>Leave exactly one tab open.</li>
<li>Run <code>trwinp dom</code>.</li></ol></main></body></html>"""

OTTER_SPEC = BrowserSpec(
    name="Otter",
    profile_name="TRW-Chrome-Otter",
    legacy_profile_name="Chrome-Otter-Automation",
    debug_port=9222,
    proxy_port=9223,
    start_url="https://otter.ai/home",
    legacy_firewall_names=("WSL Chrome DevTools 9223",),
)
DOM_SPEC = BrowserSpec(
    name="DOM",
    profile_name="TRW-Chrome-DOM",
    debug_port=9224,
    proxy_port=9225,
    start_url="data:text/html;charset=utf-8," + urllib.parse.quote(DOM_WELCOME_HTML),
)


def windows_local_appdata() -> str:  # pragma: no cover - WSL/Windows boundary
    try:
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "echo", "%LOCALAPPDATA%"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceUnavailableError(
            "Could not determine Windows LOCALAPPDATA for the Chrome profile."
        ) from exc
    value = result.stdout.strip()
    if not value or "%" in value:
        raise SourceUnavailableError("Windows LOCALAPPDATA was unavailable.")
    return value


def windows_host_ip() -> str:  # pragma: no cover - WSL/Windows boundary
    try:
        result = subprocess.run(["ip", "route"], check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceUnavailableError("Could not inspect the WSL network route.") from exc
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "default" and len(parts) >= 3:
            return parts[2]
    raise SourceUnavailableError("Could not find the Windows host IP in the WSL route.")


def wsl_ip() -> str:  # pragma: no cover - WSL/Windows boundary
    try:
        result = subprocess.run(["hostname", "-I"], check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceUnavailableError("Could not inspect the WSL IP address.") from exc
    addresses = [value for value in result.stdout.split() if value and ":" not in value]
    if not addresses:
        raise SourceUnavailableError("Could not find the WSL IPv4 address.")
    return addresses[0]


def chrome_executable() -> str:
    return os.environ.get(
        "TRANSCRIPT_WEAVER_CHROME_EXE",
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    )


def profile_path(spec: BrowserSpec, *, legacy: bool = False) -> str:
    name = spec.legacy_profile_name if legacy else spec.profile_name
    if name is None:
        raise SourceUnavailableError(f"{spec.name} has no legacy Chrome profile.")
    return windows_local_appdata().rstrip("\\/") + "\\" + name


def windows_path_exists(path: str) -> bool:  # pragma: no cover - WSL/Windows boundary
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", f'if exist "{path}\\NUL" (exit /b 0) else (exit /b 1)'],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def selected_profile_path(spec: BrowserSpec) -> str:
    override = os.environ.get(f"TRANSCRIPT_WEAVER_{spec.name.upper()}_PROFILE")
    if override:
        return override
    preferred = profile_path(spec)
    if windows_path_exists(preferred):
        return preferred
    if spec.legacy_profile_name is not None:
        legacy = profile_path(spec, legacy=True)
        if windows_path_exists(legacy):
            return legacy
    return preferred


def cdp_url(spec: BrowserSpec) -> str:
    override = os.environ.get(f"TRANSCRIPT_WEAVER_{spec.name.upper()}_CDP_URL")
    return override or f"http://{windows_host_ip()}:{spec.proxy_port}"


def cdp_ready(url: str) -> bool:  # pragma: no cover - live browser boundary
    try:
        with urllib.request.urlopen(f"{url}/json/version", timeout=1) as response:
            return int(response.status) == 200
    except Exception:
        return False


def wait_for_cdp(
    url: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: int = 30,
) -> None:  # pragma: no cover - live browser boundary
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if cdp_ready(url):
            return
        sleep(0.5)
    raise SourceUnavailableError("Chrome's DevTools endpoint did not become ready.")


def start_chrome(spec: BrowserSpec, *, profile: str, start_url: str | None = None) -> None:
    try:
        subprocess.Popen(
            [
                chrome_executable(),
                f"--remote-debugging-port={spec.debug_port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                "--new-window",
                start_url or spec.start_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise SourceUnavailableError(
            f"Could not start Windows Chrome for {spec.name} preparation."
        ) from exc


def _run_text(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, capture_output=True)


def port_proxy_ready(spec: BrowserSpec) -> bool:  # pragma: no cover - Windows boundary
    result = _run_text(["cmd.exe", "/d", "/c", "netsh", "interface", "portproxy", "dump"])
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        if not line.startswith("add v4tov4 "):
            continue
        values = dict(token.split("=", 1) for token in line.split()[2:] if "=" in token)
        if (
            values.get("listenport") == str(spec.proxy_port)
            and values.get("connectaddress") == "127.0.0.1"
            and values.get("connectport") == str(spec.debug_port)
        ):
            return True
    return False


def firewall_ready(spec: BrowserSpec) -> bool:  # pragma: no cover - Windows boundary
    for name in (spec.firewall_name, *spec.legacy_firewall_names):
        result = _run_text(
            [
                "cmd.exe",
                "/d",
                "/c",
                "netsh",
                "advfirewall",
                "firewall",
                "show",
                "rule",
                f"name={name}",
            ]
        )
        if result.returncode != 0 or "No rules match" in result.stdout:
            continue
        text = result.stdout
        common = all(
            re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            for pattern in (
                r"^Enabled:\s+Yes\s*$",
                r"^Direction:\s+In\s*$",
                r"^Protocol:\s+TCP\s*$",
                rf"^LocalPort:\s+{spec.proxy_port}\s*$",
                r"^Action:\s+Allow\s*$",
            )
        )
        if not common:
            continue
        if name in spec.legacy_firewall_names:
            return True
        host, guest = windows_host_ip(), wsl_ip()
        local_ip_matches = re.search(
            rf"^LocalIP:\s+{re.escape(host)}(?:/32)?\s*$", text, re.MULTILINE
        )
        remote_ip_matches = re.search(
            rf"^RemoteIP:\s+{re.escape(guest)}(?:/32)?\s*$", text, re.MULTILINE
        )
        if local_ip_matches and remote_ip_matches:
            return True
    return False


def forwarding_ready(spec: BrowserSpec) -> bool:
    return port_proxy_ready(spec) and firewall_ready(spec)


def forwarding_commands(spec: BrowserSpec) -> tuple[str, ...]:
    host = windows_host_ip()
    guest = wsl_ip()
    return (
        f"netsh interface portproxy delete v4tov4 listenport={spec.proxy_port}",
        (
            "netsh interface portproxy add v4tov4 "
            f"listenport={spec.proxy_port} listenaddress={host} "
            f"connectport={spec.debug_port} connectaddress=127.0.0.1"
        ),
        f'netsh advfirewall firewall delete rule name="{spec.firewall_name}"',
        (
            f'netsh advfirewall firewall add rule name="{spec.firewall_name}" '
            f"dir=in action=allow protocol=TCP localip={host} remoteip={guest} "
            f"localport={spec.proxy_port}"
        ),
    )


def configure_forwarding(spec: BrowserSpec) -> None:  # pragma: no cover - UAC boundary
    elevated_script = "; ".join(
        (*forwarding_commands(spec), "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }")
    )
    encoded = base64.b64encode(elevated_script.encode("utf-16le")).decode("ascii")
    launcher = (
        "$p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru "
        f"-ArgumentList @('-NoProfile','-EncodedCommand','{encoded}'); exit $p.ExitCode"
    )
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", launcher], check=False)
    except OSError as exc:
        raise SourceUnavailableError("Could not request Windows elevation.") from exc
    if result.returncode != 0:
        raise SourceUnavailableError(
            "Windows declined or failed the DevTools port-forwarding configuration."
        )
    if not forwarding_ready(spec):
        raise SourceUnavailableError(
            "Windows reported success, but the DevTools forwarding setup could not be verified."
        )

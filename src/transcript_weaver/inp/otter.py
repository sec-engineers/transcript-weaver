"""Otter acquisition behind a mockable browser boundary.

The live client intentionally follows the supplied prototype: start real Windows
Chrome with a dedicated profile, connect from WSL over CDP, wait for manual
authentication, open the first visible recording, and use Otter's Copy
Transcript command plus the browser clipboard.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Protocol

from transcript_weaver.inp.errors import (
    AuthenticationRequiredError,
    SourceUnavailableError,
    TranscriptNotFoundError,
)
from transcript_weaver.models import AcquiredTranscript, Source
from transcript_weaver.runtime import DiagnosticError, StageLog, write_debug_artifact

OTTER_URL = "https://otter.ai/home"
TITLE_LINK_SELECTOR = 'a[data-testid="conversation-title-link"][href*="/u/"]'


@dataclass(frozen=True, slots=True)
class OtterCapture:
    transcript: str
    displayed_datetime: str
    title: str | None
    url: str
    duration_seconds: float | None = None


class OtterClient(Protocol):
    def capture_newest(self) -> OtterCapture: ...


class OtterSource:
    def __init__(
        self,
        client: OtterClient | None = None,
        *,
        local_timezone: tzinfo | None = None,
        stage_log: StageLog | None = None,
        debug_artifacts: bool = False,
        log_directory: Path | None = None,
        run_id: str | None = None,
        warning: Callable[[str], None] | None = None,
    ) -> None:
        self._client = client
        self._local_timezone = local_timezone
        self._stage_log = stage_log
        self._debug_artifacts = debug_artifacts
        self._log_directory = log_directory
        self._run_id = run_id
        self._warning = warning

    def acquire(self) -> AcquiredTranscript:
        client = self._client
        if client is None:
            if (
                self._stage_log is None
                or self._log_directory is None
                or self._run_id is None
                or self._warning is None
            ):
                raise SourceUnavailableError("Otter diagnostic context was not configured.")
            client = PlaywrightOtterClient(
                stage_log=self._stage_log,
                debug_artifacts=self._debug_artifacts,
                log_directory=self._log_directory,
                run_id=self._run_id,
                warning=self._warning,
            )
        capture = client.capture_newest()
        if not capture.transcript.strip():
            raise TranscriptNotFoundError("Otter returned an empty transcript.")
        recorded_at = parse_otter_datetime(
            capture.displayed_datetime,
            local_timezone=self._local_timezone,
        )
        return AcquiredTranscript(
            transcript=capture.transcript,
            recorded_at=recorded_at,
            source=Source(type="otter", name=capture.title, reference=capture.url),
            duration_seconds=capture.duration_seconds,
        )


def parse_otter_datetime(
    text: str,
    *,
    now: datetime | None = None,
    local_timezone: tzinfo | None = None,
) -> datetime:
    """Parse prototype-proven Otter formats and convert local system time to UTC."""
    local_now = now or datetime.now().astimezone()
    zone = local_timezone or local_now.tzinfo
    if zone is None:
        raise SourceUnavailableError("Could not determine the local system timezone.")
    normalized = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    relative_match = re.search(
        r"\b(Today|Yesterday)\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if relative_match:
        effective_now = (
            local_now.astimezone(zone)
            if local_now.tzinfo is not None
            else local_now.replace(tzinfo=zone)
        )
        date_value = effective_now.date()
        if relative_match.group(1).casefold() == "yesterday":
            date_value -= timedelta(days=1)
        relative_time = datetime.strptime(
            relative_match.group(2).upper().replace(" ", ""), "%I:%M%p"
        ).time()
        return datetime.combine(date_value, relative_time, tzinfo=zone).astimezone(timezone.utc)
    patterns: tuple[tuple[str, tuple[str, ...], bool], ...] = (
        (
            r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\s*(?:,|at)?\s*"
            r"(\d{1,2}:\d{2}\s*[AP]M)",
            ("%b %d, %Y", "%B %d, %Y"),
            False,
        ),
        (
            r"([A-Z][a-z]{2,8}\s+\d{1,2})\s*(?:,|at)\s*"
            r"(\d{1,2}:\d{2}\s*[AP]M)",
            ("%b %d %Y", "%B %d %Y"),
            True,
        ),
        (
            r"(\d{1,2}/\d{1,2}/\d{4})\s*,?\s*(\d{1,2}:\d{2}\s*[AP]M)",
            ("%m/%d/%Y",),
            False,
        ),
        (r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", ("%Y-%m-%d",), False),
    )

    for pattern, date_formats, needs_year in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        date_text = match.group(1)
        if needs_year:
            date_text = f"{date_text} {local_now.year}"
        time_text = match.group(2).upper().replace(" ", "")
        for date_format in date_formats:
            for time_format in ("%I:%M%p", "%H:%M"):
                try:
                    date_value = datetime.strptime(date_text, date_format)
                    time_value = datetime.strptime(time_text, time_format)
                except ValueError:
                    continue
                local_value = datetime(
                    date_value.year,
                    date_value.month,
                    date_value.day,
                    time_value.hour,
                    time_value.minute,
                    tzinfo=zone,
                )
                return local_value.astimezone(timezone.utc)
    raise TranscriptNotFoundError("Could not identify the Otter recording date and time.")


def _exception_summary(exc: Exception) -> str:
    message = str(exc).splitlines()[0].strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


class PlaywrightOtterClient:  # pragma: no cover - exercised only by opt-in live test
    """Live Otter browser client with shared, run-correlated diagnostics."""

    def __init__(
        self,
        *,
        stage_log: StageLog,
        debug_artifacts: bool,
        log_directory: Path,
        run_id: str,
        warning: Callable[[str], None],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._log = stage_log
        self._debug_artifacts = debug_artifacts
        self._log_directory = log_directory
        self._run_id = run_id
        self._warning = warning
        self._sleep = sleep
        self._cdp_url = os.environ.get("TRANSCRIPT_WEAVER_OTTER_CDP_URL")
        self._started_chrome = False

    def capture_newest(self) -> OtterCapture:
        sync_api = _load_playwright()
        cdp_url = self._cdp_url or f"http://{_windows_host_ip()}:9223"
        if _env_flag("TRANSCRIPT_WEAVER_OTTER_START_CHROME", default=True):
            if _cdp_ready(cdp_url):
                self._log.info("Reusing existing Chrome DevTools session")
            else:
                self._start_chrome()
        _wait_for_cdp(cdp_url, sleep=self._sleep)

        try:
            with (
                sync_api.sync_playwright() as playwright,
                self._managed_browser(playwright.chromium.connect_over_cdp(cdp_url)) as browser,
            ):
                if not browser.contexts:
                    raise SourceUnavailableError(
                        "Connected to Chrome but found no browser context."
                    )
                context = browser.contexts[0]
                try:
                    context.grant_permissions(
                        ["clipboard-read", "clipboard-write"], origin="https://otter.ai"
                    )
                except Exception:
                    self._warning("could not grant Otter clipboard permission")
                otter_pages = [
                    candidate for candidate in context.pages if "otter.ai" in candidate.url
                ]
                page = (
                    otter_pages[0]
                    if otter_pages
                    else (context.pages[0] if context.pages else context.new_page())
                )
                try:
                    self._wait_for_ready(page)
                    self._capture_debug(page, "otter-list")
                    title, url = self._open_newest(page)
                    self._capture_debug(page, "transcript-page")
                    self._log.debug("Extracting Otter recording datetime")
                    displayed_datetime = self._visible_recording_datetime(page)
                    duration_seconds = self._media_duration_seconds(page)
                    transcript = self._copy_transcript(page)
                    return OtterCapture(
                        transcript, displayed_datetime, title, url, duration_seconds
                    )
                except (
                    AuthenticationRequiredError,
                    SourceUnavailableError,
                    TranscriptNotFoundError,
                ):
                    self._capture_debug(page, "failure-page")
                    raise
                except Exception as exc:
                    self._capture_debug(page, "failure-page")
                    raise SourceUnavailableError(
                        f"Otter browser acquisition failed: {_exception_summary(exc)}"
                    ) from exc
        except (AuthenticationRequiredError, SourceUnavailableError, TranscriptNotFoundError):
            raise
        except Exception as exc:
            raise SourceUnavailableError(
                f"Otter browser acquisition failed: {_exception_summary(exc)}"
            ) from exc

    def _capture_debug(self, page: Any, suffix: str) -> None:
        state = self._page_state(page)
        self._log.debug(
            "Browser state "
            f"precise_links={state['precise_recording_link_count']} "
            f"broad_links={state['broad_recording_link_count']} "
            f"sign_in_controls={state['sign_in_control_count']} "
            f"signed_out={state['clearly_signed_out']}"
        )
        if not self._debug_artifacts:
            return
        try:
            write_debug_artifact(
                self._log_directory,
                self._run_id,
                "trwinp",
                suffix=suffix,
                extension=".html",
                content=page.content(),
            )
            screenshot = page.screenshot(full_page=True)
            if not isinstance(screenshot, bytes):
                raise DiagnosticError("Browser screenshot did not return bytes.")
            write_debug_artifact(
                self._log_directory,
                self._run_id,
                "trwinp",
                suffix=suffix,
                extension=".png",
                content=screenshot,
            )
            self._log.info(f"Captured sensitive browser artifacts: {suffix}")
        except (OSError, DiagnosticError) as exc:
            self._warning(f"could not write debug artifact for {suffix}: {exc}")

    def _start_chrome(self) -> None:
        chrome_exe = os.environ.get(
            "TRANSCRIPT_WEAVER_CHROME_EXE",
            "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        )
        profile = os.environ.get("TRANSCRIPT_WEAVER_OTTER_PROFILE")
        if not profile:
            profile = _windows_local_appdata() + r"\Chrome-Otter-Automation"
        try:
            subprocess.Popen(
                [
                    chrome_exe,
                    "--remote-debugging-port=9222",
                    "--remote-debugging-address=0.0.0.0",
                    f"--user-data-dir={profile}",
                    "--new-window",
                    OTTER_URL,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise SourceUnavailableError(
                "Could not start Windows Chrome for Otter automation."
            ) from exc
        self._started_chrome = True
        self._log.info("Started dedicated Otter Chrome profile")

    @contextmanager
    def _managed_browser(self, browser: Any) -> Iterator[Any]:
        try:
            yield browser
        finally:
            if self._started_chrome:
                try:
                    context = browser.contexts[0]
                    page = context.pages[0]
                    context.new_cdp_session(page).send("Browser.close")
                    self._log.info("Closed dedicated Otter Chrome profile")
                except Exception as exc:
                    self._warning(
                        f"could not close dedicated Otter Chrome: {_exception_summary(exc)}"
                    )
            with suppress(Exception):
                browser.close()

    def _wait_for_ready(self, page: Any) -> None:
        page.goto(OTTER_URL, wait_until="domcontentloaded")
        deadline = time.monotonic() + int(
            os.environ.get("TRANSCRIPT_WEAVER_OTTER_LOGIN_TIMEOUT", "1800")
        )
        self._log.info("Waiting for Otter recordings page")
        last_state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last_state = self._page_state(page)
            if last_state["recording_link_count"] > 0:
                return
            self._sleep(2)
        if last_state.get("clearly_signed_out"):
            raise AuthenticationRequiredError("Timed out waiting for Otter login.")
        raise SourceUnavailableError(
            "Otter loaded, but no recording-list selector matched; use --debug-artifacts "
            "to inspect a possible page change."
        )

    def _page_state(self, page: Any) -> dict[str, Any]:
        body = page.locator("body").inner_text(timeout=5000).lower()
        precise_count = page.locator(TITLE_LINK_SELECTOR).count()
        broad_count = page.locator('a[href*="/u/"]').count()
        sign_in_controls = page.get_by_role(
            "button", name=re.compile(r"sign in|log in|continue with google", re.IGNORECASE)
        ).count()
        url = str(page.url)
        clearly_signed_out = (
            any(part in url.lower() for part in ("/login", "/signin", "/auth"))
            or sign_in_controls > 0
        )
        return {
            "precise_recording_link_count": precise_count,
            "broad_recording_link_count": broad_count,
            "recording_link_count": max(precise_count, broad_count),
            "sign_in_control_count": sign_in_controls,
            "body_mentions_recordings": "recordings" in body,
            "body_mentions_new_recording": "new recording" in body,
            "clearly_signed_out": clearly_signed_out,
        }

    def _open_newest(self, page: Any) -> tuple[str | None, str]:
        selectors = (
            TITLE_LINK_SELECTOR,
            '[data-testid="conversation-card"] a[href*="/u/"]',
            'a[href*="otter.ai/u/"]',
            'a[href^="/u/"]',
            'a[href*="/u/"]',
        )
        for selector in selectors:
            links = page.locator(selector)
            for index in range(links.count()):
                link = links.nth(index)
                if not link.is_visible(timeout=1000):
                    continue
                href = link.get_attribute("href")
                if not href:
                    continue
                title = link.inner_text(timeout=1000).strip() or None
                page.goto(urllib.parse.urljoin(str(page.url), href), wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    self._log.debug("Recording page did not reach network idle")
                return title, str(page.url)
        raise TranscriptNotFoundError("The Otter recording list contained no usable link.")

    def _visible_recording_datetime(self, page: Any) -> str:
        body = page.locator("body").inner_text(timeout=5000)
        if not isinstance(body, str):
            raise SourceUnavailableError("Otter page text was unavailable.")
        parse_otter_datetime(body)
        return body

    def _media_duration_seconds(self, page: Any) -> float | None:
        value = page.evaluate(
            """() => {
                const durations = Array.from(document.querySelectorAll('audio, video'))
                    .map(element => Number(element.duration))
                    .filter(duration => Number.isFinite(duration) && duration >= 0);
                return durations.length ? Math.max(...durations) : null;
            }"""
        )
        if value is None:
            self._log.debug("Otter exposed no reliable media duration")
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            self._log.debug("Otter exposed an invalid media duration")
            return None
        self._log.debug("Extracted Otter media duration")
        return float(value)

    def _copy_transcript(self, page: Any) -> str:
        tab = page.locator('[data-testid="tab-Transcript"]').first
        if tab.count() and tab.is_visible(timeout=3000):
            tab.click()
        menu_candidates = (
            page.locator('[data-testid="transcript-more-options-button"]').first,
            page.locator('[data-testid="more-options-button"]').first,
            page.locator('[data-testid="block-menu-more-options"]').first,
            page.get_by_role(
                "button", name=re.compile(r"more options|more|menu", re.IGNORECASE)
            ).first,
        )
        menu = next(
            (
                candidate
                for candidate in menu_candidates
                if candidate.count() and candidate.is_visible(timeout=3000)
            ),
            None,
        )
        if menu is None:
            raise SourceUnavailableError("Could not open Otter's More Options menu.")
        menu.click()
        command = page.get_by_text(re.compile(r"copy transcript", re.IGNORECASE)).first
        if not command.count() or not command.is_visible(timeout=3000):
            raise SourceUnavailableError("Could not find Otter's Copy Transcript command.")
        command.click()
        self._sleep(1)
        try:
            text = page.evaluate("navigator.clipboard.readText()")
        except Exception as exc:
            raise SourceUnavailableError(
                "Could not read the transcript clipboard; allow clipboard access for otter.ai."
            ) from exc
        if not isinstance(text, str) or not text.strip():
            raise TranscriptNotFoundError("Otter copied an empty transcript.")
        return text.strip()


def _load_playwright() -> Any:  # pragma: no cover - live dependency boundary
    try:
        return importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise SourceUnavailableError(
            "Playwright is unavailable. Reinstall or upgrade transcript-weaver to repair "
            "the installation."
        ) from exc


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no"}


def _windows_local_appdata() -> str:  # pragma: no cover - WSL/Windows boundary
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


def _windows_host_ip() -> str:  # pragma: no cover - WSL/Windows boundary
    try:
        result = subprocess.run(
            ["ip", "route"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SourceUnavailableError("Could not inspect the WSL network route.") from exc
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "default" and len(parts) >= 3:
            return parts[2]
    raise SourceUnavailableError("Could not find the Windows host IP in the WSL route.")


def _cdp_ready(cdp_url: str) -> bool:  # pragma: no cover - live browser boundary
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1) as response:
            return int(response.status) == 200
    except Exception:
        return False


def _wait_for_cdp(
    cdp_url: str,
    *,
    sleep: Callable[[float], None],
    timeout_seconds: int = 300,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            sleep(0.5)
    raise SourceUnavailableError("Chrome's DevTools endpoint did not become ready.")

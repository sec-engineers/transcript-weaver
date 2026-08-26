"""Prepare dedicated, long-lived Chrome instances for TRW inputs."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import Any, TextIO

from transcript_weaver.browser import (
    DOM_SPEC,
    OTTER_SPEC,
    BrowserSpec,
    cdp_ready,
    cdp_url,
    configure_forwarding,
    forwarding_commands,
    forwarding_ready,
    profile_path,
    selected_profile_path,
    start_chrome,
    wait_for_cdp,
    windows_path_exists,
)
from transcript_weaver.inp.errors import SourceUnavailableError


def confirm(prompt: str, *, stdin: TextIO, stdout: TextIO, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    stdout.write(prompt + suffix)
    stdout.flush()
    answer = stdin.readline()
    if not answer:
        stdout.write("\n")
        return default
    normalized = answer.strip().casefold()
    if not normalized:
        return default
    return normalized in {"y", "yes"}


def _choose_otter_profile(*, stdin: TextIO, stdout: TextIO) -> str:
    override = os.environ.get("TRANSCRIPT_WEAVER_OTTER_PROFILE")
    if override:
        return override
    preferred = profile_path(OTTER_SPEC)
    if windows_path_exists(preferred):
        return preferred
    legacy = profile_path(OTTER_SPEC, legacy=True)
    if not windows_path_exists(legacy):
        return preferred
    stdout.write(
        "TRW found the existing Otter Chrome profile at:\n"
        f"  {legacy}\n"
        "It may contain your authenticated Otter session.\n"
    )
    if confirm("Continue using this existing profile?", stdin=stdin, stdout=stdout, default=True):
        return legacy
    stdout.write(f"TRW will use the new profile at:\n  {preferred}\n")
    return preferred


def _ensure_forwarding(spec: BrowserSpec, *, stdin: TextIO, stdout: TextIO) -> None:
    if forwarding_ready(spec):
        return
    stdout.write(
        f"TRW needs a Windows port-forwarding rule so WSL can reach the dedicated "
        f"{spec.name} Chrome DevTools endpoint ({spec.proxy_port} -> {spec.debug_port}).\n"
    )
    commands = forwarding_commands(spec)
    stdout.write("The following commands will run in an Administrator PowerShell window:\n")
    for command in commands:
        stdout.write(f"  {command}\n")
    guide = f"docs/{spec.name.casefold()}.md"
    stdout.write(f"A full explanation is available in the TRW guide: {guide}\n")
    if not confirm(
        "Configure the Windows port-forwarding and firewall rules now?",
        stdin=stdin,
        stdout=stdout,
    ):
        stdout.write(
            "No changes were made. If you change your mind, run the commands above in "
            "an Administrator PowerShell window or run trwprep again.\n"
        )
        raise SourceUnavailableError(
            "DevTools forwarding is not configured. Run trwprep again and approve the "
            "Windows UAC request when ready."
        )
    stdout.write("Windows will ask for permission to configure the local forwarding rules.\n")
    stdout.flush()
    configure_forwarding(spec)


def _load_playwright() -> Any:  # pragma: no cover - live dependency boundary
    try:
        return importlib.import_module("playwright.sync_api")
    except ModuleNotFoundError as exc:
        raise SourceUnavailableError(
            "Playwright is missing. Reinstall or upgrade transcript-weaver."
        ) from exc


def _show_otter(endpoint: str, *, playwright_api: Any | None = None) -> None:
    sync_api = playwright_api or _load_playwright()
    try:
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            if not browser.contexts:
                raise SourceUnavailableError(
                    "Connected to the TRW Otter browser but found no browser context."
                )
            context = browser.contexts[0]
            pages = [page for page in context.pages if "otter.ai" in str(page.url)]
            page = pages[0] if pages else context.new_page()
            if not pages:
                page.goto(OTTER_SPEC.start_url, wait_until="domcontentloaded")
            page.bring_to_front()
    except SourceUnavailableError:
        raise
    except Exception as exc:
        summary = str(exc).splitlines()[0].strip()
        raise SourceUnavailableError(
            f"Could not prepare the Otter browser page: {summary or type(exc).__name__}."
        ) from exc


def _validate_dom_browser(endpoint: str, *, playwright_api: Any | None = None) -> None:
    sync_api = playwright_api or _load_playwright()
    try:
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            contexts = browser.contexts
            if len(contexts) != 1:
                raise SourceUnavailableError(
                    "The prepared DOM browser must have exactly one browser context; "
                    f"found {len(contexts)}. Leave the browser open, correct it, and run "
                    "'trwprep dom' again."
                )
            pages = contexts[0].pages
            if len(pages) != 1:
                raise SourceUnavailableError(
                    f"The prepared DOM browser must have exactly one tab; found {len(pages)}. "
                    "Leave the browser open, close extra tabs, and run 'trwprep dom' again."
                )
    except SourceUnavailableError:
        raise
    except Exception as exc:
        summary = str(exc).splitlines()[0].strip()
        raise SourceUnavailableError(
            f"Could not inspect the prepared DOM browser: {summary or type(exc).__name__}."
        ) from exc


def prepare_browser(
    mode: str,
    *,
    stdin: TextIO,
    stdout: TextIO,
    playwright_api: Any | None = None,
    ready: Callable[[str], bool] = cdp_ready,
) -> None:
    spec = DOM_SPEC if mode == "dom" else OTTER_SPEC
    endpoint = cdp_url(spec)
    already_running = ready(endpoint)
    if not already_running:
        override = os.environ.get(f"TRANSCRIPT_WEAVER_{spec.name.upper()}_CDP_URL")
        if override:
            raise SourceUnavailableError(
                f"The configured {spec.name} DevTools endpoint is not reachable: {override}"
            )
        _ensure_forwarding(spec, stdin=stdin, stdout=stdout)
        profile = (
            _choose_otter_profile(stdin=stdin, stdout=stdout)
            if spec is OTTER_SPEC
            else selected_profile_path(spec)
        )
        start_chrome(spec, profile=profile)
        wait_for_cdp(endpoint)
        stdout.write(f"Started the dedicated TRW {spec.name} Chrome profile:\n  {profile}\n")
    else:
        stdout.write(f"The dedicated TRW {spec.name} browser is already running.\n")
    if spec is OTTER_SPEC:
        _show_otter(endpoint, playwright_api=playwright_api)
        stdout.write("Otter is ready. Complete sign-in if needed; later run 'trwinp otter'.\n")
    else:
        _validate_dom_browser(endpoint, playwright_api=playwright_api)
        stdout.write("Prepare exactly one page in this browser, then run 'trwinp dom'.\n")

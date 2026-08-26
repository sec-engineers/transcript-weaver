"""Acquire the current DOM from a prepared, already-running Chrome tab."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import datetime
from typing import Any

from transcript_weaver.browser import DOM_SPEC, cdp_ready, cdp_url
from transcript_weaver.inp.errors import SourceUnavailableError, TranscriptNotFoundError
from transcript_weaver.models import AcquiredTranscript, Source


def _load_playwright() -> Any:  # pragma: no cover - live dependency boundary
    try:
        return importlib.import_module("playwright.sync_api")
    except ModuleNotFoundError as exc:
        raise SourceUnavailableError(
            "Playwright is missing. Reinstall or upgrade transcript-weaver."
        ) from exc


class DomSource:
    def __init__(
        self,
        *,
        endpoint: str | None = None,
        clock: Callable[[], datetime] | None = None,
        playwright_api: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._playwright_api = playwright_api

    def acquire(self) -> AcquiredTranscript:
        endpoint = self._endpoint or cdp_url(DOM_SPEC)
        if not cdp_ready(endpoint):
            raise SourceUnavailableError(
                "The prepared TRW DOM browser is not running or reachable. Run 'trwprep dom' first."
            )
        sync_api = self._playwright_api or _load_playwright()
        try:
            with sync_api.sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(endpoint)
                contexts = browser.contexts
                if len(contexts) != 1:
                    raise SourceUnavailableError(
                        "TRW DOM browser must have exactly one browser context; "
                        f"found {len(contexts)}."
                    )
                pages = contexts[0].pages
                if len(pages) != 1:
                    raise SourceUnavailableError(
                        f"TRW DOM browser must have exactly one tab; found {len(pages)}."
                    )
                page = pages[0]
                html = page.content()
                if not html.strip():
                    raise TranscriptNotFoundError("The current browser DOM is empty.")
                return AcquiredTranscript(
                    transcript=html,
                    recorded_at=self._clock(),
                    source=Source(
                        type="dom",
                        name=str(page.title()) or None,
                        reference=str(page.url) or None,
                    ),
                )
        except (SourceUnavailableError, TranscriptNotFoundError):
            raise
        except Exception as exc:
            summary = str(exc).splitlines()[0].strip()
            raise SourceUnavailableError(
                f"Could not capture the current browser DOM: {summary or type(exc).__name__}."
            ) from exc

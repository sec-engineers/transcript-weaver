"""Small provider boundary and Gemini REST implementation."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


def _bounded_text(value: Any, *, secret: str, limit: int = 600) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.replace(secret, "[redacted]").split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3].rstrip() + "..."


def _quota_label(quota_id: str, metric: str) -> str:
    folded = f"{quota_id} {metric}".casefold()
    period = "daily" if "perday" in folded else "per-minute" if "perminute" in folded else ""
    resource = "input-token" if "token" in folded else "request" if "request" in folded else "quota"
    return " ".join(part for part in (period, resource, "limit exceeded") if part)


def _http_error_reason(exc: urllib.error.HTTPError, *, secret: str) -> str | None:
    try:
        raw = exc.read(65_537)
    except (OSError, ValueError):
        return None
    if not raw or len(raw) > 65_536:
        return None
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    error = envelope.get("error") if isinstance(envelope, dict) else None
    if not isinstance(error, dict):
        return None

    reasons: list[str] = []
    retry_delay: str | None = None
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and delay.strip():
                retry_delay = delay.strip()
            violations = detail.get("violations")
            if not isinstance(violations, list):
                continue
            for violation in violations:
                if not isinstance(violation, dict):
                    continue
                quota_id = violation.get("quotaId", "")
                metric = violation.get("quotaMetric", "")
                label = _quota_label(str(quota_id), str(metric))
                dimensions = violation.get("quotaDimensions")
                model = dimensions.get("model") if isinstance(dimensions, dict) else None
                quota_value = violation.get("quotaValue")
                qualifiers = []
                if isinstance(model, str) and model:
                    qualifiers.append(f"model {model}")
                if isinstance(quota_value, (str, int, float)):
                    qualifiers.append(f"limit {quota_value}")
                reason = label + (f" ({', '.join(qualifiers)})" if qualifiers else "")
                if reason not in reasons:
                    reasons.append(reason)
    if retry_delay:
        reasons.append(f"Google recommends retrying after {retry_delay}")
    if reasons:
        return _bounded_text("; ".join(reasons), secret=secret)
    return _bounded_text(error.get("message"), secret=secret)


class Provider(Protocol):
    model: str

    def transform(self, system: str, prompt: str, packet_json: str) -> str: ...


@dataclass(slots=True)
class GeminiProvider:
    model: str
    credential_name: str
    opener: Callable[..., Any] = urllib.request.urlopen
    sleeper: Callable[[float], None] = time.sleep
    max_attempts: int = 5
    retry_reporter: Callable[[str], None] | None = None

    def _report_retry(self, message: str) -> None:
        if self.retry_reporter is not None:
            self.retry_reporter(message)

    def _secret(self) -> str:
        try:
            result = subprocess.run(
                ["pass", self.credential_name],
                check=True,
                text=True,
                capture_output=True,
            )
            secret = result.stdout.splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError) as exc:
            raise ProviderError(
                "Could not retrieve the configured Gemini credential from pass."
            ) from exc
        if not secret:
            raise ProviderError("The configured Gemini credential from pass is empty.")
        return secret

    def transform(self, system: str, prompt: str, packet_json: str) -> str:
        secret = self._secret()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={secret}"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}, {"text": packet_json}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self.opener(request, timeout=120) as response:
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                transient = exc.code in {429, 500, 502, 503, 504}
                reason = _http_error_reason(exc, secret=secret)
                why = f": {reason}" if reason else ""
                if transient and attempt < self.max_attempts:
                    delay = float(attempt * attempt)
                    self._report_retry(
                        f"Gemini HTTP {exc.code}{why}; retry {attempt} of "
                        f"{self.max_attempts - 1} in {delay:g} seconds"
                    )
                    self.sleeper(delay)
                    continue
                raise ProviderError(
                    f"Gemini request failed with HTTP status {exc.code}{why}.",
                    transient=transient,
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raw_reason = exc.reason if isinstance(exc, urllib.error.URLError) else str(exc)
                reason = _bounded_text(str(raw_reason), secret=secret)
                why = f": {reason}" if reason else ""
                if attempt < self.max_attempts:
                    delay = float(attempt * attempt)
                    self._report_retry(
                        f"Gemini network error{why}; retry {attempt} of "
                        f"{self.max_attempts - 1} in {delay:g} seconds"
                    )
                    self.sleeper(delay)
                    continue
                raise ProviderError(
                    f"Gemini request failed after transient network errors{why}.",
                    transient=True,
                ) from exc
        try:
            envelope = json.loads(raw)
            text = envelope["candidates"][0]["content"]["parts"][0]["text"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Gemini returned an unexpected response shape.") from exc
        if not isinstance(text, str):
            raise ProviderError("Gemini returned a non-text response.")
        return text


def build_provider(
    name: str,
    config: dict[str, Any],
    *,
    retry_reporter: Callable[[str], None] | None = None,
) -> Provider:
    if name.casefold() != "gemini":
        raise ProviderError(f"Unsupported provider {name!r}.")
    if set(config) != {"model", "credential"} or not isinstance(config.get("model"), str):
        raise ProviderError(f"Provider {name!r} configuration is invalid.")
    credential = config.get("credential")
    if (
        not isinstance(credential, dict)
        or set(credential) != {"source", "name"}
        or credential.get("source") != "pass"
        or not isinstance(credential.get("name"), str)
        or not credential["name"]
    ):
        raise ProviderError(
            f"Provider {name!r} credential must specify source 'pass' and a nonempty name."
        )
    return GeminiProvider(config["model"], credential["name"], retry_reporter=retry_reporter)

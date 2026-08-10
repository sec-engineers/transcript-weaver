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
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
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
                if transient and attempt < self.max_attempts:
                    delay = float(attempt * attempt)
                    self._report_retry(
                        f"Gemini HTTP {exc.code}; retry {attempt} of "
                        f"{self.max_attempts - 1} in {delay:g} seconds"
                    )
                    self.sleeper(delay)
                    continue
                raise ProviderError(
                    f"Gemini request failed with HTTP status {exc.code}.", transient=transient
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_attempts:
                    delay = float(attempt * attempt)
                    self._report_retry(
                        f"Gemini network error; retry {attempt} of "
                        f"{self.max_attempts - 1} in {delay:g} seconds"
                    )
                    self.sleeper(delay)
                    continue
                raise ProviderError(
                    "Gemini request failed after transient network errors.", transient=True
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

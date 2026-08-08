"""Prompt resolution and strict enrichment validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from transcript_weaver.config import AppConfig, ApplicationPaths, ConfigurationError
from transcript_weaver.profiles import find_profile, resolve_configured_path
from transcript_weaver.weave.provider import Provider, ProviderError, build_provider

SYSTEM_INSTRUCTION = (
    "You are one stage in a JSON-to-JSON pipeline. Return exactly one complete JSON "
    "object with no Markdown fences or explanatory prose. Preserve every input field "
    "and value exactly: do not modify or delete anything. Add transformation results "
    "without changing existing data. Follow the user transformation prompt for "
    "classification and content."
)


class WeaveError(RuntimeError):
    pass


def _read_prompt(path: Path) -> str:
    if not path.exists():
        raise WeaveError(f"Prompt file does not exist: {path}")
    if not path.is_file():
        raise WeaveError(f"Prompt path is not a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WeaveError(f"Could not read prompt as UTF-8: {path}") from exc
    if not text.strip():
        raise WeaveError(f"Prompt file is empty: {path}")
    return text


def resolve_prompt(
    argument: str, config: AppConfig, paths: ApplicationPaths
) -> tuple[str, str, str]:
    candidate = Path(argument).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.exists():
        return _read_prompt(candidate), "gemini", str(candidate.resolve())
    try:
        profile_name, profile = find_profile(config.weave, argument, kind="weave")
    except ConfigurationError as exc:
        raise WeaveError(str(exc)) from exc
    if set(profile) != {"provider", "prompt"} and set(profile) != {"provider", "prompt_file"}:
        raise WeaveError(
            f"Weave profile {profile_name!r} must contain provider and exactly one of "
            "prompt or prompt_file."
        )
    provider = profile.get("provider")
    if not isinstance(provider, str) or not provider:
        raise WeaveError(f"Weave profile {profile_name!r} provider must be a nonempty string.")
    if "prompt" in profile:
        prompt = profile["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise WeaveError(f"Weave profile {profile_name!r} prompt must be nonempty.")
    else:
        prompt = _read_prompt(
            resolve_configured_path(
                profile["prompt_file"],
                config_file=paths.config_file,
                field=f"weave.{profile_name}.prompt_file",
            )
        )
    return prompt, provider, profile_name


def _preserves(original: Any, enriched: Any, path: str = "packet") -> None:
    if isinstance(original, dict):
        if not isinstance(enriched, dict):
            raise WeaveError(f"Provider modified original field {path}.")
        for key, value in original.items():
            if key not in enriched:
                raise WeaveError(f"Provider deleted original field {path}.{key}.")
            _preserves(value, enriched[key], f"{path}.{key}")
    elif isinstance(original, list):
        if not isinstance(enriched, list) or len(original) != len(enriched):
            raise WeaveError(f"Provider modified original field {path}.")
        for index, value in enumerate(original):
            _preserves(value, enriched[index], f"{path}[{index}]")
    elif type(original) is not type(enriched) or original != enriched:
        raise WeaveError(f"Provider modified original field {path}.")


def validate_response(text: str, original: dict[str, Any]) -> dict[str, Any]:
    try:
        enriched = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WeaveError("Provider response was not exactly one valid JSON object.") from exc
    if not isinstance(enriched, dict):
        raise WeaveError("Provider response must be a top-level JSON object.")
    _preserves(original, enriched)
    weave = enriched.get("weave")
    if (
        not isinstance(weave, dict)
        or not isinstance(weave.get("type"), str)
        or not weave["type"].strip()
        or not isinstance(weave.get("content"), str)
        or not weave["content"].strip()
    ):
        raise WeaveError(
            "Provider response must contain weave with nonempty string type and content."
        )
    return enriched


def transform(
    packet: dict[str, Any],
    argument: str,
    config: AppConfig,
    paths: ApplicationPaths,
    *,
    provider: Provider | None = None,
) -> tuple[dict[str, Any], str, str]:
    prompt, provider_name, selected = resolve_prompt(argument, config, paths)
    try:
        configured_name, provider_config = find_profile(
            config.providers, provider_name, kind="provider"
        )
        active = provider or build_provider(configured_name, provider_config)
        response = active.transform(
            SYSTEM_INSTRUCTION, prompt, json.dumps(packet, ensure_ascii=False)
        )
    except (ConfigurationError, ProviderError) as exc:
        raise WeaveError(str(exc)) from exc
    return validate_response(response, packet), selected, active.model

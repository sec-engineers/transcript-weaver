"""Shared profile, path, and packet-field helpers."""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from transcript_weaver.config import ConfigurationError


def available_profiles(profiles: Mapping[str, Any]) -> str:
    return ", ".join(sorted(profiles)) or "none configured"


def find_profile(profiles: Mapping[str, Any], name: str, *, kind: str) -> tuple[str, Any]:
    for configured, value in profiles.items():
        if configured.casefold() == name.casefold():
            return configured, value
    match = difflib.get_close_matches(name.casefold(), [x.casefold() for x in profiles], n=1)
    suggestion = ""
    if match:
        original = next(x for x in profiles if x.casefold() == match[0])
        suggestion = f" Did you mean {original!r}?"
    available = available_profiles(profiles)
    raise ConfigurationError(
        f"Unknown {kind} profile {name!r}.{suggestion} Available profiles: {available}."
    )


def resolve_configured_path(value: Any, *, config_file: Path, field: str) -> Path:
    raw: Any
    relative_to: Any
    if isinstance(value, str):
        raw = value
        relative_to = "config"
    elif isinstance(value, dict):
        effective = {key: item for key, item in value.items() if not key.startswith("_comment")}
        if set(effective) not in ({"path"}, {"path", "relative_to"}):
            raise ConfigurationError(
                f"{field} must contain path and, for relative paths, relative_to."
            )
        raw = effective.get("path")
        relative_to = effective.get("relative_to")
    else:
        raise ConfigurationError(f"{field} must be a path string or path object.")
    if not isinstance(raw, str) or not raw:
        raise ConfigurationError(f"{field}.path must be a nonempty string.")
    path = Path(raw).expanduser()
    if path.is_absolute():
        if relative_to not in {None, "config"} and isinstance(value, dict):
            raise ConfigurationError(
                f"{field}.relative_to must be omitted for an absolute or '~' path."
            )
        return path.resolve(strict=False)
    if relative_to == "cwd":
        base = Path.cwd()
    elif relative_to == "config":
        base = config_file.parent
    else:
        raise ConfigurationError(
            f"{field}.relative_to must be 'cwd' or 'config' for a relative path."
        )
    return (base / path).resolve(strict=False)


def extract_dotted(packet: Mapping[str, Any], dotted: str, *, field: str) -> Any:
    current: Any = packet
    for part in dotted.split("."):
        if not part or not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"Packet field {dotted!r} configured for {field} is missing.")
        current = current[part]
    return current

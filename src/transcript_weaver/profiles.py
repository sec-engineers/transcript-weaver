"""Shared profile, path, and packet-field helpers."""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from transcript_weaver.config import ConfigurationError


def find_profile(profiles: Mapping[str, Any], name: str, *, kind: str) -> tuple[str, Any]:
    for configured, value in profiles.items():
        if configured.casefold() == name.casefold():
            return configured, value
    match = difflib.get_close_matches(name.casefold(), [x.casefold() for x in profiles], n=1)
    suggestion = ""
    if match:
        original = next(x for x in profiles if x.casefold() == match[0])
        suggestion = f" Did you mean {original!r}?"
    available = ", ".join(sorted(profiles)) or "none configured"
    raise ConfigurationError(
        f"Unknown {kind} profile {name!r}.{suggestion} Available profiles: {available}."
    )


def resolve_configured_path(value: Any, *, config_file: Path, field: str) -> Path:
    cwd = False
    raw: Any
    if isinstance(value, str):
        raw = value
    elif isinstance(value, dict) and set(value) == {"path", "relative_to"}:
        raw = value.get("path")
        if value.get("relative_to") != "cwd":
            raise ConfigurationError(f"{field}.relative_to must be 'cwd'.")
        cwd = True
    else:
        raise ConfigurationError(
            f"{field} must be a path string or an object with path and relative_to='cwd'."
        )
    if not isinstance(raw, str) or not raw:
        raise ConfigurationError(f"{field} path must be a nonempty string.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() if cwd else config_file.parent) / path
    return path.resolve(strict=False)


def extract_dotted(packet: Mapping[str, Any], dotted: str, *, field: str) -> Any:
    current: Any = packet
    for part in dotted.split("."):
        if not part or not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"Packet field {dotted!r} configured for {field} is missing.")
        current = current[part]
    return current

"""Resolve configured credentials without exposing their values."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path


class CredentialError(RuntimeError):
    """Raised when a configured credential cannot be resolved safely."""


def resolve_credential(
    spec: str,
    *,
    label: str = "credential",
    warning: Callable[[str], None] | None = None,
) -> str:
    """Resolve an explicit env/file/command/literal credential specification."""
    source, separator, remainder = spec.partition("(")
    argument = remainder[:-1] if separator == "(" and spec.endswith(")") else ""
    if source not in {"env", "file", "command", "literal"} or not argument.strip():
        raise CredentialError(f"The configured {label} specification is invalid.")
    try:
        if source == "env":
            value = os.environ.get(argument, "")
        elif source == "file":
            value = Path(argument).expanduser().read_text(encoding="utf-8")
        elif source == "command":
            result = subprocess.run(
                argument,
                check=True,
                text=True,
                capture_output=True,
                shell=True,
            )
            value = result.stdout
        else:
            if warning is not None:
                warning(
                    f"{label.capitalize()} is stored directly in the TRW configuration; "
                    "this is discouraged. Prefer env(...), file(...), or command(...)."
                )
            value = argument
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise CredentialError(
            f"Could not resolve the configured {label} from {source}(...)."
        ) from None
    lines = value.splitlines()
    secret = lines[0].strip() if lines else ""
    if not secret:
        raise CredentialError(f"The configured {label} from {source}(...) is empty.")
    return secret

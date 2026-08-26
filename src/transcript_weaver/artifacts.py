"""Temporary permission for explicitly requested sensitive debug artifacts."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

PERMISSION_DURATION = timedelta(hours=1)
PERMISSION_FILENAME = "debug-artifacts-permission.json"
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ArtifactPermissionError(RuntimeError):
    """The temporary sensitive-artifact permission is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class ArtifactPermission:
    enabled_at: datetime
    expires_at: datetime


def permission_directory(runtime_directory: Path | None, log_directory: Path) -> Path:
    return runtime_directory or log_directory.parent / "runtime"


def permission_path(runtime_directory: Path) -> Path:
    return runtime_directory / PERMISSION_FILENAME


def _utc_now(clock: datetime | None = None) -> datetime:
    value = clock or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ArtifactPermissionError("Artifact permission time must include a timezone.")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def read_permission(
    runtime_directory: Path, *, clock: datetime | None = None
) -> ArtifactPermission | None:
    path = permission_path(runtime_directory)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ArtifactPermissionError(f"Artifact permission path is unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "enabled_at",
            "expires_at",
        }:
            raise ValueError
        if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
            raise ValueError
        enabled_at = datetime.strptime(value["enabled_at"], UTC_FORMAT).replace(tzinfo=timezone.utc)
        expires_at = datetime.strptime(value["expires_at"], UTC_FORMAT).replace(tzinfo=timezone.utc)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ArtifactPermissionError(f"Artifact permission record is invalid: {path}") from exc
    if expires_at <= _utc_now(clock):
        return None
    return ArtifactPermission(enabled_at, expires_at)


def enable_permission(
    runtime_directory: Path, *, clock: datetime | None = None
) -> ArtifactPermission:
    enabled_at = _utc_now(clock)
    permission = ArtifactPermission(enabled_at, enabled_at + PERMISSION_DURATION)
    if runtime_directory.exists() and (
        runtime_directory.is_symlink() or not runtime_directory.is_dir()
    ):
        raise ArtifactPermissionError(
            f"Artifact permission directory is unsafe: {runtime_directory}"
        )
    runtime_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        runtime_directory.chmod(0o700)
    except OSError as exc:
        raise ArtifactPermissionError(
            f"Could not secure artifact permission directory: {runtime_directory}"
        ) from exc
    path = permission_path(runtime_directory)
    temporary = runtime_directory / f".{PERMISSION_FILENAME}.{uuid.uuid4().hex}.tmp"
    payload = {
        "schema_version": 1,
        "enabled_at": permission.enabled_at.strftime(UTC_FORMAT),
        "expires_at": permission.expires_at.strftime(UTC_FORMAT),
    }
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise ArtifactPermissionError(f"Could not write artifact permission: {path}") from exc
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()
    return permission


def disable_permission(runtime_directory: Path) -> bool:
    path = permission_path(runtime_directory)
    if path.is_symlink():
        raise ArtifactPermissionError(f"Artifact permission path is unsafe: {path}")
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False

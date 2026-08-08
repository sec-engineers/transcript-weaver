"""Per-user configuration loading and validation."""

from __future__ import annotations

import json
import os
import platform
import uuid
from contextlib import suppress
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from platformdirs import PlatformDirs

CONFIG_SCHEMA_VERSION = 1


class ConfigurationError(RuntimeError):
    """Raised when user configuration cannot be safely loaded."""


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    retained_runs: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    schema_version: int
    logging: LoggingConfig
    providers: dict[str, dict[str, Any]]
    weave: dict[str, dict[str, Any]]
    out: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    config_file: Path
    log_directory: Path


def get_application_paths(
    config_dirs: PlatformDirs | None = None, log_dirs: PlatformDirs | None = None
) -> ApplicationPaths:
    if config_dirs is None or log_dirs is None:
        app_name = "transcript-weaver" if platform.system() == "Linux" else "Transcript Weaver"
        config_dirs = config_dirs or PlatformDirs(appname=app_name, appauthor=False, roaming=True)
        log_dirs = log_dirs or PlatformDirs(appname=app_name, appauthor=False, roaming=False)
    return ApplicationPaths(
        Path(config_dirs.user_config_path) / "config.json", Path(log_dirs.user_log_path)
    )


def packaged_default_config_bytes() -> bytes:
    return (
        resources.files("transcript_weaver.resources").joinpath("default-config.json").read_bytes()
    )


def _profiles(value: Any, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration {name} section must be an object.")
    result: dict[str, dict[str, Any]] = {}
    seen: dict[str, str] = {}
    for key, profile in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(profile, dict):
            raise ConfigurationError(f"Configuration {name} profiles must be named objects.")
        folded = key.casefold()
        if folded in seen:
            raise ConfigurationError(
                f"Configuration {name} profile names {seen[folded]!r} and {key!r} "
                "differ only by case."
            )
        seen[folded] = key
        result[key] = profile
    return result


def validate_config(value: Any, *, path: Path) -> AppConfig:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration must be a JSON object: {path}")
    allowed = {"schema_version", "logging", "providers", "weave", "out"}
    if set(value) != allowed:
        raise ConfigurationError(f"Configuration has unrecognized or missing fields: {path}")
    if value.get("schema_version") != 1 or isinstance(value.get("schema_version"), bool):
        raise ConfigurationError(f"Unsupported configuration schema_version: {path}")
    logging_value = value.get("logging")
    if not isinstance(logging_value, dict) or set(logging_value) != {"retained_runs"}:
        raise ConfigurationError(f"Configuration logging section is invalid: {path}")
    retained = logging_value.get("retained_runs")
    if not isinstance(retained, int) or isinstance(retained, bool) or retained < 0:
        raise ConfigurationError(
            f"Configuration logging.retained_runs must be a nonnegative integer: {path}"
        )
    providers = _profiles(value.get("providers"), "providers")
    weave = _profiles(value.get("weave"), "weave")
    out = _profiles(value.get("out"), "out")
    return AppConfig(1, LoggingConfig(retained), providers, weave, out)


def load_or_create_config(paths: ApplicationPaths) -> AppConfig:
    config_path = paths.config_file
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _create_from_packaged_default(config_path)
    try:
        return validate_config(
            json.loads(config_path.read_text(encoding="utf-8")), path=config_path
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Could not read valid JSON configuration: {config_path}") from exc


def _create_from_packaged_default(config_path: Path) -> None:
    data = packaged_default_config_bytes()
    try:
        validate_config(json.loads(data.decode("utf-8")), path=config_path)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("Packaged default configuration is invalid.") from exc
    temporary = config_path.parent / f".{config_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, config_path)
        except FileExistsError:
            pass
        except OSError as exc:
            if not config_path.exists():
                raise ConfigurationError(
                    f"Could not create configuration atomically: {config_path}"
                ) from exc
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()

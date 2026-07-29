"""Per-user configuration loading and platform-specific application paths."""

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


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    config_file: Path
    log_directory: Path


def get_application_paths(
    config_dirs: PlatformDirs | None = None,
    log_dirs: PlatformDirs | None = None,
) -> ApplicationPaths:
    """Return conventional config and log paths without creating either."""
    if config_dirs is None or log_dirs is None:
        system = platform.system()
        app_name = "transcript-weaver" if system == "Linux" else "Transcript Weaver"
        config_dirs = config_dirs or PlatformDirs(appname=app_name, appauthor=False, roaming=True)
        log_dirs = log_dirs or PlatformDirs(appname=app_name, appauthor=False, roaming=False)
    return ApplicationPaths(
        config_file=Path(config_dirs.user_config_path) / "config.json",
        log_directory=Path(log_dirs.user_log_path),
    )


def packaged_default_config_bytes() -> bytes:
    resource = resources.files("transcript_weaver.resources").joinpath("default-config.json")
    return resource.read_bytes()


def validate_config(value: Any, *, path: Path) -> AppConfig:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration must be a JSON object: {path}")
    allowed_top = {"schema_version", "logging"}
    if set(value) != allowed_top:
        raise ConfigurationError(f"Configuration has unrecognized or missing fields: {path}")
    if value.get("schema_version") != CONFIG_SCHEMA_VERSION or isinstance(
        value.get("schema_version"), bool
    ):
        raise ConfigurationError(f"Unsupported configuration schema_version: {path}")
    logging_value = value.get("logging")
    if not isinstance(logging_value, dict) or set(logging_value) != {"retained_runs"}:
        raise ConfigurationError(f"Configuration logging section is invalid: {path}")
    retained_runs = logging_value.get("retained_runs")
    if not isinstance(retained_runs, int) or isinstance(retained_runs, bool) or retained_runs < 0:
        raise ConfigurationError(
            f"Configuration logging.retained_runs must be a nonnegative integer: {path}"
        )
    return AppConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        logging=LoggingConfig(retained_runs=retained_runs),
    )


def load_or_create_config(paths: ApplicationPaths) -> AppConfig:
    """Atomically create the user copy once, then validate without rewriting it."""
    config_path = paths.config_file
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _create_from_packaged_default(config_path)
    try:
        raw = config_path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Could not read valid JSON configuration: {config_path}") from exc
    return validate_config(value, path=config_path)


def _create_from_packaged_default(config_path: Path) -> None:
    data = packaged_default_config_bytes()
    # Validate the packaged template before copying it into a user's directory.
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
            # Another command won the first-run race; its complete file is authoritative.
            pass
        except OSError as exc:
            if config_path.exists():
                pass
            else:
                raise ConfigurationError(
                    f"Could not create configuration atomically: {config_path}"
                ) from exc
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()

"""Shared pipeline run correlation, logging, artifacts, and retention."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
ARTIFACT_SUFFIX_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIAGNOSTIC_FILE_PATTERN = re.compile(
    r"^(?P<run>\d{8}-\d{6}-[0-9a-f]{4})-"
    r"(?P<stage>trwinp|trweave|trwout)(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?"
    r"(?P<extension>\.log|\.html|\.png|\.json)$"
)
SUPPORTED_EXTENSIONS = {".log", ".html", ".png", ".json"}


class RunIdError(ValueError):
    """Raised when packet run correlation is malformed."""


class DiagnosticError(RuntimeError):
    """Raised when optional diagnostics cannot be created safely."""


@dataclass(frozen=True, slots=True)
class LoggingOptions:
    log: bool = False
    verbose: bool = False
    debug_artifacts: bool = False

    @property
    def enabled(self) -> bool:
        return self.log or self.verbose or self.debug_artifacts

    @property
    def detailed(self) -> bool:
        return self.verbose or self.debug_artifacts


class _UtcFormatter(logging.Formatter):
    def converter(self, timestamp: float | None) -> time.struct_time:
        return time.gmtime(timestamp)


class StageLog:
    """Invocation-isolated persistent logger; no root logger mutation."""

    def __init__(
        self,
        *,
        run_id: str,
        stage: str,
        options: LoggingOptions,
        log_directory: Path,
    ) -> None:
        self.run_id = validate_run_id(run_id)
        self.stage = stage
        self.options = options
        self.log_directory = log_directory
        self.path: Path | None = None
        self._logger = logging.getLogger(f"transcript_weaver.{stage}.{id(self)}")
        self._logger.propagate = False
        self._logger.setLevel(logging.DEBUG if options.detailed else logging.INFO)
        self._handler: logging.Handler = logging.NullHandler()
        if options.enabled:
            log_directory.mkdir(parents=True, exist_ok=True)
            self.path = build_diagnostic_path(log_directory, run_id, stage, extension=".log")
            try:
                self._handler = logging.FileHandler(self.path, mode="x", encoding="utf-8")
            except OSError as exc:
                raise DiagnosticError(f"Could not create diagnostic log: {self.path}") from exc
            formatter = _UtcFormatter(
                f"%(asctime)s.%(msecs)03dZ %(levelname)s run={run_id} stage={stage} %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
            self._handler.setFormatter(formatter)
            self._logger.addHandler(self._handler)
        else:
            self._logger.addHandler(self._handler)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def debug(self, message: str) -> None:
        self._logger.debug(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def exception(self, message: str) -> None:
        if self.options.detailed:
            self._logger.exception(message)
        else:
            self._logger.error(message)

    def close(self) -> None:
        self._handler.flush()
        self._handler.close()
        self._logger.removeHandler(self._handler)


def generate_run_id(clock: datetime | None = None) -> str:
    instant = clock or datetime.now(timezone.utc)
    return f"{instant.astimezone(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def validate_run_id(value: Any) -> str:
    if not isinstance(value, str) or not RUN_ID_PATTERN.fullmatch(value):
        raise RunIdError("Packet run.id is missing or invalid.")
    return value


def ensure_packet_run_id(packet: dict[str, Any], *, clock: datetime | None = None) -> str:
    run = packet.get("run")
    if run is None:
        run_id = generate_run_id(clock)
        packet["run"] = {"id": run_id}
        return run_id
    if not isinstance(run, dict) or set(run) != {"id"}:
        raise RunIdError("Packet run must be an object containing only id.")
    return validate_run_id(run.get("id"))


def read_packet_run_id(packet: Mapping[str, Any]) -> str | None:
    run = packet.get("run")
    if run is None:
        return None
    if not isinstance(run, Mapping):
        raise RunIdError("Packet run must be an object containing id.")
    return validate_run_id(run.get("id"))


def build_diagnostic_path(
    log_directory: Path,
    run_id: str,
    stage: str,
    *,
    extension: str,
    suffix: str | None = None,
) -> Path:
    validate_run_id(run_id)
    if stage not in {"trwinp", "trweave", "trwout"}:
        raise DiagnosticError("Invalid pipeline stage for diagnostic filename.")
    if extension not in SUPPORTED_EXTENSIONS:
        raise DiagnosticError("Unsupported diagnostic artifact extension.")
    if suffix is not None and not ARTIFACT_SUFFIX_PATTERN.fullmatch(suffix):
        raise DiagnosticError("Diagnostic artifact suffix is unsafe.")
    suffix_part = f"-{suffix}" if suffix else ""
    return log_directory / f"{run_id}-{stage}{suffix_part}{extension}"


def write_debug_artifact(
    log_directory: Path,
    run_id: str,
    stage: str,
    *,
    suffix: str,
    extension: str,
    content: str | bytes,
) -> Path:
    log_directory.mkdir(parents=True, exist_ok=True)
    path = build_diagnostic_path(log_directory, run_id, stage, extension=extension, suffix=suffix)
    if isinstance(content, bytes):
        with path.open("xb") as stream:
            stream.write(content)
    else:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    return path


def write_preservation_artifacts(
    log_directory: Path,
    run_id: str,
    *,
    original: Mapping[str, Any],
    provider_output: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Persist sensitive before/after packets for an immutable-field failure."""
    failure_directory = log_directory / "packet-failures"
    original_path = write_debug_artifact(
        failure_directory,
        run_id,
        "trweave",
        suffix="original",
        extension=".json",
        content=json.dumps(original, ensure_ascii=False, indent=2) + "\n",
    )
    try:
        provider_path = write_debug_artifact(
            failure_directory,
            run_id,
            "trweave",
            suffix="provider",
            extension=".json",
            content=json.dumps(provider_output, ensure_ascii=False, indent=2) + "\n",
        )
    except BaseException:
        with suppress(FileNotFoundError):
            original_path.unlink()
        raise
    return original_path, provider_path


def apply_log_retention(
    log_directory: Path,
    retained_runs: int,
    *,
    current_run_id: str,
    warn: Callable[[str], None],
) -> None:
    validate_run_id(current_run_id)
    if not log_directory.exists():
        return
    groups: dict[str, list[Path]] = {}
    try:
        entries = list(log_directory.iterdir())
    except OSError as exc:
        warn(f"Could not inspect diagnostic retention directory: {exc}")
        return
    for path in entries:
        if path.is_symlink() or not path.is_file():
            continue
        match = DIAGNOSTIC_FILE_PATTERN.fullmatch(path.name)
        if not match:
            continue
        run_id = match.group("run")
        try:
            validate_run_id(run_id)
        except RunIdError:
            continue
        groups.setdefault(run_id, []).append(path)
    protected = set(sorted(groups, reverse=True)[:retained_runs])
    protected.add(current_run_id)
    for run_id, paths in groups.items():
        if run_id in protected:
            continue
        for path in paths:
            try:
                path.unlink()
            except OSError as exc:
                warn(f"Could not remove expired diagnostic file {path.name}: {exc}")

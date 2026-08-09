"""Deterministic, timezone-aware packet persistence."""

from __future__ import annotations

import os
import re
import string
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from transcript_weaver.config import AppConfig, ApplicationPaths, ConfigurationError
from transcript_weaver.profiles import extract_dotted, find_profile, resolve_configured_path


class OutputError(RuntimeError):
    pass


HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(\d{4}-\d{2}-\d{2})(?:\s.*)?$")


def _atomic_replace(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _atomic_create(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise OutputError(f"Refusing to overwrite existing file: {path}") from exc
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _safe_target(vault: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise OutputError("Destination paths must be relative to the configured vault.")
    target = (vault / candidate).resolve(strict=False)
    try:
        target.relative_to(vault)
    except ValueError as exc:
        raise OutputError("Destination path escapes the configured vault.") from exc
    return target


def _format(template: Any, *, date: str, time: str, content: str) -> str:
    if not isinstance(template, str):
        raise OutputError("Destination format must be a string.")
    for _, field, spec, conversion in string.Formatter().parse(template):
        if field is not None and field not in {"date", "time", "content"}:
            raise OutputError(f"Unsupported format placeholder {{{field}}}.")
        if spec or conversion:
            raise OutputError("Format specifications and conversions are not supported.")
    try:
        return template.format(date=date, time=time, content=content)
    except ValueError as exc:
        raise OutputError("Destination format is malformed.") from exc


def insert_chronologically(existing: str, entry_date: str, block: str) -> tuple[str, bool]:
    matches = list(HEADING_RE.finditer(existing))
    same = [m for m in matches if m.group(1) == entry_date]
    if not matches:
        return ((existing.rstrip() + "\n\n" if existing.strip() else "") + block, False)
    if same:
        last = same[-1]
        later = next((m for m in matches if m.start() > last.start()), None)
        at = later.start() if later else len(existing)
        before, after = existing[:at].rstrip(), existing[at:].lstrip()
        return before + "\n\n---\n\n" + block + after, True
    later = next((m for m in matches if m.group(1) > entry_date), None)
    if later:
        before, after = existing[: later.start()].rstrip(), existing[later.start() :].lstrip()
        return before + "\n\n" + block + after, False
    return existing.rstrip() + "\n\n" + block, False


def persist(
    packet: dict[str, Any],
    profile_argument: str,
    config: AppConfig,
    paths: ApplicationPaths,
    *,
    warn: Callable[[str], None],
) -> tuple[str, Path]:
    try:
        profile_name, profile = find_profile(config.out, profile_argument, kind="output")
    except ConfigurationError as exc:
        raise OutputError(str(exc)) from exc
    required = {"timezone", "vault", "packet_fields", "destinations"}
    if set(profile) != required:
        raise OutputError(
            f"Output profile {profile_name!r} must contain exactly timezone, vault, "
            "packet_fields, and destinations."
        )
    timezone_name = profile["timezone"]
    if not isinstance(timezone_name, str):
        raise OutputError("Output timezone must be an IANA timezone string.")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise OutputError(f"Unknown IANA timezone {timezone_name!r}.") from exc
    try:
        instant = datetime.strptime(packet["datetime"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=ZoneInfo("UTC")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OutputError("Packet datetime must be canonical UTC YYYY-MM-DDTHH:MM:SSZ.") from exc
    local = instant.astimezone(zone)
    date, time_value = local.strftime("%Y-%m-%d"), local.strftime("%H%M")
    fields = profile["packet_fields"]
    if (
        not isinstance(fields, dict)
        or set(fields) != {"category", "content"}
        or not all(isinstance(x, str) for x in fields.values())
    ):
        raise OutputError("packet_fields must contain string category and content paths.")
    try:
        category = extract_dotted(packet, fields["category"], field="category")
        content = extract_dotted(packet, fields["content"], field="content")
    except ValueError as exc:
        raise OutputError(str(exc)) from exc
    if not isinstance(category, str) or not category.strip():
        raise OutputError("Configured category packet field must be a nonempty string.")
    if not isinstance(content, str) or not content.strip():
        raise OutputError("Configured content packet field must be a nonempty string.")
    destinations = profile["destinations"]
    if not isinstance(destinations, Mapping):
        raise OutputError("Output destinations must be an object.")
    found = next(
        (
            (key, val)
            for key, val in destinations.items()
            if isinstance(key, str) and key.casefold() == category.casefold()
        ),
        None,
    )
    if found is None:
        raise OutputError(f"No destination is configured for category {category!r}.")
    destination_name, destination = found
    if not isinstance(destination, dict):
        raise OutputError(f"Destination {destination_name!r} must be an object.")
    operation = destination.get("operation")
    rendered = _format(destination.get("format"), date=date, time=time_value, content=content)
    vault = resolve_configured_path(
        profile["vault"], config_file=paths.config_file, field=f"out.{profile_name}.vault"
    )
    if operation in {"insert", "append"}:
        if set(destination) != {"operation", "file", "format"} or not isinstance(
            destination.get("file"), str
        ):
            raise OutputError(f"Destination {destination_name!r} is invalid for {operation}.")
        target = _safe_target(vault, destination["file"])
        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
        except (OSError, UnicodeError) as exc:
            raise OutputError(f"Could not read destination file: {target}") from exc
        if operation == "insert":
            rendered_content, duplicate = insert_chronologically(existing, date, rendered)
            if duplicate:
                warn(f"journal already contains an entry dated {date}; keeping both entries")
        else:
            rendered_content = existing + rendered
        _atomic_replace(target, rendered_content)
    elif operation == "create":
        if (
            set(destination) != {"operation", "directory", "filename", "format"}
            or not isinstance(destination.get("directory"), str)
            or not isinstance(destination.get("filename"), str)
        ):
            raise OutputError(f"Destination {destination_name!r} is invalid for create.")
        filename = _format(destination["filename"], date=date, time=time_value, content=content)
        target = _safe_target(vault, str(Path(destination["directory"]) / filename))
        _atomic_create(target, rendered)
    else:
        raise OutputError(f"Unsupported output operation {operation!r}.")
    return operation, target

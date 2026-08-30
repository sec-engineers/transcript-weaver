"""Interactive validation and narrowly scoped configuration migration."""

from __future__ import annotations

import json
import os
import shlex
import uuid
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from typing import Any, TextIO

from transcript_weaver.config import (
    CONFIG_SCHEMA_VERSION,
    ApplicationPaths,
    ConfigurationError,
    validate_config,
)
from transcript_weaver.prep.core import confirm


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        original = path.read_bytes()
        value = json.loads(original.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"No configuration file was found at {path}. Run any TRW pipeline "
            "command once to create the current schema-2 configuration."
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Could not read valid JSON configuration: {path}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration {path} must be a JSON object.")
    return value, original


def _schema_one_to_two(value: dict[str, Any], *, path: Path) -> dict[str, Any]:
    providers = value.get("providers")
    if not isinstance(providers, dict) or len(providers) != 1:
        raise ConfigurationError(
            "Automatic schema-1 migration supports exactly one configured provider. "
            "No changes were made; see docs/configuration.md for manual migration."
        )
    provider, settings = next(iter(providers.items()))
    if not isinstance(provider, str) or not provider.strip() or not isinstance(settings, dict):
        raise ConfigurationError(
            "The schema-1 provider configuration is not in the supported form. "
            "No changes were made; see docs/configuration.md for manual migration."
        )
    model = settings.get("model")
    credential = settings.get("credential")
    if (
        {key for key in settings if not key.startswith("_comment")} != {"model", "credential"}
        or not isinstance(model, str)
        or not model.strip()
        or not isinstance(credential, dict)
        or {key for key in credential if not key.startswith("_comment")} != {"source", "name"}
        or credential.get("source") != "pass"
        or not isinstance(credential.get("name"), str)
        or not credential["name"].strip()
    ):
        raise ConfigurationError(
            "Automatic schema-1 migration supports the shipped model and pass-credential "
            "form. No changes were made; see docs/configuration.md for manual migration."
        )
    weave = value.get("weave")
    if not isinstance(weave, dict):
        raise ConfigurationError(
            "The schema-1 weave configuration is not in the supported form. "
            "No changes were made; see docs/configuration.md for manual migration."
        )
    migrated_weave = deepcopy(weave)
    for name, profile in migrated_weave.items():
        if not isinstance(profile, dict) or not isinstance(profile.get("provider"), str):
            raise ConfigurationError(
                f"Schema-1 weave profile {name!r} is not in the supported form. "
                "No changes were made; see docs/configuration.md for manual migration."
            )
        if profile["provider"].casefold() != provider.casefold():
            raise ConfigurationError(
                f"Schema-1 weave profile {name!r} uses a different provider. Automatic "
                "migration was not attempted; see docs/configuration.md."
            )
        del profile["provider"]

    migrated: dict[str, Any] = {}
    for key, item in value.items():
        if key == "schema_version":
            migrated[key] = CONFIG_SCHEMA_VERSION
            migrated["provider"] = provider
            migrated["model"] = model
            pass_name = shlex.quote(credential["name"])
            migrated["api_key"] = f"command(pass show {pass_name})"
        elif key == "providers":
            continue
        elif key == "weave":
            migrated[key] = migrated_weave
        else:
            migrated[key] = deepcopy(item)
    try:
        validate_config(migrated, path=path)
    except ConfigurationError as exc:
        raise ConfigurationError(
            f"The schema-1 configuration could not be migrated safely: {exc} No changes were made."
        ) from None
    return migrated


def _next_backup_path(path: Path) -> Path:
    base = path.with_name(path.name + ".schema-v1.backup")
    if not base.exists():
        return base
    index = 1
    while True:
        candidate = path.with_name(f"{path.name}.schema-v1.backup.{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _write_new_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _replace_atomically(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_new_file(temporary, data)
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def validate_or_offer_migration(paths: ApplicationPaths, *, stdin: TextIO, stdout: TextIO) -> None:
    path = paths.config_file
    value, original = _read_json(path)
    schema = value.get("schema_version")
    if schema == CONFIG_SCHEMA_VERSION and not isinstance(schema, bool):
        validate_config(value, path=path)
        stdout.write(f"Configuration is valid for schema version 2:\n  {path}\n")
        return
    if schema != 1 or isinstance(schema, bool):
        raise ConfigurationError(
            f"Configuration {path} uses unsupported schema_version {schema!r}. "
            f"This TRW release requires schema version {CONFIG_SCHEMA_VERSION}."
        )

    migrated = _schema_one_to_two(value, path=path)
    stdout.write(
        "Configuration schema version 1 was found:\n"
        f"  {path}\n\n"
        "Transcript Weaver currently requires schema version 2. TRW can update\n"
        "this configuration by moving its provider, model, and pass credential\n"
        "to the new global defaults and removing inherited provider fields.\n"
        "A non-overwriting backup will be created first.\n"
    )
    if not confirm("Update this configuration now?", stdin=stdin, stdout=stdout):
        stdout.write("Configuration was not changed.\n")
        return

    backup = _next_backup_path(path)
    updated = (json.dumps(migrated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        _write_new_file(backup, original)
        _replace_atomically(path, updated)
    except OSError as exc:
        raise ConfigurationError(
            f"Could not safely update configuration {path}. The original configuration "
            "was not intentionally replaced."
        ) from exc
    stdout.write(
        "Configuration updated successfully to schema version 2.\n"
        f"Backup created:\n  {backup}\n"
        f"Updated configuration:\n  {path}\n"
    )

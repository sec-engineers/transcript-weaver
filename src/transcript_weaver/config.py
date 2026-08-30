"""Per-user configuration loading, validation, and first-run provisioning."""

from __future__ import annotations

import json
import os
import platform
import uuid
from contextlib import suppress
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PureWindowsPath
from typing import Any

from platformdirs import PlatformDirs

CONFIG_SCHEMA_VERSION = 2
REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "provider",
    "model",
    "api_key",
    "logging",
    "weave",
    "out",
}


class ConfigurationError(RuntimeError):
    """Raised when user configuration cannot be safely loaded."""


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    retained_runs: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    schema_version: int
    provider: str
    model: str
    api_key: str
    logging: LoggingConfig
    weave: dict[str, dict[str, Any]]
    out: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    config_file: Path
    log_directory: Path
    runtime_directory: Path | None = None


@dataclass(frozen=True, slots=True)
class _ResourceFile:
    resource_parts: tuple[str, ...]
    destination: Path


def get_application_paths(
    config_dirs: PlatformDirs | None = None, log_dirs: PlatformDirs | None = None
) -> ApplicationPaths:
    if config_dirs is None or log_dirs is None:
        app_name = "transcript-weaver" if platform.system() == "Linux" else "Transcript Weaver"
        config_dirs = config_dirs or PlatformDirs(appname=app_name, appauthor=False, roaming=True)
        log_dirs = log_dirs or PlatformDirs(appname=app_name, appauthor=False, roaming=False)
    runtime_path = getattr(log_dirs, "user_runtime_path", None)
    if runtime_path is None:
        runtime_path = Path(log_dirs.user_log_path).parent / "runtime"
    return ApplicationPaths(
        Path(config_dirs.user_config_path) / "config.json",
        Path(log_dirs.user_log_path),
        Path(runtime_path),
    )


def _resource_bytes(*parts: str) -> bytes:
    resource = resources.files("transcript_weaver.resources")
    for part in parts:
        resource = resource.joinpath(part)
    return resource.read_bytes()


def packaged_default_config_bytes() -> bytes:
    return _resource_bytes("default-config.json")


def packaged_example_prompt_bytes() -> bytes:
    return _resource_bytes("prompts", "example.md")


def packaged_linkedin_prompt_bytes() -> bytes:
    return _resource_bytes("prompts", "linkedin-profile.md")


def _without_comments(value: Any, *, context: str) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.startswith("_comment"):
                if not isinstance(item, str) and not (
                    isinstance(item, list) and all(isinstance(line, str) for line in item)
                ):
                    raise ConfigurationError(
                        f"{context}.{key} must be a string or an array of strings."
                    )
                continue
            result[key] = _without_comments(item, context=f"{context}.{key}")
        return result
    if isinstance(value, list):
        return [
            _without_comments(item, context=f"{context}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def _require_fields(
    value: Any,
    *,
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{context} must be a JSON object.")
    if any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{context} field names must be strings.")
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - allowed)
    details: list[str] = []
    if missing:
        details.append(f"missing required fields: {', '.join(missing)}")
    if unexpected:
        details.append(f"unrecognized fields: {', '.join(unexpected)}")
    if details:
        expected = ", ".join(sorted(allowed))
        raise ConfigurationError(
            f"{context} has {'; '.join(details)}. Expected fields: {expected}."
        )
    return value


def _profiles(value: Any, name: str, *, path: Path) -> dict[str, dict[str, Any]]:
    context = f"Configuration {path} section {name}"
    if not isinstance(value, dict):
        raise ConfigurationError(f"{context} must be a JSON object.")
    result: dict[str, dict[str, Any]] = {}
    seen: dict[str, str] = {}
    for key, profile in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigurationError(f"{context} profile names must be nonempty strings.")
        if not isinstance(profile, dict):
            raise ConfigurationError(f"{context} profile {key!r} must be a JSON object.")
        folded = key.casefold()
        if folded in seen:
            raise ConfigurationError(
                f"{context} profile names {seen[folded]!r} and {key!r} differ only by case."
            )
        seen[folded] = key
        result[key] = profile
    return result


def _nonempty_string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{context} must be a nonempty string.")
    return value


def _validate_path(value: Any, *, context: str) -> None:
    if isinstance(value, str):
        _nonempty_string(value, context=context)
        return
    path = _require_fields(value, required={"path"}, optional={"relative_to"}, context=context)
    raw_path = _nonempty_string(path["path"], context=f"{context}.path")
    relative_to = path.get("relative_to")
    expanded = Path(raw_path).expanduser()
    is_absolute = expanded.is_absolute() or raw_path.startswith("~")
    if is_absolute:
        if relative_to is not None:
            raise ConfigurationError(
                f"{context}.relative_to must be omitted when path is absolute or begins with '~'."
            )
    elif relative_to not in ("cwd", "config"):
        raise ConfigurationError(
            f"{context}.relative_to must be 'cwd' or 'config' for a relative path."
        )


def _validate_api_key_spec(value: Any, *, context: str) -> str:
    spec = _nonempty_string(value, context=context)
    source, separator, argument = spec.partition("(")
    if separator != "(" or not spec.endswith(")"):
        raise ConfigurationError(
            f"{context} must use env(...), file(...), command(...), or literal(...)."
        )
    if source not in {"env", "file", "command", "literal"} or not argument[:-1].strip():
        raise ConfigurationError(
            f"{context} must use env(...), file(...), command(...), or literal(...)."
        )
    return spec


def _validate_weave(weave: dict[str, dict[str, Any]], *, path: Path) -> None:
    for name, profile in weave.items():
        context = f"Configuration {path} weave.{name}"
        _require_fields(
            profile,
            required=set(),
            optional={"provider", "model", "api_key", "prompt", "prompt_file"},
            context=context,
        )
        if "provider" in profile:
            _nonempty_string(profile["provider"], context=f"{context}.provider")
        if "model" in profile:
            _nonempty_string(profile["model"], context=f"{context}.model")
        if "api_key" in profile:
            _validate_api_key_spec(profile["api_key"], context=f"{context}.api_key")
        prompt_fields = {field for field in ("prompt", "prompt_file") if field in profile}
        if len(prompt_fields) != 1:
            raise ConfigurationError(
                f"{context} must contain exactly one of prompt or prompt_file."
            )
        if "prompt" in profile:
            _nonempty_string(profile["prompt"], context=f"{context}.prompt")
        else:
            _validate_path(profile["prompt_file"], context=f"{context}.prompt_file")


def _validate_destination_roots(value: Any, *, context: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{context} must be a JSON object.")
    roots: dict[str, str] = {}
    seen: dict[str, str] = {}
    for name, raw_path in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError(f"{context} names must be nonempty strings.")
        folded = name.casefold()
        if folded in seen:
            raise ConfigurationError(
                f"{context} names {seen[folded]!r} and {name!r} differ only by case."
            )
        seen[folded] = name
        relative = _nonempty_string(raw_path, context=f"{context}.{name}")
        candidate = Path(relative)
        if candidate.is_absolute() or PureWindowsPath(relative).is_absolute():
            raise ConfigurationError(
                f"{context}.{name} must be a relative path beneath the resolved vault."
            )
        depth = 0
        for part in candidate.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if depth == 0:
                    raise ConfigurationError(
                        f"{context}.{name} must not use '..' to escape the resolved vault."
                    )
                depth -= 1
            else:
                depth += 1
        roots[folded] = name
    return roots


def _validate_destinations(value: Any, *, context: str, destination_roots: dict[str, str]) -> None:
    if not isinstance(value, dict) or not value:
        raise ConfigurationError(f"{context} must be a nonempty JSON object.")
    seen: dict[str, str] = {}
    for name, destination in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError(f"{context} names must be nonempty strings.")
        folded = name.casefold()
        if folded in seen:
            raise ConfigurationError(
                f"{context} names {seen[folded]!r} and {name!r} differ only by case."
            )
        seen[folded] = name
        item_context = f"{context}.{name}"
        if not isinstance(destination, dict):
            raise ConfigurationError(f"{item_context} must be a JSON object.")
        operation = destination.get("operation")
        if operation in ("insert", "append"):
            fields = _require_fields(
                destination,
                required={"operation", "file", "format"},
                optional={"root"},
                context=item_context,
            )
            _nonempty_string(fields["file"], context=f"{item_context}.file")
        elif operation == "create":
            fields = _require_fields(
                destination,
                required={"operation", "directory", "filename", "format"},
                optional={"root"},
                context=item_context,
            )
            _nonempty_string(fields["directory"], context=f"{item_context}.directory")
            _nonempty_string(fields["filename"], context=f"{item_context}.filename")
        else:
            raise ConfigurationError(
                f"{item_context}.operation must be 'insert', 'append', or 'create'."
            )
        _nonempty_string(fields["format"], context=f"{item_context}.format")
        if "root" in fields:
            root_name = _nonempty_string(fields["root"], context=f"{item_context}.root")
            if root_name.casefold() not in destination_roots:
                available = ", ".join(sorted(destination_roots.values())) or "none configured"
                raise ConfigurationError(
                    f"{item_context}.root names unknown destination root {root_name!r}. "
                    f"Available destination roots: {available}."
                )


def _validate_out(out: dict[str, dict[str, Any]], *, path: Path) -> None:
    for name, profile in out.items():
        context = f"Configuration {path} out.{name}"
        fields = _require_fields(
            profile,
            required={"timezone", "vault", "packet_fields", "destinations"},
            optional={"destination_roots"},
            context=context,
        )
        _nonempty_string(fields["timezone"], context=f"{context}.timezone")
        _validate_path(fields["vault"], context=f"{context}.vault")
        packet_fields = _require_fields(
            fields["packet_fields"],
            required={"category", "content"},
            context=f"{context}.packet_fields",
        )
        _nonempty_string(packet_fields["category"], context=f"{context}.packet_fields.category")
        _nonempty_string(packet_fields["content"], context=f"{context}.packet_fields.content")
        roots = _validate_destination_roots(
            fields.get("destination_roots", {}),
            context=f"{context}.destination_roots",
        )
        _validate_destinations(
            fields["destinations"],
            context=f"{context}.destinations",
            destination_roots=roots,
        )


def validate_config(value: Any, *, path: Path) -> AppConfig:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration {path} must be a JSON object.")
    sanitized = _without_comments(value, context=f"Configuration {path}")
    schema = sanitized.get("schema_version")
    if schema != CONFIG_SCHEMA_VERSION or isinstance(schema, bool):
        if schema == 1 and not isinstance(schema, bool):
            raise ConfigurationError(
                f"Configuration {path} uses schema version 1, but this TRW release "
                f"requires configuration schema version {CONFIG_SCHEMA_VERSION}. Run "
                "'trwprep validate-config' to validate it and offer a supported update."
            )
        raise ConfigurationError(
            f"Configuration {path} schema_version must be {CONFIG_SCHEMA_VERSION}; "
            f"received {schema!r}. Run 'trwprep validate-config' for guidance."
        )
    root = _require_fields(
        sanitized,
        required=REQUIRED_TOP_LEVEL_FIELDS,
        context=f"Configuration {path} top-level object",
    )
    logging_value = _require_fields(
        root["logging"],
        required={"retained_runs"},
        context=f"Configuration {path} logging",
    )
    retained = logging_value["retained_runs"]
    if not isinstance(retained, int) or isinstance(retained, bool) or retained < 0:
        raise ConfigurationError(
            f"Configuration {path} logging.retained_runs must be a nonnegative integer; "
            f"received {retained!r}."
        )
    provider = _nonempty_string(root["provider"], context=f"Configuration {path} provider")
    model = _nonempty_string(root["model"], context=f"Configuration {path} model")
    api_key = _validate_api_key_spec(root["api_key"], context=f"Configuration {path} api_key")
    weave = _profiles(root["weave"], "weave", path=path)
    out = _profiles(root["out"], "out", path=path)
    _validate_weave(weave, path=path)
    _validate_out(out, path=path)
    return AppConfig(
        CONFIG_SCHEMA_VERSION,
        provider,
        model,
        api_key,
        LoggingConfig(retained),
        weave,
        out,
    )


def load_or_create_config(paths: ApplicationPaths) -> AppConfig:
    config_path = paths.config_file
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _create_packaged_defaults(config_path)
    try:
        config = validate_config(
            json.loads(config_path.read_text(encoding="utf-8")), path=config_path
        )
        if any(
            profile.get("prompt_file") == "prompts/example.md" for profile in config.weave.values()
        ):
            prompt_path = config_path.parent / "prompts/example.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            _create_file_if_absent(prompt_path, packaged_example_prompt_bytes())
        if any(
            profile.get("prompt_file") == "prompts/linkedin-profile.md"
            for profile in config.weave.values()
        ):
            prompt_path = config_path.parent / "prompts/linkedin-profile.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            _create_file_if_absent(prompt_path, packaged_linkedin_prompt_bytes())
        return config
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Could not read valid JSON configuration: {config_path}") from exc


def _create_packaged_defaults(config_path: Path) -> None:
    config_data = packaged_default_config_bytes()
    prompt_data = packaged_example_prompt_bytes()
    linkedin_prompt_data = packaged_linkedin_prompt_bytes()
    try:
        validate_config(json.loads(config_data.decode("utf-8")), path=config_path)
        prompt_data.decode("utf-8")
        linkedin_prompt_data.decode("utf-8")
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("Packaged default resources are invalid.") from exc
    files = (
        _ResourceFile(("prompts", "example.md"), config_path.parent / "prompts/example.md"),
        _ResourceFile(
            ("prompts", "linkedin-profile.md"),
            config_path.parent / "prompts/linkedin-profile.md",
        ),
        _ResourceFile(("default-config.json",), config_path),
    )
    for resource_file in files:
        data = _resource_bytes(*resource_file.resource_parts)
        resource_file.destination.parent.mkdir(parents=True, exist_ok=True)
        _create_file_if_absent(resource_file.destination, data)


def _create_file_if_absent(path: Path, data: bytes) -> None:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
        except OSError as exc:
            if not path.exists():
                raise ConfigurationError(f"Could not create file atomically: {path}") from exc
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()

"""Output-driver discovery and compatibility boundary."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol, cast

from transcript_weaver.config import AppConfig, ApplicationPaths, ConfigurationError
from transcript_weaver.out.core import OutputError, persist
from transcript_weaver.profiles import find_profile

OUTPUT_DRIVER_API_VERSION = 1
ENTRY_POINT_GROUP = "transcript_weaver.output_drivers"
OFFICIAL_DRIVER_PACKAGES = {"highlevel": "transcript-weaver-highlevel"}


@dataclass(frozen=True, slots=True)
class OutputResult:
    operation: str
    destination: str


class OutputDriver(Protocol):
    api_version: int

    def __call__(
        self,
        packet: Mapping[str, Any],
        profile: Mapping[str, Any],
        *,
        warning: Callable[[str], None],
    ) -> OutputResult: ...


def _entry_points() -> list[metadata.EntryPoint]:
    return list(metadata.entry_points(group=ENTRY_POINT_GROUP))


def _load_driver(name: str) -> OutputDriver:
    matches = [entry for entry in _entry_points() if entry.name.casefold() == name.casefold()]
    if not matches:
        package = OFFICIAL_DRIVER_PACKAGES.get(name.casefold())
        if package is not None:
            raise OutputError(
                f"Output driver {name!r} is not installed.\n"
                "Install the official plugin with:\n"
                f"  {sys.executable} -m pip install --user {package}"
            )
        raise OutputError(f"Output driver {name!r} is not installed.")
    if len(matches) != 1:
        distributions = ", ".join(sorted(entry.value for entry in matches))
        raise OutputError(
            f"Multiple installed plugins provide output driver {name!r}: {distributions}."
        )
    try:
        driver = matches[0].load()
    except Exception as exc:
        raise OutputError(f"Could not load output driver {name!r}: {type(exc).__name__}.") from exc
    api_version = getattr(driver, "api_version", None)
    if api_version != OUTPUT_DRIVER_API_VERSION:
        raise OutputError(
            f"Output driver {name!r} uses plugin API {api_version!r}; "
            f"this TRW release requires API {OUTPUT_DRIVER_API_VERSION}. "
            "Install matching TRW and plugin versions."
        )
    if not callable(driver):
        raise OutputError(f"Output driver {name!r} is not callable.")
    return cast(OutputDriver, driver)


def dispatch_output(
    packet: dict[str, Any],
    profile_argument: str,
    config: AppConfig,
    paths: ApplicationPaths,
    *,
    warn: Callable[[str], None],
) -> OutputResult:
    """Use a configured plugin driver or preserve the built-in file behavior."""
    try:
        profile_name, profile = find_profile(config.out, profile_argument, kind="output")
    except ConfigurationError as exc:
        raise OutputError(str(exc)) from exc
    driver_name = profile.get("driver")
    if driver_name is None:
        operation, target = persist(packet, profile_name, config, paths, warn=warn)
        return OutputResult(operation, str(target))
    if not isinstance(driver_name, str) or not driver_name.strip():
        raise OutputError(f"Output profile {profile_name!r} driver must be a nonempty string.")
    driver = _load_driver(driver_name)
    try:
        result = driver(packet, profile, warning=warn)
    except OutputError:
        raise
    except Exception as exc:
        raise OutputError(
            f"Output driver {driver_name!r} failed unexpectedly: {type(exc).__name__}."
        ) from exc
    if not isinstance(result, OutputResult):
        raise OutputError(
            f"Output driver {driver_name!r} returned an incompatible result. "
            "Install matching TRW and plugin versions."
        )
    return result

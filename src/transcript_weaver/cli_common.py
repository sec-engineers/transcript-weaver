"""Shared startup and shutdown behavior for all console commands."""

from __future__ import annotations

import argparse
import textwrap
from dataclasses import dataclass
from typing import TextIO

from transcript_weaver import __version__
from transcript_weaver.artifacts import (
    ArtifactPermissionError,
    permission_directory,
    read_permission,
)
from transcript_weaver.config import (
    AppConfig,
    ApplicationPaths,
    ConfigurationError,
    get_application_paths,
    load_or_create_config,
)
from transcript_weaver.models import SCHEMA_VERSION
from transcript_weaver.runtime import (
    DiagnosticError,
    LoggingOptions,
    StageLog,
    apply_log_retention,
)


@dataclass(slots=True)
class Invocation:
    stage: str
    run_id: str
    config: AppConfig
    paths: ApplicationPaths
    log: StageLog
    stderr: TextIO

    def warning(self, message: str) -> None:
        write_cli_message(self.stderr, message, prefix=f"{self.stage}: warning: ")
        self.log.warning(message)

    def close(self, *, success: bool) -> None:
        self.log.info("Stage completed successfully" if success else "Stage failed")
        self.log.close()


def write_cli_message(stream: TextIO, message: str, *, prefix: str = "") -> None:
    """Write ordinary CLI prose within 72 columns without splitting paths."""
    lines = message.splitlines() or [""]
    for index, line in enumerate(lines):
        initial = prefix if index == 0 else ""
        rendered = textwrap.fill(
            line,
            width=72,
            initial_indent=initial,
            break_long_words=False,
            break_on_hyphens=False,
        )
        stream.write(rendered + "\n")


def write_cli_error(stream: TextIO, stage: str, error: object) -> None:
    write_cli_message(stream, str(error), prefix=f"{stage}: ")


def add_logging_arguments(
    parser: argparse.ArgumentParser, *, suppress_defaults: bool = False
) -> None:
    default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument(
        "--log",
        action="store_true",
        default=default,
        help="write a persistent diagnostic log in the per-user log directory",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=default,
        help="write a more detailed persistent log (implies --log)",
    )
    parser.add_argument(
        "--debug-artifacts",
        action="store_true",
        default=default,
        help=(
            "capture potentially sensitive diagnostics after 'trwprep artifacts enable'; "
            "inspect before sharing (implies --verbose and --log)"
        ),
    )


class _VersionAction(argparse.Action):
    def __init__(self, option_strings: list[str], dest: str, **kwargs: object) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)  # type: ignore[arg-type]

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del namespace, values, option_string
        print(f"{parser.prog} {__version__}\nSchema currently used: {SCHEMA_VERSION}")
        parser.exit(0)


def add_version_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--version",
        action=_VersionAction,
        help="show the command version and currently used schema version, then exit",
    )


def logging_options(args: argparse.Namespace) -> LoggingOptions:
    return LoggingOptions(
        log=bool(args.log or args.verbose or args.debug_artifacts),
        verbose=bool(args.verbose or args.debug_artifacts),
        debug_artifacts=bool(args.debug_artifacts),
    )


def start_invocation(
    *,
    stage: str,
    run_id: str,
    args: argparse.Namespace,
    stderr: TextIO,
    paths: ApplicationPaths | None = None,
    config: AppConfig | None = None,
) -> Invocation:
    effective_paths = paths or get_application_paths()
    effective_config = config or load_or_create_config(effective_paths)
    options = logging_options(args)
    if options.debug_artifacts:
        runtime_directory = permission_directory(
            effective_paths.runtime_directory, effective_paths.log_directory
        )
        try:
            permission = read_permission(runtime_directory)
        except ArtifactPermissionError as exc:
            raise ConfigurationError(str(exc)) from exc
        if permission is None:
            raise ConfigurationError(
                "--debug-artifacts requires temporary permission.\nRun "
                "'trwprep artifacts enable' and review the security warning first."
            )
    try:
        stage_log = StageLog(
            run_id=run_id,
            stage=stage,
            options=options,
            log_directory=effective_paths.log_directory,
        )
    except DiagnosticError as exc:
        print(f"{stage}: warning: {exc}; continuing without a persistent log", file=stderr)
        stage_log = StageLog(
            run_id=run_id,
            stage=stage,
            options=LoggingOptions(),
            log_directory=effective_paths.log_directory,
        )
    invocation = Invocation(
        stage=stage,
        run_id=run_id,
        config=effective_config,
        paths=effective_paths,
        log=stage_log,
        stderr=stderr,
    )
    stage_log.info("Stage started")
    apply_log_retention(
        effective_paths.log_directory,
        effective_config.logging.retained_runs,
        current_run_id=run_id,
        warn=invocation.warning,
    )
    return invocation

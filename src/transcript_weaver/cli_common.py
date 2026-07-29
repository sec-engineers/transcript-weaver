"""Shared startup and shutdown behavior for all console commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TextIO

from transcript_weaver.config import (
    AppConfig,
    ApplicationPaths,
    get_application_paths,
    load_or_create_config,
)
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
        print(f"{self.stage}: warning: {message}", file=self.stderr)
        self.log.warning(message)

    def close(self, *, success: bool) -> None:
        self.log.info("Stage completed successfully" if success else "Stage failed")
        self.log.close()


def add_logging_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log",
        action="store_true",
        help="write a persistent diagnostic log in the per-user log directory",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="write a more detailed persistent log (implies --log)",
    )
    parser.add_argument(
        "--debug-artifacts",
        action="store_true",
        help=(
            "capture potentially sensitive HTML and screenshots; inspect before sharing "
            "(implies --verbose and --log)"
        ),
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
    if options.debug_artifacts:
        invocation.warning(
            "debug artifacts may contain transcripts, account details, email addresses, "
            "and private page contents; inspect them before sharing"
        )
    return invocation

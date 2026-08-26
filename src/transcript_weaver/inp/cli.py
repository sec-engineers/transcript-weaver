"""Command-line interface for ``trwinp``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from transcript_weaver.cli_common import (
    add_logging_arguments,
    add_version_argument,
    start_invocation,
)
from transcript_weaver.config import ApplicationPaths, ConfigurationError
from transcript_weaver.inp.dom import DomSource
from transcript_weaver.inp.errors import ExitStatus, InputError
from transcript_weaver.inp.otter import OtterSource
from transcript_weaver.inp.sources import FileSource, StdinSource
from transcript_weaver.models import ModelError, TranscriptPacket
from transcript_weaver.runtime import RunIdError, generate_run_id


def _add_stage_logging(parser: argparse.ArgumentParser) -> None:
    add_logging_arguments(parser, suppress_defaults=True)


class _ModeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        if message == "the following arguments are required: mode":
            modes = next(
                (
                    action.choices
                    for action in self._actions
                    if isinstance(action, argparse._SubParsersAction)
                ),
                {},
            )
            self.print_usage(sys.stderr)
            self.exit(
                2,
                f"{self.prog}: error: {message}\nValid modes: {', '.join(modes)}\n",
            )
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ModeArgumentParser(
        prog="trwinp",
        description="Acquire a transcript and emit a normalized JSON packet.",
    )
    add_logging_arguments(parser)
    add_version_argument(parser)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    stdin_parser = subparsers.add_parser(
        "stdin", help="read UTF-8 transcript text from standard input"
    )
    _add_stage_logging(stdin_parser)
    file_parser = subparsers.add_parser("file", help="read a UTF-8 text file")
    file_parser.add_argument("path", type=Path, help="path to a UTF-8 text file")
    _add_stage_logging(file_parser)
    dom_parser = subparsers.add_parser(
        "dom", help="capture the current DOM from the prepared TRW Chrome browser"
    )
    _add_stage_logging(dom_parser)
    otter_parser = subparsers.add_parser("otter", help="acquire the newest visible Otter recording")
    _add_stage_logging(otter_parser)
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    paths: ApplicationPaths | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    run_id = generate_run_id()
    invocation = None
    try:
        invocation = start_invocation(
            stage="trwinp", run_id=run_id, args=args, stderr=stderr, paths=paths
        )
        if args.mode == "stdin":
            invocation.log.info("Acquiring transcript from standard input")
            acquired = StdinSource(stdin).acquire()
        elif args.mode == "file":
            invocation.log.info("Acquiring transcript from UTF-8 text file")
            acquired = FileSource(args.path).acquire()
        elif args.mode == "dom":
            invocation.log.info("Capturing current DOM from prepared Chrome browser")
            acquired = DomSource().acquire()
        else:
            invocation.log.info("Starting Otter acquisition")
            acquired = OtterSource(
                stage_log=invocation.log,
                debug_artifacts=args.debug_artifacts,
                log_directory=invocation.paths.log_directory,
                run_id=run_id,
                warning=invocation.warning,
            ).acquire()
        stdout.write(TranscriptPacket.from_acquired(acquired, run_id=run_id).to_json())
        invocation.close(success=True)
        return int(ExitStatus.OK)
    except (InputError, ModelError, ConfigurationError, RunIdError) as exc:
        if invocation is not None:
            invocation.log.exception(type(exc).__name__)
            invocation.close(success=False)
        print(f"trwinp: {exc}", file=stderr)
        return int(getattr(exc, "status", ExitStatus.GENERAL_ERROR))
    except KeyboardInterrupt:
        if invocation is not None:
            invocation.close(success=False)
        print("trwinp: interrupted", file=stderr)
        return int(ExitStatus.GENERAL_ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)

"""Command-line preparation utility for interactive TRW dependencies."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from transcript_weaver.cli_common import add_version_argument
from transcript_weaver.inp.errors import SourceUnavailableError
from transcript_weaver.prep.core import prepare_browser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trwprep",
        description="Prepare long-lived external dependencies used by Transcript Weaver.",
    )
    add_version_argument(parser)
    subparsers = parser.add_subparsers(dest="target", required=True)
    subparsers.add_parser("dom", help="prepare the dedicated Chrome browser for DOM capture")
    subparsers.add_parser("otter", help="prepare the dedicated authenticated Otter browser")
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        prepare_browser(args.target, stdin=stdin, stdout=stdout)
        return 0
    except SourceUnavailableError as exc:
        print(f"trwprep: {exc}", file=stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)

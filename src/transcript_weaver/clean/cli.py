"""Safe placeholder for ``trwclean`` with shared startup diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from transcript_weaver.cli_common import add_logging_arguments, start_invocation
from transcript_weaver.config import (
    ApplicationPaths,
    ConfigurationError,
    get_application_paths,
    load_or_create_config,
)
from transcript_weaver.runtime import RunIdError, ensure_packet_run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trwclean",
        description="Future LLM transcript-cleaning stage (not implemented yet).",
    )
    parser.add_argument("master_prompt_file", nargs="?")
    add_logging_arguments(parser)
    return parser


def _read_optional_packet(stdin: TextIO) -> dict[str, Any]:
    try:
        if stdin.isatty():
            return {}
    except (AttributeError, OSError):
        return {}
    text = stdin.read()
    if not text.strip():
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Input packet must be a JSON object.")
    return value


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    paths: ApplicationPaths | None = None,
) -> int:
    del stdout
    args = build_parser().parse_args(argv)
    invocation = None
    try:
        effective_paths = paths or get_application_paths()
        config = load_or_create_config(effective_paths)
        packet = _read_optional_packet(stdin)
        run_id = ensure_packet_run_id(packet)
        invocation = start_invocation(
            stage="trwclean",
            run_id=run_id,
            args=args,
            stderr=stderr,
            paths=effective_paths,
            config=config,
        )
        invocation.log.info("Placeholder invoked; no packet was emitted")
        print("trwclean: not implemented in milestone 1.", file=stderr)
        invocation.close(success=False)
        return 1
    except (ConfigurationError, RunIdError, ValueError, json.JSONDecodeError) as exc:
        if invocation is not None:
            invocation.log.exception(type(exc).__name__)
            invocation.close(success=False)
        print(f"trwclean: {exc}", file=stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)

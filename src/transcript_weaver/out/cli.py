"""Command-line deterministic output stage."""

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
from transcript_weaver.out.core import OutputError, persist
from transcript_weaver.runtime import RunIdError, ensure_packet_run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trwout", description="Persist an enriched packet using a configured output profile."
    )
    parser.add_argument("output_profile")
    add_logging_arguments(parser)
    return parser


def _read_packet(stdin: TextIO) -> dict[str, Any]:
    text = stdin.read()
    if not text.strip():
        raise ValueError("Standard input did not contain a JSON packet.")
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
        packet = _read_packet(stdin)
        run_id = ensure_packet_run_id(packet)
        invocation = start_invocation(
            stage="trwout",
            run_id=run_id,
            args=args,
            stderr=stderr,
            paths=effective_paths,
            config=config,
        )
        operation, target = persist(
            packet, args.output_profile, config, effective_paths, warn=invocation.warning
        )
        invocation.log.info(
            f"Output completed profile={args.output_profile!r} operation={operation} "
            f"destination={target.name!r}"
        )
        invocation.close(success=True)
        return 0
    except (ConfigurationError, RunIdError, ValueError, json.JSONDecodeError, OutputError) as exc:
        if invocation is not None:
            invocation.log.exception(type(exc).__name__)
            invocation.close(success=False)
        print(f"trwout: {exc}", file=stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)

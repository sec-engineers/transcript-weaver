"""Command-line transcript transformation stage."""

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
from transcript_weaver.profiles import available_profiles
from transcript_weaver.runtime import (
    DiagnosticError,
    RunIdError,
    apply_log_retention,
    ensure_packet_run_id,
    write_preservation_artifacts,
)
from transcript_weaver.weave.core import PreservationError, WeaveError, transform
from transcript_weaver.weave.provider import Provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trweave",
        description="Enrich a transcript packet with a configured transformation prompt.",
    )
    parser.add_argument(
        "prompt_or_profile", nargs="?", help="prompt file or configured weave profile"
    )
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
    provider: Provider | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    invocation = None
    try:
        effective_paths = paths or get_application_paths()
        config = load_or_create_config(effective_paths)
        if args.prompt_or_profile is None:
            raise ConfigurationError(
                "No weave profile or prompt file was provided. "
                f"Available profiles: {available_profiles(config.weave)}."
            )
        packet = _read_packet(stdin)
        run_id = ensure_packet_run_id(packet)
        invocation = start_invocation(
            stage="trweave",
            run_id=run_id,
            args=args,
            stderr=stderr,
            paths=effective_paths,
            config=config,
        )
        enriched, selected, model = transform(
            packet,
            args.prompt_or_profile,
            config,
            effective_paths,
            provider=provider,
            retry_reporter=invocation.warning,
        )
        invocation.log.info(
            f"Transformation completed profile={selected!r} provider='gemini' model={model!r}"
        )
        stdout.write(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n")
        invocation.close(success=True)
        return 0
    except PreservationError as exc:
        if invocation is not None:
            failure_directory = invocation.paths.log_directory / "packet-failures"
            try:
                original_path, provider_path = write_preservation_artifacts(
                    invocation.paths.log_directory,
                    invocation.run_id,
                    original=exc.original,
                    provider_output=exc.provider_output,
                )
                invocation.warning(
                    "saved sensitive packet-preservation diagnostics to "
                    f"{original_path} and {provider_path}; inspect before sharing"
                )
                apply_log_retention(
                    failure_directory,
                    invocation.config.logging.retained_runs,
                    current_run_id=invocation.run_id,
                    warn=invocation.warning,
                )
            except (DiagnosticError, OSError, TypeError, ValueError) as artifact_error:
                invocation.warning(
                    f"could not save packet-preservation diagnostics: {artifact_error}"
                )
            invocation.log.exception(type(exc).__name__)
            invocation.close(success=False)
        print(f"trweave: {exc}", file=stderr)
        return 1
    except (
        ConfigurationError,
        RunIdError,
        ValueError,
        json.JSONDecodeError,
        WeaveError,
    ) as exc:
        if invocation is not None:
            invocation.log.exception(type(exc).__name__)
            invocation.close(success=False)
        print(f"trweave: {exc}", file=stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)

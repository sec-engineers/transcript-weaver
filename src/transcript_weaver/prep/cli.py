"""Command-line preparation utility for interactive TRW dependencies."""

from __future__ import annotations

import argparse
import math
import sys
import textwrap
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TextIO

from transcript_weaver.artifacts import (
    ArtifactPermissionError,
    disable_permission,
    enable_permission,
    permission_directory,
    permission_path,
    read_permission,
)
from transcript_weaver.cli_common import add_version_argument, write_cli_error
from transcript_weaver.config import ApplicationPaths, ConfigurationError, get_application_paths
from transcript_weaver.inp.errors import SourceUnavailableError
from transcript_weaver.prep.configuration import validate_or_offer_migration
from transcript_weaver.prep.core import confirm, prepare_browser


class _HelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, width=72)


def _write_wrapped(stdout: TextIO, message: str) -> None:
    stdout.write(textwrap.fill(message, width=72, break_on_hyphens=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trwprep",
        description="Prepare long-lived external dependencies used by Transcript Weaver.",
        epilog="Artifact actions: trwprep artifacts {enable,status,disable}",
        formatter_class=_HelpFormatter,
    )
    add_version_argument(parser)
    subparsers = parser.add_subparsers(dest="target", required=True)
    subparsers.add_parser("dom", help="prepare the dedicated Chrome browser for DOM capture")
    subparsers.add_parser("otter", help="prepare the dedicated authenticated Otter browser")
    subparsers.add_parser(
        "validate-config",
        help="validate configuration and offer a supported schema update",
    )
    artifacts = subparsers.add_parser(
        "artifacts",
        help="manage permission; requires enable, status, or disable",
        formatter_class=_HelpFormatter,
    )
    artifact_actions = artifacts.add_subparsers(dest="action", required=True)
    artifact_actions.add_parser("enable", help="permit requested debug artifacts for one hour")
    artifact_actions.add_parser("status", help="show the current artifact permission status")
    artifact_actions.add_parser("disable", help="revoke artifact permission immediately")
    return parser


def _manage_artifacts(
    action: str, *, paths: ApplicationPaths, stdin: TextIO, stdout: TextIO
) -> None:
    runtime_directory = permission_directory(paths.runtime_directory, paths.log_directory)
    if action == "enable":
        current_permission = read_permission(runtime_directory)
        if current_permission is not None:
            permission = enable_permission(runtime_directory)
            _write_wrapped(stdout, "Sensitive debug artifact permission extended for one hour.")
            stdout.write(f"Expires: {permission.expires_at:%Y-%m-%d %H:%M:%S} UTC\n")
            stdout.write(f"Permission record:\n  {permission_path(runtime_directory)}\n")
            return
        _write_wrapped(
            stdout,
            "WARNING: Debug artifacts may contain the complete input transcript or DOM, "
            "raw LLM responses, account details, email addresses, and other private "
            "information. Inspect artifacts before sharing them.",
        )
        if not confirm(
            "Permit --debug-artifacts for one hour?",
            stdin=stdin,
            stdout=stdout,
        ):
            stdout.write("Artifact permission was not enabled.\n")
            return
        permission = enable_permission(runtime_directory)
        _write_wrapped(stdout, "Sensitive debug artifact permission enabled for one hour.")
        stdout.write(f"Expires: {permission.expires_at:%Y-%m-%d %H:%M:%S} UTC\n")
        _write_wrapped(
            stdout,
            "Artifacts are created only by commands that also specify --debug-artifacts.",
        )
        stdout.write(f"Permission record:\n  {permission_path(runtime_directory)}\n")
        return
    if action == "disable":
        removed = disable_permission(runtime_directory)
        stdout.write(
            "Sensitive debug artifact permission disabled.\n"
            if removed
            else "Sensitive debug artifact permission was already disabled.\n"
        )
        return
    current_permission = read_permission(runtime_directory)
    if current_permission is None:
        stdout.write("Sensitive debug artifact permission is disabled or expired.\n")
        return
    remaining = current_permission.expires_at - datetime.now(timezone.utc)
    minutes = max(0, math.ceil(remaining.total_seconds() / 60))
    stdout.write("Sensitive debug artifact permission is enabled.\n")
    stdout.write(
        f"Expires: {current_permission.expires_at:%Y-%m-%d %H:%M:%S} UTC "
        f"({minutes} minute{'s' if minutes != 1 else ''} remaining).\n"
    )
    stdout.write(f"Permission record:\n  {permission_path(runtime_directory)}\n")


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    paths: ApplicationPaths | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.target == "artifacts":
            _manage_artifacts(
                args.action,
                paths=paths or get_application_paths(),
                stdin=stdin,
                stdout=stdout,
            )
        elif args.target == "validate-config":
            validate_or_offer_migration(
                paths or get_application_paths(),
                stdin=stdin,
                stdout=stdout,
            )
        else:
            prepare_browser(args.target, stdin=stdin, stdout=stdout)
        return 0
    except (ArtifactPermissionError, ConfigurationError, SourceUnavailableError) as exc:
        write_cli_error(stderr, "trwprep", exc)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)

"""Non-mutating distribution build for the version recorded in source."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

VERSION_RE = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d{4})"\n$', re.MULTILINE)
LOCK_NAME = ".transcript-weaver-build.lock"


class BuildVersionError(RuntimeError):
    """Raised when a distribution build cannot use the recorded version safely."""


def _read_version(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildVersionError(f"Could not read authoritative version file: {path}") from exc
    match = VERSION_RE.search(content)
    if match is None:
        raise BuildVersionError(
            "Authoritative version must have the form major.minor.build with a "
            "four-digit build number."
        )
    return ".".join(match.groups())


def run_release_build(project_root: Path, *, command: Sequence[str] | None = None) -> str:
    """Build coordinated distributions without changing the recorded version."""
    root = project_root.resolve()
    version_path = root / "src" / "transcript_weaver" / "_version.py"
    lock_path = root / LOCK_NAME
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BuildVersionError(
            f"Another distribution build is active (lock exists: {lock_path})."
        ) from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
    finally:
        os.close(descriptor)

    try:
        version = _read_version(version_path)
        if command is not None:
            builds = [(root, list(command))]
        else:
            projects = [root, *sorted((root / "plugins").glob("*/pyproject.toml"))]
            project_roots = [
                item.parent if item.name == "pyproject.toml" else item for item in projects
            ]
            builds = [
                (
                    project,
                    [
                        sys.executable,
                        "-m",
                        "build",
                        "--outdir",
                        str(root / "dist"),
                        str(project),
                    ],
                )
                for project in project_roots
            ]
        for project, build_command in builds:
            result = subprocess.run(build_command, cwd=root, check=False)
            if result.returncode != 0:
                label = project.relative_to(root) if project != root else Path(".")
                raise BuildVersionError(
                    f"Distribution build for {label} failed with exit status {result.returncode}."
                )
        return version
    finally:
        with suppress(FileNotFoundError):
            lock_path.unlink()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        version = run_release_build(_project_root())
    except (BuildVersionError, OSError) as exc:
        print(f"transcript-weaver build: {exc}", file=sys.stderr)
        return 1
    print(f"Built Transcript Weaver {version}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

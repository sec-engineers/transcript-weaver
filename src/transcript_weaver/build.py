"""Intentional distribution build with one atomic build-number increment."""

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
    """Raised when a release build cannot update its version safely."""


def _read_version(path: Path) -> tuple[str, re.Match[str]]:
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
    return content, match


def _next_content(content: str, match: re.Match[str]) -> tuple[str, str]:
    major, minor, build_text = match.groups()
    build = int(build_text)
    if build >= 9999:
        raise BuildVersionError("Build number overflow: increment major or minor first.")
    version = f"{major}.{minor}.{build + 1:04d}"
    updated = content[: match.start(1)] + version + content[match.end(3) :]
    return updated, version


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def run_release_build(project_root: Path, *, command: Sequence[str] | None = None) -> str:
    """Increment once, build distributions, and roll back the source version on failure."""
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

    original = ""
    changed = False
    try:
        original, match = _read_version(version_path)
        updated, version = _next_content(original, match)
        _atomic_write(version_path, updated)
        changed = True
        build_command = list(command or (sys.executable, "-m", "build"))
        result = subprocess.run(build_command, cwd=root, check=False)
        if result.returncode != 0:
            raise BuildVersionError(
                f"Distribution build failed with exit status {result.returncode}."
            )
        return version
    except BaseException:
        if changed:
            _atomic_write(version_path, original)
        raise
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

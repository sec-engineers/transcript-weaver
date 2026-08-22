import sys
from pathlib import Path

import pytest

from transcript_weaver.build import LOCK_NAME, BuildVersionError, run_release_build


def project(tmp_path: Path, version: str = "1.0.0000") -> tuple[Path, Path]:
    root = tmp_path / "project"
    version_path = root / "src" / "transcript_weaver" / "_version.py"
    version_path.parent.mkdir(parents=True)
    version_path.write_text(
        f'"""Authoritative Transcript Weaver project version."""\n\n__version__ = "{version}"\n'
    )
    return root, version_path


def test_successful_and_repeated_builds_preserve_version(tmp_path: Path) -> None:
    root, version_path = project(tmp_path)
    original = version_path.read_text()
    command = [sys.executable, "-c", "raise SystemExit(0)"]
    for _ in range(2):
        assert run_release_build(root, command=command) == "1.0.0000"
        assert version_path.read_text() == original
        assert not (root / LOCK_NAME).exists()


def test_failed_build_preserves_version(tmp_path: Path) -> None:
    root, version_path = project(tmp_path)
    original = version_path.read_text()
    with pytest.raises(BuildVersionError, match="exit status 7"):
        run_release_build(root, command=[sys.executable, "-c", "raise SystemExit(7)"])
    assert version_path.read_text() == original
    assert not (root / LOCK_NAME).exists()


def test_malformed_version_fails_without_change(tmp_path: Path) -> None:
    root, version_path = project(tmp_path, "1.0.1")
    original = version_path.read_text()
    with pytest.raises(BuildVersionError, match="four-digit"):
        run_release_build(root, command=[sys.executable, "-c", "raise SystemExit(0)"])
    assert version_path.read_text() == original


def test_concurrent_build_fails_clearly(tmp_path: Path) -> None:
    root, version_path = project(tmp_path)
    (root / LOCK_NAME).write_text("pid=other\n")
    with pytest.raises(BuildVersionError, match="Another distribution build"):
        run_release_build(root, command=[sys.executable, "-c", "raise SystemExit(0)"])
    assert '__version__ = "1.0.0000"' in version_path.read_text()

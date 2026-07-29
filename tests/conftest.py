from pathlib import Path

import pytest

from transcript_weaver.config import ApplicationPaths


@pytest.fixture
def app_paths(tmp_path: Path) -> ApplicationPaths:
    return ApplicationPaths(
        config_file=tmp_path / "config" / "config.json",
        log_directory=tmp_path / "state" / "log",
    )

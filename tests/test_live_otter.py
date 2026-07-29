import io
import os
from pathlib import Path

import pytest

from transcript_weaver.config import ApplicationPaths
from transcript_weaver.inp import cli

pytestmark = [
    pytest.mark.live_otter,
    pytest.mark.skipif(
        os.environ.get("TRANSCRIPT_WEAVER_LIVE_OTTER") != "1",
        reason="set TRANSCRIPT_WEAVER_LIVE_OTTER=1 to access live Otter",
    ),
]


def test_live_newest_otter_recording_can_be_acquired(tmp_path: Path) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    paths = ApplicationPaths(tmp_path / "config.json", tmp_path / "log")
    status = cli.run(["otter"], stdout=stdout, stderr=stderr, paths=paths)
    assert status == 0
    packet = __import__("json").loads(stdout.getvalue())
    assert packet["transcript"].strip()
    assert packet["datetime"].endswith("Z")
    assert packet["run"]["id"]
    assert packet["source"]["type"] == "otter"
    assert packet["source"]["reference"].startswith("https://otter.ai/")
    assert stderr.getvalue() == ""

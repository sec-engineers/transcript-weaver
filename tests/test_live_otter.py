import io
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from transcript_weaver.config import ApplicationPaths
from transcript_weaver.inp import cli
from transcript_weaver.inp.otter import _windows_host_ip

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
    cdp_url = os.environ.get("TRANSCRIPT_WEAVER_OTTER_CDP_URL", f"http://{_windows_host_ip()}:9223")
    with pytest.raises((OSError, urllib.error.URLError)):
        urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1)

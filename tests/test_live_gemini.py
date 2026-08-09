import json
import os

import pytest

from transcript_weaver import __version__
from transcript_weaver.weave.core import SYSTEM_INSTRUCTION, validate_response
from transcript_weaver.weave.provider import GeminiProvider


@pytest.mark.live_gemini
def test_live_gemini_small_safe_transformation() -> None:
    if os.environ.get("TRANSCRIPT_WEAVER_LIVE_GEMINI") != "1":
        pytest.skip("set TRANSCRIPT_WEAVER_LIVE_GEMINI=1 to enable live Gemini access")
    packet = {
        "schema_version": 1,
        "trw_version": __version__,
        "run": {"id": "20260805-120000-a1b2"},
        "datetime": "2026-08-05T12:00:00Z",
        "source": {"type": "test"},
        "transcript": "I am grateful for a sunny day.",
        "metadata": {},
    }
    provider = GeminiProvider("gemini-2.5-flash-lite", "api/gemini")
    response = provider.transform(
        SYSTEM_INSTRUCTION,
        "Add a top-level weave object with type='gratitude' and a short content "
        "Markdown bullet. Never put weave inside metadata.",
        json.dumps(packet),
    )
    assert validate_response(response, packet)["weave"]["type"] == "gratitude"

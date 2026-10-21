import io
import json
import sys
from pathlib import Path

import pytest

from transcript_weaver.config import ApplicationPaths, validate_config
from transcript_weaver.out import cli as out_cli
from transcript_weaver.out.core import OutputError
from transcript_weaver.out.plugins import (
    OUTPUT_DRIVER_API_VERSION,
    OutputResult,
    dispatch_output,
)


def plugin_config() -> dict[str, object]:
    return {
        "schema_version": 2,
        "provider": "gemini",
        "model": "model",
        "api_key": "env(GEMINI_KEY)",
        "logging": {"retained_runs": 0},
        "weave": {},
        "out": {
            "crm": {
                "driver": "highlevel",
                "location_id": "env(HIGHLEVEL_LOCATION_ID)",
                "token": "env(HIGHLEVEL_TOKEN)",
                "source_path": "weave.linkedin",
                "identity": ["email"],
                "fields": {"email": {"target": "email"}},
            }
        },
    }


def packet() -> dict[str, object]:
    return {
        "schema_version": 1,
        "run": {"id": "20261021-120000-abcd"},
        "datetime": "2026-10-21T12:00:00Z",
        "source": {"type": "dom"},
        "transcript": "private",
        "weave": {"linkedin": {"email": "person@example.com"}},
    }


def test_plugin_profile_is_core_validated_without_loading_plugin(tmp_path: Path) -> None:
    config = validate_config(plugin_config(), path=tmp_path / "config.json")
    assert config.out["crm"]["driver"] == "highlevel"


def test_missing_official_plugin_names_exact_install_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transcript_weaver.out import plugins

    monkeypatch.setattr(plugins, "_entry_points", lambda: [])
    config = validate_config(plugin_config(), path=tmp_path / "config.json")
    paths = ApplicationPaths(tmp_path / "config.json", tmp_path / "logs")

    with pytest.raises(OutputError) as caught:
        dispatch_output(packet(), "crm", config, paths, warn=lambda _: None)

    message = str(caught.value)
    assert "Output driver 'highlevel' is not installed" in message
    assert f"{sys.executable} -m pip install --user transcript-weaver-highlevel" in message


def test_plugin_dispatch_and_cli_keep_standard_output_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transcript_weaver.out import plugins

    class Driver:
        api_version = OUTPUT_DRIVER_API_VERSION

        def __call__(self, value, profile, *, warning):
            assert value["weave"]["linkedin"]["email"] == "person@example.com"
            assert profile["driver"] == "highlevel"
            return OutputResult("created", "HighLevel contact test-id")

    class EntryPoint:
        name = "highlevel"
        value = "test:driver"

        @staticmethod
        def load():
            return Driver()

    monkeypatch.setattr(plugins, "_entry_points", lambda: [EntryPoint()])
    value = plugin_config()
    paths = ApplicationPaths(tmp_path / "config.json", tmp_path / "logs")
    paths.config_file.write_text(json.dumps(value))
    stdout, stderr = io.StringIO(), io.StringIO()

    assert (
        out_cli.run(
            ["crm"],
            stdin=io.StringIO(json.dumps(packet())),
            stdout=stdout,
            stderr=stderr,
            paths=paths,
        )
        == 0
    )
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_incompatible_plugin_api_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transcript_weaver.out import plugins

    class EntryPoint:
        name = "highlevel"
        value = "old:driver"

        @staticmethod
        def load():
            return type("OldDriver", (), {"api_version": 0, "__call__": lambda *a: None})()

    monkeypatch.setattr(plugins, "_entry_points", lambda: [EntryPoint()])
    config = validate_config(plugin_config(), path=tmp_path / "config.json")
    paths = ApplicationPaths(tmp_path / "config.json", tmp_path / "logs")

    with pytest.raises(OutputError, match="requires API"):
        dispatch_output(packet(), "crm", config, paths, warn=lambda _: None)

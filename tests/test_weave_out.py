import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from transcript_weaver.config import (
    ApplicationPaths,
    ConfigurationError,
    load_or_create_config,
    validate_config,
)
from transcript_weaver.out import cli as out_cli
from transcript_weaver.out.core import insert_chronologically, persist
from transcript_weaver.profiles import extract_dotted, find_profile, resolve_configured_path
from transcript_weaver.weave import cli as weave_cli
from transcript_weaver.weave.core import WeaveError, resolve_prompt, validate_response
from transcript_weaver.weave.provider import GeminiProvider, ProviderError, build_provider

RUN = "20260805-120000-a1b2"


class FakeProvider:
    model = "fake-gemini"

    def __init__(self, category: str = "gratitude", content: str = "- Thankful") -> None:
        self.category, self.content = category, content
        self.calls: list[tuple[str, str, str]] = []

    def transform(self, system: str, prompt: str, packet_json: str) -> str:
        self.calls.append((system, prompt, packet_json))
        packet = json.loads(packet_json)
        packet["weave"] = {"type": self.category, "content": self.content}
        return json.dumps(packet)


def base_config(vault: str = "vault") -> dict[str, Any]:
    destinations = {
        name: {"operation": "insert", "file": file, "format": "## {date}\n\n{content}\n\n"}
        for name, file in {
            "gratitude": "Gratitude Journal.md",
            "dream": "Dream Journal.md",
            "dss": "DSS Chronicles.md",
            "sacred": "Sacred Journey Journal.md",
        }.items()
    }
    destinations["unknown"] = {
        "operation": "create",
        "directory": "00 Inbox",
        "filename": "{date}-{time}-unknown.md",
        "format": "{content}\n",
    }
    return {
        "schema_version": 1,
        "logging": {"retained_runs": 5},
        "providers": {
            "Gemini": {
                "model": "gemini-2.5-flash-lite",
                "credential": {"source": "pass", "name": "api/gemini"},
            }
        },
        "weave": {"Cleanup": {"provider": "gemini", "prompt": "Clean safely"}},
        "out": {
            "Journals": {
                "timezone": "America/Los_Angeles",
                "vault": vault,
                "packet_fields": {"category": "weave.type", "content": "weave.content"},
                "destinations": destinations,
            }
        },
    }


def paths_with_config(tmp_path: Path, value: dict[str, Any] | None = None) -> ApplicationPaths:
    paths = ApplicationPaths(tmp_path / "config" / "config.json", tmp_path / "logs")
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text(json.dumps(value or base_config()))
    return paths


def packet(dt: str = "2026-08-05T08:30:00Z") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run": {"id": RUN},
        "datetime": dt,
        "source": {"type": "otter", "name": "Note"},
        "transcript": "PRIVATE",
        "metadata": {"nested": [1, {"x": True}]},
    }


def test_casefold_duplicates_and_lookup(tmp_path: Path) -> None:
    value = base_config()
    value["weave"]["cleanup"] = value["weave"]["Cleanup"]
    with pytest.raises(ConfigurationError, match="differ only by case"):
        validate_config(value, path=tmp_path / "c")
    assert find_profile({"Hello": 1}, "hello", kind="x") == ("Hello", 1)
    with pytest.raises(ConfigurationError, match="Did you mean"):
        find_profile({"transcript-cleanup": {}}, "transcript-cleanu", kind="weave")
    with pytest.raises(
        ConfigurationError,
        match=r"Unknown weave profile .wildly-wrong..*Available profiles: Cleanup",
    ):
        find_profile({"Cleanup": {}}, "wildly-wrong", kind="weave")


def test_missing_profile_lists_configured_choices(tmp_path: Path) -> None:
    paths = paths_with_config(tmp_path)
    weave_stderr = io.StringIO()
    assert weave_cli.run([], stderr=weave_stderr, paths=paths) == 1
    assert "No weave profile or prompt file was provided" in weave_stderr.getvalue()
    assert "Available profiles: Cleanup" in weave_stderr.getvalue()

    out_stderr = io.StringIO()
    assert out_cli.run([], stderr=out_stderr, paths=paths) == 1
    assert "No output profile was provided" in out_stderr.getvalue()
    assert "Available profiles: Journals" in out_stderr.getvalue()


def test_path_forms_and_dotted_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "cfg" / "config.json"
    assert (
        resolve_configured_path("prompts/a", config_file=config_file, field="x")
        == (config_file.parent / "prompts/a").resolve()
    )
    monkeypatch.chdir(tmp_path)
    assert (
        resolve_configured_path(
            {"path": "a", "relative_to": "cwd"}, config_file=config_file, field="x"
        )
        == (tmp_path / "a").resolve()
    )
    with pytest.raises(ConfigurationError):
        resolve_configured_path(
            {"path": "a", "relative_to": "home"}, config_file=config_file, field="x"
        )
    assert extract_dotted({"a": {"b": 2}}, "a.b", field="x") == 2
    with pytest.raises(ValueError):
        extract_dotted({}, "a.b", field="x")


def test_prompt_resolution_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = paths_with_config(tmp_path)
    config = load_or_create_config(paths)
    direct = tmp_path / "direct.md"
    direct.write_text("Direct")
    assert resolve_prompt(str(direct), config, paths)[:2] == ("Direct", "gemini")
    monkeypatch.chdir(tmp_path)
    assert resolve_prompt("direct.md", config, paths)[0] == "Direct"
    assert resolve_prompt("cleanup", config, paths) == ("Clean safely", "gemini", "Cleanup")
    bad = tmp_path / "bad"
    bad.mkdir()
    with pytest.raises(WeaveError, match="regular file"):
        resolve_prompt(str(bad), config, paths)
    invalid = tmp_path / "invalid"
    invalid.write_bytes(b"\xff")
    with pytest.raises(WeaveError, match="UTF-8"):
        resolve_prompt(str(invalid), config, paths)


def test_configured_prompt_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = base_config()
    value["weave"] = {
        "file": {"provider": "gemini", "prompt_file": "p.md"},
        "cwd": {"provider": "gemini", "prompt_file": {"path": "q.md", "relative_to": "cwd"}},
    }
    paths = paths_with_config(tmp_path, value)
    paths.config_file.parent.joinpath("p.md").write_text("P")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "q.md").write_text("Q")
    config = load_or_create_config(paths)
    assert resolve_prompt("file", config, paths)[0] == "P"
    assert resolve_prompt("cwd", config, paths)[0] == "Q"
    for profile in (
        {"provider": "gemini"},
        {"provider": "gemini", "prompt": "x", "prompt_file": "y"},
    ):
        config.weave["bad"] = profile
        with pytest.raises(WeaveError, match="exactly one"):
            resolve_prompt("bad", config, paths)


def test_strict_response_preservation() -> None:
    original = packet()
    enriched = json.loads(json.dumps(original))
    enriched["weave"] = {"type": "x", "content": "y"}
    assert validate_response(json.dumps(enriched), original) == enriched
    for text in ("```json\n{}\n```", "[]", "{}"):
        with pytest.raises(WeaveError):
            validate_response(text, original)
    changed = json.loads(json.dumps(enriched))
    changed["metadata"]["nested"][1]["x"] = False
    with pytest.raises(WeaveError, match="modified"):
        validate_response(json.dumps(changed), original)
    deleted = json.loads(json.dumps(enriched))
    del deleted["source"]
    with pytest.raises(WeaveError, match="deleted"):
        validate_response(json.dumps(deleted), original)


def test_weave_cli_success_and_secret_safe_log(tmp_path: Path) -> None:
    paths = paths_with_config(tmp_path)
    fake = FakeProvider()
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        weave_cli.run(
            ["cleanup", "--log"],
            stdin=io.StringIO(json.dumps(packet())),
            stdout=stdout,
            stderr=stderr,
            paths=paths,
            provider=fake,
        )
        == 0
    )
    result = json.loads(stdout.getvalue())
    assert result["run"]["id"] == RUN and result["weave"]["type"] == "gratitude"
    assert (
        stderr.getvalue() == ""
        and "PRIVATE" not in next(paths.log_directory.glob("*.log")).read_text()
    )
    assert "JSON-to-JSON" in fake.calls[0][0] and fake.calls[0][1] == "Clean safely"


def test_provider_configuration_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProviderError):
        build_provider("other", {})
    provider = build_provider(
        "gemini", {"model": "m", "credential": {"source": "pass", "name": "n"}}
    )
    assert provider.model == "m"
    monkeypatch.setattr(GeminiProvider, "_secret", lambda self: "SECRET")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}).encode()

    calls = 0

    def opener(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("temporary")
        return Response()

    live = GeminiProvider("m", "n", opener=opener, sleeper=lambda _: None, max_attempts=2)
    assert live.transform("s", "p", "{}") == "{}" and calls == 2


def test_insert_order_and_duplicate_warning(tmp_path: Path) -> None:
    existing = "# Journal\n\n## 2026-08-04\n\nold\n\n## 2026-08-06\n\nlater\n\n"
    updated, duplicate = insert_chronologically(existing, "2026-08-05", "## 2026-08-05\n\nmid\n\n")
    assert not duplicate and updated.index("08-04") < updated.index("08-05") < updated.index(
        "08-06"
    )
    updated, duplicate = insert_chronologically(
        updated, "2026-08-05", "## 2026-08-05\n\nsecond\n\n"
    )
    assert duplicate and updated.index("mid") < updated.index("second") < updated.index("later")


def test_output_cli_timezone_duplicate_append_create_and_safety(tmp_path: Path) -> None:
    paths = paths_with_config(tmp_path)
    vault = paths.config_file.parent / "vault"
    enriched = packet()
    enriched["weave"] = {"type": "gratitude", "content": "first"}
    stderr = io.StringIO()
    assert (
        out_cli.run(
            ["journals"], stdin=io.StringIO(json.dumps(enriched)), stderr=stderr, paths=paths
        )
        == 0
    )
    journal = vault / "Gratitude Journal.md"
    assert "## 2026-08-05" in journal.read_text()
    enriched["weave"]["content"] = "second"
    stderr = io.StringIO()
    assert (
        out_cli.run(
            ["JOURNALS"], stdin=io.StringIO(json.dumps(enriched)), stderr=stderr, paths=paths
        )
        == 0
    )
    assert "keeping both" in stderr.getvalue() and journal.read_text().index(
        "first"
    ) < journal.read_text().index("second")
    value = base_config()
    value["out"]["Journals"]["destinations"]["gratitude"] = {
        "operation": "append",
        "file": "append.md",
        "format": "{date}:{content}\n",
    }
    paths = paths_with_config(tmp_path / "append", value)
    config = load_or_create_config(paths)
    assert persist(enriched, "journals", config, paths, warn=lambda _: None)[0] == "append"
    enriched["weave"] = {"type": "unknown", "content": "misc"}
    paths = paths_with_config(tmp_path / "create")
    assert out_cli.run(["journals"], stdin=io.StringIO(json.dumps(enriched)), paths=paths) == 0
    assert list((paths.config_file.parent / "vault" / "00 Inbox").glob("*.md"))
    assert out_cli.run(["journals"], stdin=io.StringIO(json.dumps(enriched)), paths=paths) == 1
    unsafe = base_config()
    unsafe["out"]["Journals"]["destinations"]["gratitude"]["file"] = "../escape.md"
    paths = paths_with_config(tmp_path / "unsafe", unsafe)
    enriched["weave"] = {"type": "gratitude", "content": "x"}
    assert out_cli.run(["journals"], stdin=io.StringIO(json.dumps(enriched)), paths=paths) == 1


def test_timezone_crosses_date_and_dst(tmp_path: Path) -> None:
    paths = paths_with_config(tmp_path)
    config = load_or_create_config(paths)
    for dt, expected in [
        ("2026-08-05T06:30:00Z", "2026-08-04"),
        ("2026-01-05T07:30:00Z", "2026-01-04"),
    ]:
        enriched = packet(dt)
        enriched["weave"] = {"type": "dream", "content": dt}
        _, target = persist(enriched, "journals", config, paths, warn=lambda _: None)
        assert expected in target.read_text()


def test_end_to_end_five_categories(tmp_path: Path) -> None:
    paths = paths_with_config(tmp_path)
    expected_files = {
        "gratitude": "Gratitude Journal.md",
        "dream": "Dream Journal.md",
        "dss": "DSS Chronicles.md",
        "sacred": "Sacred Journey Journal.md",
        "unknown": "00 Inbox",
    }
    for category, expected in expected_files.items():
        source = packet()
        source["transcript"] = f"representative {category}"
        woven = io.StringIO()
        fake = FakeProvider(category, f"content-{category}")
        assert (
            weave_cli.run(
                ["cleanup"],
                stdin=io.StringIO(json.dumps(source)),
                stdout=woven,
                paths=paths,
                provider=fake,
            )
            == 0
        )
        enriched = json.loads(woven.getvalue())
        assert enriched["run"]["id"] == RUN and enriched["transcript"] == source["transcript"]
        assert out_cli.run(["journals"], stdin=io.StringIO(json.dumps(enriched)), paths=paths) == 0
        root = paths.config_file.parent / "vault"
        assert (root / expected).exists()


def test_tilde_prompt_and_unknown_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    prompt = home / "prompt.md"
    prompt.write_text("home prompt")
    monkeypatch.setenv("HOME", str(home))
    paths = paths_with_config(tmp_path / "app")
    config = load_or_create_config(paths)
    assert resolve_prompt("~/prompt.md", config, paths)[0] == "home prompt"
    with pytest.raises(WeaveError, match="Available profiles"):
        resolve_prompt("does-not-exist", config, paths)


def test_provider_permanent_http_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(GeminiProvider, "_secret", lambda self: "SECRET")
    calls = 0

    def opener(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError("https://redacted", 400, "bad", {}, None)

    provider = GeminiProvider("m", "n", opener=opener, sleeper=lambda _: None)
    with pytest.raises(ProviderError, match="400"):
        provider.transform("system", "prompt", "{}")
    assert calls == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"timezone": "Not/AZone"}), "timezone"),
        (
            lambda value: value.update(
                {"packet_fields": {"category": "missing", "content": "weave.content"}}
            ),
            "missing",
        ),
    ],
)
def test_output_validation_errors_leave_existing_file_unchanged(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    value = base_config()
    profile = value["out"]["Journals"]
    mutation(profile)
    paths = paths_with_config(tmp_path, value)
    journal = paths.config_file.parent / "vault" / "Gratitude Journal.md"
    journal.parent.mkdir(parents=True)
    journal.write_text("original")
    enriched = packet()
    enriched["weave"] = {"type": "gratitude", "content": "new"}
    stderr = io.StringIO()
    assert (
        out_cli.run(
            ["journals"],
            stdin=io.StringIO(json.dumps(enriched)),
            stderr=stderr,
            paths=paths,
        )
        == 1
    )
    assert message.casefold() in stderr.getvalue().casefold()
    assert journal.read_text() == "original"


def test_unknown_category_and_invalid_format_are_rejected(tmp_path: Path) -> None:
    enriched = packet()
    enriched["weave"] = {"type": "not-configured", "content": "new"}
    paths = paths_with_config(tmp_path / "unknown")
    assert out_cli.run(["journals"], stdin=io.StringIO(json.dumps(enriched)), paths=paths) == 1

    value = base_config()
    value["out"]["Journals"]["destinations"]["gratitude"]["format"] = "{secret}"
    paths = paths_with_config(tmp_path / "format", value)
    enriched["weave"]["type"] = "gratitude"
    assert out_cli.run(["journals"], stdin=io.StringIO(json.dumps(enriched)), paths=paths) == 1


def test_packaged_output_profile_creates_inspectable_cwd_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ApplicationPaths(tmp_path / "config" / "config.json", tmp_path / "logs")
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    monkeypatch.chdir(run_directory)
    config = load_or_create_config(paths)
    enriched = packet()
    enriched["weave"] = {"type": "dream", "content": "A prototype dream."}
    operation, target = persist(
        enriched,
        "example-journals",
        config,
        paths,
        warn=lambda _: None,
    )
    assert operation == "insert"
    assert target == run_directory / "transcript-weaver-test-output" / "Dream Journal.md"
    assert target.read_text() == "## 2026-08-05\n\nA prototype dream.\n\n"
    assert (paths.config_file.parent / "prompts" / "example.md").exists()

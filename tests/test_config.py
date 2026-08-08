import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from transcript_weaver.config import (
    ApplicationPaths,
    ConfigurationError,
    get_application_paths,
    load_or_create_config,
    packaged_default_config_bytes,
    packaged_example_prompt_bytes,
    validate_config,
)

EXPECTED = json.loads(packaged_default_config_bytes())


def test_packaged_default_has_intended_sections() -> None:
    assert json.loads(packaged_default_config_bytes()) == EXPECTED


def test_first_run_creates_owned_config_atomically(app_paths: ApplicationPaths) -> None:
    config = load_or_create_config(app_paths)
    assert config.logging.retained_runs == 5
    assert json.loads(app_paths.config_file.read_text()) == EXPECTED
    assert not list(app_paths.config_file.parent.glob("*.tmp"))
    assert not app_paths.log_directory.exists()


def test_existing_config_is_never_overwritten(app_paths: ApplicationPaths) -> None:
    app_paths.config_file.parent.mkdir(parents=True)
    custom = {
        "schema_version": 1,
        "logging": {"retained_runs": 1000},
        "providers": {},
        "weave": {},
        "out": {},
    }
    original = json.dumps(custom, indent=2)
    app_paths.config_file.write_text(original)
    assert load_or_create_config(app_paths).logging.retained_runs == 1000
    assert app_paths.config_file.read_text() == original


def test_concurrent_first_run_is_complete(app_paths: ApplicationPaths) -> None:
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: load_or_create_config(app_paths), range(12)))
    assert all(result.logging.retained_runs == 5 for result in results)
    assert json.loads(app_paths.config_file.read_text()) == EXPECTED


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        {"schema_version": 2, "logging": {"retained_runs": 5}},
        {"schema_version": 1, "logging": []},
        {"schema_version": 1, "logging": {"retained_runs": -1}},
        {"schema_version": 1, "logging": {"retained_runs": True}},
        {"schema_version": 1, "logging": {"retained_runs": 5, "extra": 1}},
        {"schema_version": 1, "logging": {"retained_runs": 5}, "extra": 1},
    ],
)
def test_invalid_config_values_are_rejected(value: object, tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        validate_config(value, path=tmp_path / "config.json")


def test_invalid_existing_config_is_untouched(app_paths: ApplicationPaths) -> None:
    app_paths.config_file.parent.mkdir(parents=True)
    app_paths.config_file.write_text("{broken")
    with pytest.raises(ConfigurationError, match=str(app_paths.config_file)):
        load_or_create_config(app_paths)
    assert app_paths.config_file.read_text() == "{broken"


def test_injected_platform_directories_are_used(tmp_path: Path) -> None:
    class FakeDirs:
        user_config_path = tmp_path / "xdg-config" / "transcript-weaver"
        user_log_path = tmp_path / "xdg-state" / "transcript-weaver" / "log"

    paths = get_application_paths(FakeDirs(), FakeDirs())  # type: ignore[arg-type]
    assert paths.config_file == FakeDirs.user_config_path / "config.json"
    assert paths.log_directory == FakeDirs.user_log_path


def test_linux_xdg_and_fallback_paths(monkeypatch) -> None:
    from platformdirs.unix import Unix

    monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg/config")
    monkeypatch.setenv("XDG_STATE_HOME", "/xdg/state")
    paths = get_application_paths(
        Unix("transcript-weaver", appauthor=False),
        Unix("transcript-weaver", appauthor=False),
    )
    assert paths.config_file == Path("/xdg/config/transcript-weaver/config.json")
    assert paths.log_directory == Path("/xdg/state/transcript-weaver/log")

    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setenv("HOME", "/home/example")
    paths = get_application_paths(
        Unix("transcript-weaver", appauthor=False),
        Unix("transcript-weaver", appauthor=False),
    )
    assert paths.config_file == Path("/home/example/.config/transcript-weaver/config.json")
    assert paths.log_directory == Path("/home/example/.local/state/transcript-weaver/log")


def test_macos_paths(monkeypatch) -> None:
    from platformdirs.macos import MacOS

    monkeypatch.setenv("HOME", "/Users/example")
    paths = get_application_paths(
        MacOS("Transcript Weaver", appauthor=False),
        MacOS("Transcript Weaver", appauthor=False),
    )
    assert paths.config_file == Path(
        "/Users/example/Library/Application Support/Transcript Weaver/config.json"
    )
    assert paths.log_directory == Path("/Users/example/Library/Logs/Transcript Weaver")


def test_windows_roaming_config_and_local_logs(monkeypatch) -> None:
    from platformdirs.windows import Windows

    def fake_win_folder(const: str) -> str:
        if const == "CSIDL_APPDATA":
            return "C:/Users/example/AppData/Roaming"
        if const == "CSIDL_LOCAL_APPDATA":
            return "C:/Users/example/AppData/Local"
        raise AssertionError(const)

    monkeypatch.setattr("platformdirs.windows.get_win_folder", fake_win_folder)
    paths = get_application_paths(
        Windows("Transcript Weaver", appauthor=False, roaming=True),
        Windows("Transcript Weaver", appauthor=False, roaming=False),
    )
    assert str(paths.config_file).replace("\\", "/") == (
        "C:/Users/example/AppData/Roaming/Transcript Weaver/config.json"
    )
    assert str(paths.log_directory).replace("\\", "/") == (
        "C:/Users/example/AppData/Local/Transcript Weaver/Logs"
    )


def test_first_run_provisions_example_prompt_and_sanitizes_comments(
    app_paths: ApplicationPaths,
) -> None:
    config = load_or_create_config(app_paths)
    prompt_path = app_paths.config_file.parent / "prompts" / "example.md"
    assert prompt_path.read_bytes() == packaged_example_prompt_bytes()
    assert "dream|gratitude|dss|sacred|unknown" in prompt_path.read_text()
    vault = config.out["example-journals"]["vault"]
    assert vault == {"path": "transcript-weaver-test-output", "relative_to": "cwd"}
    stored = json.loads(app_paths.config_file.read_text())
    assert stored["out"]["example-journals"]["vault"]["_comment"]


def test_first_run_never_overwrites_existing_example_prompt(
    app_paths: ApplicationPaths,
) -> None:
    prompt_path = app_paths.config_file.parent / "prompts" / "example.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("my customized prompt")
    load_or_create_config(app_paths)
    assert prompt_path.read_text() == "my customized prompt"


def test_top_level_configuration_error_lists_missing_and_unrecognized_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    value = {
        "schema_version": 1,
        "logging": {"retained_runs": 5},
        "obsolete": {},
    }
    with pytest.raises(ConfigurationError) as caught:
        validate_config(value, path=path)
    message = str(caught.value)
    assert str(path) in message
    assert "missing required fields: out, providers, weave" in message
    assert "unrecognized fields: obsolete" in message
    assert "Expected fields: logging, out, providers, schema_version, weave" in message


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["providers"]["gemini"].update({"unexpected": True}),
            "providers.gemini has unrecognized fields: unexpected",
        ),
        (
            lambda value: value["weave"]["transcript-cleanup"].pop("prompt_file"),
            "weave.transcript-cleanup must contain exactly one of prompt or prompt_file",
        ),
        (
            lambda value: value["out"]["example-journals"]["packet_fields"].pop("content"),
            "packet_fields has missing required fields: content",
        ),
        (
            lambda value: value["out"]["example-journals"]["vault"].update(
                {"relative_to": "elsewhere"}
            ),
            "vault.relative_to must be 'cwd' or 'config'",
        ),
    ],
)
def test_nested_configuration_errors_name_exact_field(
    tmp_path: Path, mutate, expected: str
) -> None:
    value = json.loads(packaged_default_config_bytes())
    mutate(value)
    with pytest.raises(ConfigurationError, match=expected):
        validate_config(value, path=tmp_path / "config.json")


def test_vault_path_object_accepts_cwd_config_absolute_and_home(tmp_path: Path) -> None:
    for vault in (
        {"path": "test-output", "relative_to": "cwd"},
        {"path": "test-output", "relative_to": "config"},
        {"path": "/absolute/test-output"},
        {"path": "~/test-output"},
    ):
        value = json.loads(packaged_default_config_bytes())
        value["out"]["example-journals"]["vault"] = vault
        assert validate_config(value, path=tmp_path / "config.json")


def test_absolute_vault_rejects_relative_to(tmp_path: Path) -> None:
    value = json.loads(packaged_default_config_bytes())
    value["out"]["example-journals"]["vault"] = {
        "path": "/absolute/test-output",
        "relative_to": "cwd",
    }
    with pytest.raises(ConfigurationError, match="must be omitted"):
        validate_config(value, path=tmp_path / "config.json")


def test_existing_default_config_recreates_only_missing_referenced_prompt(
    app_paths: ApplicationPaths,
) -> None:
    app_paths.config_file.parent.mkdir(parents=True)
    app_paths.config_file.write_bytes(packaged_default_config_bytes())
    prompt_path = app_paths.config_file.parent / "prompts" / "example.md"
    load_or_create_config(app_paths)
    assert prompt_path.read_bytes() == packaged_example_prompt_bytes()
    prompt_path.write_text("custom")
    load_or_create_config(app_paths)
    assert prompt_path.read_text() == "custom"


def test_weave_profile_rejects_unknown_provider(tmp_path: Path) -> None:
    value = json.loads(packaged_default_config_bytes())
    value["weave"]["transcript-cleanup"]["provider"] = "missing-provider"
    with pytest.raises(ConfigurationError, match="Available providers: gemini"):
        validate_config(value, path=tmp_path / "config.json")

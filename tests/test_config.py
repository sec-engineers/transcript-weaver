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

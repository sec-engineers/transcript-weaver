import io
import json
from pathlib import Path
from typing import Any

import pytest

from transcript_weaver.config import ApplicationPaths, validate_config
from transcript_weaver.inp import cli as inp_cli
from transcript_weaver.prep import cli as prep_cli
from transcript_weaver.prep import configuration as prep_configuration


def schema_one_config(*, credential_name: str = "api/gemini") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "logging": {"retained_runs": 5},
        "providers": {
            "gemini": {
                "model": "gemini-test-model",
                "credential": {"source": "pass", "name": credential_name},
            }
        },
        "_comment_profiles": ["Preserve this comment."],
        "weave": {
            "example": {
                "_comment": "Preserve this profile comment.",
                "provider": "Gemini",
                "prompt": "Clean safely.",
            }
        },
        "out": {},
    }


def write_config(paths: ApplicationPaths, value: dict[str, Any]) -> bytes:
    paths.config_file.parent.mkdir(parents=True)
    original = (json.dumps(value, indent=2) + "\n").encode()
    paths.config_file.write_bytes(original)
    return original


def test_validate_config_reports_current_schema(app_paths: ApplicationPaths) -> None:
    value = schema_one_config()
    value.pop("providers")
    value.update(
        {
            "schema_version": 2,
            "provider": "gemini",
            "model": "gemini-test-model",
            "api_key": "env(TEST_KEY)",
        }
    )
    for profile in value["weave"].values():
        profile.pop("provider")
    write_config(app_paths, value)
    stdout = io.StringIO()
    assert prep_cli.run(["validate-config"], stdout=stdout, paths=app_paths) == 0
    assert "valid for schema version 2" in stdout.getvalue()
    assert "[y/N]" not in stdout.getvalue()


def test_schema_one_declined_migration_changes_nothing(app_paths: ApplicationPaths) -> None:
    original = write_config(app_paths, schema_one_config())
    stdout = io.StringIO()
    assert (
        prep_cli.run(
            ["validate-config"],
            stdin=io.StringIO("no\n"),
            stdout=stdout,
            paths=app_paths,
        )
        == 0
    )
    assert "requires schema version 2" in stdout.getvalue()
    assert "Update this configuration now? [y/N]" in stdout.getvalue()
    assert "was not changed" in stdout.getvalue()
    assert app_paths.config_file.read_bytes() == original
    assert not list(app_paths.config_file.parent.glob("*.backup*"))


def test_schema_one_confirmed_migration_is_valid_backed_up_and_secret_safe(
    app_paths: ApplicationPaths,
) -> None:
    secret_name = "api/private-name"
    original = write_config(app_paths, schema_one_config(credential_name=secret_name))
    stdout = io.StringIO()
    assert (
        prep_cli.run(
            ["validate-config"],
            stdin=io.StringIO("yes\n"),
            stdout=stdout,
            paths=app_paths,
        )
        == 0
    )
    output = stdout.getvalue()
    assert "updated successfully to schema version 2" in output
    assert secret_name not in output
    backup = app_paths.config_file.with_name("config.json.schema-v1.backup")
    assert backup.read_bytes() == original
    migrated = json.loads(app_paths.config_file.read_text())
    config = validate_config(migrated, path=app_paths.config_file)
    assert config.provider == "gemini"
    assert config.model == "gemini-test-model"
    assert config.api_key == "command(pass show api/private-name)"
    assert "providers" not in migrated
    assert "provider" not in migrated["weave"]["example"]
    assert migrated["_comment_profiles"] == ["Preserve this comment."]
    assert migrated["weave"]["example"]["_comment"] == "Preserve this profile comment."


def test_migration_never_overwrites_an_existing_backup(app_paths: ApplicationPaths) -> None:
    write_config(app_paths, schema_one_config())
    first_backup = app_paths.config_file.with_name("config.json.schema-v1.backup")
    first_backup.write_text("keep me")
    assert (
        prep_cli.run(
            ["validate-config"],
            stdin=io.StringIO("yes\n"),
            stdout=io.StringIO(),
            paths=app_paths,
        )
        == 0
    )
    assert first_backup.read_text() == "keep me"
    assert app_paths.config_file.with_name("config.json.schema-v1.backup.1").exists()


def test_unsupported_schema_one_shape_is_untouched(app_paths: ApplicationPaths) -> None:
    value = schema_one_config()
    value["providers"]["other"] = value["providers"]["gemini"].copy()
    original = write_config(app_paths, value)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        prep_cli.run(
            ["validate-config"],
            stdin=io.StringIO("yes\n"),
            stdout=stdout,
            stderr=stderr,
            paths=app_paths,
        )
        == 1
    )
    assert stdout.getvalue() == ""
    error = " ".join(stderr.getvalue().split())
    assert "exactly one configured provider" in error
    assert "manual migration" in error
    assert app_paths.config_file.read_bytes() == original


def test_failed_atomic_replacement_leaves_original_and_backup(
    app_paths: ApplicationPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = write_config(app_paths, schema_one_config())

    def fail(path: Path, data: bytes) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(prep_configuration, "_replace_atomically", fail)
    stderr = io.StringIO()
    assert (
        prep_cli.run(
            ["validate-config"],
            stdin=io.StringIO("yes\n"),
            stdout=io.StringIO(),
            stderr=stderr,
            paths=app_paths,
        )
        == 1
    )
    assert "Could not safely update" in stderr.getvalue()
    assert app_paths.config_file.read_bytes() == original
    backup = app_paths.config_file.with_name("config.json.schema-v1.backup")
    assert backup.read_bytes() == original


def test_missing_configuration_points_to_safe_creation(app_paths: ApplicationPaths) -> None:
    stderr = io.StringIO()
    assert prep_cli.run(["validate-config"], stderr=stderr, paths=app_paths) == 1
    assert "No configuration file was found" in stderr.getvalue()
    assert "create the current schema-2 configuration" in " ".join(stderr.getvalue().split())
    assert not app_paths.config_file.exists()


def test_pipeline_schema_error_leads_directly_to_helper(app_paths: ApplicationPaths) -> None:
    write_config(app_paths, schema_one_config())
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        inp_cli.run(
            ["stdin"],
            stdin=io.StringIO("transcript"),
            stdout=stdout,
            stderr=stderr,
            paths=app_paths,
        )
        == 1
    )
    assert stdout.getvalue() == ""
    error = " ".join(stderr.getvalue().split())
    assert "requires configuration schema version 2" in error
    assert "trwprep validate-config" in error

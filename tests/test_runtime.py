from datetime import datetime, timezone
from pathlib import Path

import pytest

from transcript_weaver.runtime import (
    DiagnosticError,
    LoggingOptions,
    RunIdError,
    StageLog,
    apply_log_retention,
    build_diagnostic_path,
    ensure_packet_run_id,
    generate_run_id,
    validate_run_id,
    write_debug_artifact,
)

RUN1 = "20260728-100000-a1b2"
RUN2 = "20260728-110000-b2c3"
RUN3 = "20260728-120000-c3d4"


def test_run_id_is_sortable_safe_and_separate_from_recording_time(monkeypatch) -> None:
    monkeypatch.setattr("transcript_weaver.runtime.secrets.token_hex", lambda _: "a7f3")
    value = generate_run_id(datetime(2026, 7, 28, 14, 30, 12, tzinfo=timezone.utc))
    assert value == "20260728-143012-a7f3"
    assert validate_run_id(value) == value
    assert "/" not in value and "\\" not in value


@pytest.mark.parametrize("value", ["../bad", "20260728-143012", "x" * 30, 123, True])
def test_run_id_rejects_unsafe_values(value: object) -> None:
    with pytest.raises(RunIdError):
        validate_run_id(value)


def test_packet_preserves_valid_id_and_generates_missing(monkeypatch) -> None:
    existing = {"run": {"id": RUN1}}
    assert ensure_packet_run_id(existing) == RUN1
    assert existing == {"run": {"id": RUN1}}
    monkeypatch.setattr("transcript_weaver.runtime.generate_run_id", lambda clock=None: RUN2)
    legacy: dict[str, object] = {"transcript": "legacy"}
    assert ensure_packet_run_id(legacy) == RUN2
    assert legacy["run"] == {"id": RUN2}


def test_packet_rejects_invalid_existing_run() -> None:
    with pytest.raises(RunIdError):
        ensure_packet_run_id({"run": {"id": "../../escape"}})


def test_artifact_paths_are_correlated_safe_and_never_overwritten(tmp_path: Path) -> None:
    path = write_debug_artifact(
        tmp_path,
        RUN1,
        "trwinp",
        suffix="otter-list",
        extension=".html",
        content="<html></html>",
    )
    assert path.name == f"{RUN1}-trwinp-otter-list.html"
    with pytest.raises(FileExistsError):
        write_debug_artifact(
            tmp_path,
            RUN1,
            "trwinp",
            suffix="otter-list",
            extension=".html",
            content="replacement",
        )
    with pytest.raises(DiagnosticError):
        build_diagnostic_path(tmp_path, RUN1, "trwinp", suffix="../bad", extension=".png")


def _make_group(directory: Path, run_id: str) -> list[Path]:
    paths = []
    for stage, extension in (("trwinp", ".log"), ("trwinp", ".png"), ("trwout", ".log")):
        path = directory / f"{run_id}-{stage}{extension}"
        path.write_text("diagnostic")
        paths.append(path)
    return paths


def test_retention_counts_complete_run_groups_and_keeps_unrelated(tmp_path: Path) -> None:
    old = _make_group(tmp_path, RUN1)
    middle = _make_group(tmp_path, RUN2)
    newest = _make_group(tmp_path, RUN3)
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("keep")
    warnings: list[str] = []
    apply_log_retention(tmp_path, 2, current_run_id=RUN3, warn=warnings.append)
    assert not any(path.exists() for path in old)
    assert all(path.exists() for path in middle + newest)
    assert unrelated.exists()
    assert warnings == []


def test_zero_retention_protects_only_current_run(tmp_path: Path) -> None:
    old = _make_group(tmp_path, RUN1)
    current = _make_group(tmp_path, RUN2)
    apply_log_retention(tmp_path, 0, current_run_id=RUN2, warn=lambda _: None)
    assert not any(path.exists() for path in old)
    assert all(path.exists() for path in current)


def test_retention_ignores_missing_directory_and_symlink(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    apply_log_retention(missing, 5, current_run_id=RUN1, warn=lambda _: None)
    assert not missing.exists()
    target = tmp_path / "target"
    target.write_text("keep")
    link = tmp_path / f"{RUN1}-trwinp.log"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    apply_log_retention(tmp_path, 0, current_run_id=RUN2, warn=lambda _: None)
    assert link.exists() and target.exists()


def test_stage_logging_contains_correlation_and_closes_cleanly(tmp_path: Path) -> None:
    stage_log = StageLog(
        run_id=RUN1,
        stage="trwinp",
        options=LoggingOptions(log=True),
        log_directory=tmp_path,
    )
    stage_log.info("Safe milestone")
    path = stage_log.path
    stage_log.close()
    assert path is not None
    content = path.read_text()
    assert f"run={RUN1} stage=trwinp" in content
    assert "Safe milestone" in content


def test_byte_artifact_and_invalid_stage_extension(tmp_path: Path) -> None:
    png = write_debug_artifact(
        tmp_path,
        RUN1,
        "trwinp",
        suffix="page-one",
        extension=".png",
        content=b"png-bytes",
    )
    assert png.read_bytes() == b"png-bytes"
    with pytest.raises(DiagnosticError):
        build_diagnostic_path(tmp_path, RUN1, "bad-stage", extension=".log")
    with pytest.raises(DiagnosticError):
        build_diagnostic_path(tmp_path, RUN1, "trwinp", extension=".json")


def test_verbose_logger_supports_debug_warning_and_traceback(tmp_path: Path) -> None:
    stage_log = StageLog(
        run_id=RUN2,
        stage="trwclean",
        options=LoggingOptions(verbose=True),
        log_directory=tmp_path,
    )
    stage_log.debug("Detailed decision")
    stage_log.warning("Attention")
    try:
        raise RuntimeError("representative failure")
    except RuntimeError:
        stage_log.exception("RuntimeError")
    path = stage_log.path
    stage_log.close()
    assert path is not None
    content = path.read_text()
    assert "DEBUG" in content and "WARNING" in content and "Traceback" in content


def test_disabled_logger_creates_no_directory(tmp_path: Path) -> None:
    directory = tmp_path / "absent"
    stage_log = StageLog(
        run_id=RUN3,
        stage="trwout",
        options=LoggingOptions(),
        log_directory=directory,
    )
    stage_log.info("discarded")
    stage_log.close()
    assert not directory.exists()

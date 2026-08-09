import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from transcript_weaver import __version__
from transcript_weaver.config import ApplicationPaths
from transcript_weaver.inp import cli
from transcript_weaver.inp.errors import ExitStatus, SourceUnavailableError, TranscriptNotFoundError
from transcript_weaver.inp.otter import OtterCapture, OtterSource, parse_otter_datetime
from transcript_weaver.inp.sources import FileSource, StdinSource
from transcript_weaver.models import AcquiredTranscript, ModelError, Source, TranscriptPacket
from transcript_weaver.out import cli as out_cli
from transcript_weaver.weave import cli as weave_cli

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def test_packet_contract_and_deterministic_serialization() -> None:
    acquired = AcquiredTranscript(
        "  Café notes\n",
        datetime(2026, 7, 28, 11, 30, 45, 999, tzinfo=timezone.utc),
        Source("file", "notes.txt", "/safe/notes.txt"),
    )
    packet = TranscriptPacket.from_acquired(acquired, run_id="20260728-113045-a1b2")
    assert packet.as_dict() == {
        "schema_version": 1,
        "trw_version": __version__,
        "run": {"id": "20260728-113045-a1b2"},
        "datetime": "2026-07-28T11:30:45Z",
        "source": {"type": "file", "name": "notes.txt", "reference": "/safe/notes.txt"},
        "transcript": "Café notes",
        "metadata": {},
    }
    assert packet.to_json().endswith("\n")
    assert packet.to_json() == packet.to_json()


@pytest.mark.parametrize(
    ("packet", "message"),
    [
        (TranscriptPacket(datetime(2026, 1, 1), Source("stdin"), "text"), "timezone"),
        (
            TranscriptPacket(datetime(2026, 1, 1, tzinfo=timezone.utc), Source("stdin"), " "),
            "empty",
        ),
        (
            TranscriptPacket(datetime(2026, 1, 1, tzinfo=timezone.utc), Source(" "), "text"),
            "Source type",
        ),
    ],
)
def test_packet_rejects_invalid_data(packet: TranscriptPacket, message: str) -> None:
    with pytest.raises(ModelError, match=message):
        packet.as_dict()


def test_stdin_uses_injected_clock_and_rejects_empty() -> None:
    instant = datetime(2026, 7, 28, 18, 30, tzinfo=timezone.utc)
    acquired = StdinSource(io.StringIO("hello\n"), clock=lambda: instant).acquire()
    assert acquired.recorded_at == instant
    with pytest.raises(TranscriptNotFoundError):
        StdinSource(io.StringIO(" \n")).acquire()


def test_file_reads_utf8_and_uses_modification_time(tmp_path: Path) -> None:
    path = tmp_path / "café.txt"
    path.write_text("Résumé\n", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp()
    os.utime(path, (timestamp, timestamp))
    acquired = FileSource(path).acquire()
    assert acquired.transcript == "Résumé\n"
    assert acquired.recorded_at.timestamp() == timestamp
    assert acquired.source.reference == str(path.resolve())


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "invalid"])
def test_file_errors_are_actionable(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "input.txt"
    expected: type[Exception] = SourceUnavailableError
    if kind == "directory":
        path.mkdir()
    elif kind == "empty":
        path.write_text("\n", encoding="utf-8")
        expected = TranscriptNotFoundError
    elif kind == "invalid":
        path.write_bytes(b"\xff")
    with pytest.raises(expected):
        FileSource(path).acquire()


def test_ordinary_cli_is_silent_and_creates_no_log(app_paths: ApplicationPaths) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    status = cli.run(
        ["stdin"],
        stdin=io.StringIO("A transcript"),
        stdout=stdout,
        stderr=stderr,
        paths=app_paths,
    )
    packet = json.loads(stdout.getvalue())
    assert status == ExitStatus.OK
    assert RUN_ID_RE.fullmatch(packet["run"]["id"])
    assert packet["transcript"] == "A transcript"
    assert stderr.getvalue() == ""
    assert app_paths.config_file.exists()
    assert not app_paths.log_directory.exists()


def test_log_options_never_contaminate_stdout_or_log_transcript(
    app_paths: ApplicationPaths,
) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    secret_transcript = "PRIVATE_TRANSCRIPT_VALUE"
    assert (
        cli.run(
            ["stdin", "--verbose"],
            stdin=io.StringIO(secret_transcript),
            stdout=stdout,
            stderr=stderr,
            paths=app_paths,
        )
        == 0
    )
    packet = json.loads(stdout.getvalue())
    logs = list(app_paths.log_directory.glob("*.log"))
    assert len(logs) == 1
    content = logs[0].read_text()
    assert packet["run"]["id"] in logs[0].name
    assert secret_transcript not in content
    assert stderr.getvalue() == ""


def test_debug_artifacts_imply_log_and_warn(app_paths: ApplicationPaths) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        cli.run(
            ["stdin", "--debug-artifacts"],
            stdin=io.StringIO("safe input"),
            stdout=stdout,
            stderr=stderr,
            paths=app_paths,
        )
        == 0
    )
    assert json.loads(stdout.getvalue())["run"]["id"]
    assert list(app_paths.log_directory.glob("*.log"))
    assert "may contain transcripts" in stderr.getvalue()
    assert not list(app_paths.log_directory.glob("*.html"))
    assert not list(app_paths.log_directory.glob("*.png"))


def test_failure_has_no_partial_json(app_paths: ApplicationPaths) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    status = cli.run(
        ["stdin"], stdin=io.StringIO(""), stdout=stdout, stderr=stderr, paths=app_paths
    )
    assert status == ExitStatus.TRANSCRIPT_NOT_FOUND
    assert stdout.getvalue() == ""
    assert "did not contain" in stderr.getvalue()


def test_invalid_config_blocks_json_without_overwrite(app_paths: ApplicationPaths) -> None:
    app_paths.config_file.parent.mkdir(parents=True)
    app_paths.config_file.write_text("{bad")
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        cli.run(
            ["stdin"],
            stdin=io.StringIO("data"),
            stdout=stdout,
            stderr=stderr,
            paths=app_paths,
        )
        != 0
    )
    assert stdout.getvalue() == ""
    assert str(app_paths.config_file) in stderr.getvalue()
    assert app_paths.config_file.read_text() == "{bad"


@pytest.mark.parametrize("stage", ["trwinp", "trweave", "trwout"])
def test_any_command_can_create_first_run_config(tmp_path: Path, stage: str) -> None:
    paths = ApplicationPaths(tmp_path / stage / "config.json", tmp_path / stage / "log")
    if stage == "trwinp":
        cli.run(["stdin"], stdin=io.StringIO("data"), paths=paths)
    elif stage == "trweave":
        weave_cli.run(["missing"], stdin=io.StringIO(""), paths=paths)
    else:
        out_cli.run(["missing"], stdin=io.StringIO(""), paths=paths)
    assert paths.config_file.exists()


def test_downstream_placeholders_preserve_or_generate_run_for_logging(
    tmp_path: Path,
) -> None:
    for module, stage in ((weave_cli, "trweave"), (out_cli, "trwout")):
        paths = ApplicationPaths(tmp_path / stage / "config.json", tmp_path / stage / "log")
        packet = {
            "schema_version": 1,
            "trw_version": __version__,
            "run": {"id": "20260728-120000-a1b2"},
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        assert (
            module.run(
                ["missing", "--log"],
                stdin=io.StringIO(json.dumps(packet)),
                stdout=stdout,
                stderr=stderr,
                paths=paths,
            )
            == 1
        )
        assert stdout.getvalue() == ""
        assert list(paths.log_directory.glob(f"{packet['run']['id']}-{stage}.log"))

        generated_paths = ApplicationPaths(
            tmp_path / f"{stage}-legacy" / "config.json",
            tmp_path / f"{stage}-legacy" / "log",
        )
        module.run(
            ["missing", "--log"],
            stdin=io.StringIO(json.dumps({"schema_version": 1, "trw_version": __version__})),
            paths=generated_paths,
        )
        names = [path.name for path in generated_paths.log_directory.glob("*.log")]
        assert len(names) == 1 and RUN_ID_RE.match(names[0].split(f"-{stage}")[0])


def test_ordinary_invocation_applies_zero_retention(app_paths: ApplicationPaths) -> None:
    app_paths.config_file.parent.mkdir(parents=True)
    app_paths.config_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "logging": {"retained_runs": 0},
                "providers": {},
                "weave": {},
                "out": {},
            }
        )
    )
    app_paths.log_directory.mkdir(parents=True)
    old = app_paths.log_directory / "20200101-000000-a1b2-trwinp.log"
    old.write_text("old")
    cli.run(["stdin"], stdin=io.StringIO("data"), paths=app_paths)
    assert not old.exists()


@pytest.mark.parametrize("args", [[], ["file"], ["unknown"], ["--help"]])
def test_conventional_usage_and_help(args: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.run(args)
    assert caught.value.code in {0, 2}


class FakeClient:
    def __init__(self, capture: OtterCapture) -> None:
        self.capture = capture

    def capture_newest(self) -> OtterCapture:
        return self.capture


def test_mocked_otter_preserves_identity_and_converts_to_utc() -> None:
    capture = OtterCapture(
        "Newest transcript",
        "Jul 28, 2026 at 11:30 AM",
        "Morning note",
        "https://otter.ai/u/opaque-recording-id",
        301.5,
    )
    pacific = timezone(timedelta(hours=-7))
    acquired = OtterSource(FakeClient(capture), local_timezone=pacific).acquire()
    assert acquired.recorded_at == datetime(2026, 7, 28, 18, 30, tzinfo=timezone.utc)
    assert acquired.source.reference == capture.url
    assert acquired.duration_seconds == 301.5


@pytest.mark.parametrize(
    ("shown", "expected"),
    [
        ("July 6, 2026 at 10:15 AM", datetime(2026, 7, 6, 17, 15, tzinfo=timezone.utc)),
        ("07/06/2026, 10:15 AM", datetime(2026, 7, 6, 17, 15, tzinfo=timezone.utc)),
        ("2026-07-06 10:15", datetime(2026, 7, 6, 17, 15, tzinfo=timezone.utc)),
        ("Jul 12 at 6:04 am", datetime(2026, 7, 12, 13, 4, tzinfo=timezone.utc)),
    ],
)
def test_otter_datetime_formats(shown: str, expected: datetime) -> None:
    pacific = timezone(timedelta(hours=-7))
    now = datetime(2026, 7, 28, tzinfo=pacific)
    assert parse_otter_datetime(shown, now=now, local_timezone=pacific) == expected


def test_otter_adapter_errors() -> None:
    with pytest.raises(TranscriptNotFoundError):
        parse_otter_datetime("No timestamp here")
    capture = OtterCapture(" ", "Jul 28 at 1:00 PM", None, "https://otter.ai/u/id")
    with pytest.raises(TranscriptNotFoundError):
        OtterSource(FakeClient(capture)).acquire()


def test_file_cli_success_and_mocked_otter_branch(
    tmp_path: Path, app_paths: ApplicationPaths, monkeypatch
) -> None:
    source = tmp_path / "input.txt"
    source.write_text("file transcript")
    stdout = io.StringIO()
    assert cli.run(["file", str(source)], stdout=stdout, paths=app_paths) == 0
    assert json.loads(stdout.getvalue())["source"]["type"] == "file"

    class FakeOtterSource:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["run_id"]

        def acquire(self) -> AcquiredTranscript:
            return AcquiredTranscript(
                "mock otter", datetime(2026, 1, 1, tzinfo=timezone.utc), Source("otter")
            )

    monkeypatch.setattr(cli, "OtterSource", FakeOtterSource)
    otter_paths = ApplicationPaths(tmp_path / "otter-config.json", tmp_path / "otter-log")
    stdout, stderr = io.StringIO(), io.StringIO()
    assert cli.run(["otter"], stdout=stdout, stderr=stderr, paths=otter_paths) == 0
    assert json.loads(stdout.getvalue())["source"]["type"] == "otter"
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("module", [weave_cli, out_cli])
def test_downstream_rejects_invalid_json_and_unsafe_run(
    module, app_paths: ApplicationPaths
) -> None:
    for text in ("{broken", json.dumps({"run": {"id": "../escape"}}), "[]"):
        stdout, stderr = io.StringIO(), io.StringIO()
        assert (
            module.run(
                ["missing"], stdin=io.StringIO(text), stdout=stdout, stderr=stderr, paths=app_paths
            )
            == 1
        )
        assert stdout.getvalue() == ""
        assert stderr.getvalue()


def test_help_warns_that_debug_artifacts_are_sensitive(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.run(["otter", "--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    assert "--log" in help_text and "--verbose" in help_text
    assert "--debug-artifacts" in help_text
    assert "potentially sensitive" in help_text


def test_repeated_in_process_logging_does_not_duplicate_handlers(
    app_paths: ApplicationPaths,
) -> None:
    for number in range(2):
        assert (
            cli.run(
                ["stdin", "--log"],
                stdin=io.StringIO(f"transcript {number}"),
                paths=app_paths,
            )
            == 0
        )
    logs = list(app_paths.log_directory.glob("*.log"))
    assert len(logs) == 2
    for path in logs:
        content = path.read_text()
        assert content.count("Stage started") == 1
        assert content.count("Stage completed successfully") == 1


def test_trwinp_help_discovers_all_input_methods() -> None:
    help_text = cli.build_parser().format_help()
    assert "stdin" in help_text
    assert "read UTF-8 transcript text from standard input" in help_text
    assert "file" in help_text
    assert "read a UTF-8 text file" in help_text
    assert "otter" in help_text
    assert "acquire the newest visible Otter recording" in help_text


def test_missing_playwright_is_actionable_and_traceback_free(
    app_paths: ApplicationPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transcript_weaver.inp import otter

    original_import_module = otter.importlib.import_module

    def missing_module(name: str) -> object:
        if name == "playwright.sync_api":
            raise ModuleNotFoundError(name)
        return original_import_module(name)

    monkeypatch.setattr(otter.importlib, "import_module", missing_module)
    with pytest.raises(SourceUnavailableError, match="Reinstall or upgrade transcript-weaver"):
        otter._load_playwright()

    class MissingPlaywrightSource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def acquire(self) -> AcquiredTranscript:
            return otter._load_playwright()

    monkeypatch.setattr(cli, "OtterSource", MissingPlaywrightSource)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert cli.run(["otter"], stdout=stdout, stderr=stderr, paths=app_paths) != 0
    assert stdout.getvalue() == ""
    assert "Reinstall or upgrade transcript-weaver" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


@pytest.mark.parametrize(
    ("shown", "expected"),
    [
        ("Today at 5:34 am", datetime(2026, 8, 8, 12, 34, tzinfo=timezone.utc)),
        ("Yesterday at 11:45 PM", datetime(2026, 8, 8, 6, 45, tzinfo=timezone.utc)),
    ],
)
def test_otter_relative_datetime_formats(shown: str, expected: datetime) -> None:
    pacific = timezone(timedelta(hours=-7))
    now = datetime(2026, 8, 8, 18, 0, tzinfo=pacific)
    assert parse_otter_datetime(shown, now=now, local_timezone=pacific) == expected


def test_otter_closes_only_a_browser_it_started() -> None:
    from transcript_weaver.inp.otter import PlaywrightOtterClient

    class Session:
        commands: list[str] = []

        def send(self, command: str) -> None:
            self.commands.append(command)

    class Context:
        pages = [object()]
        session = Session()

        def new_cdp_session(self, page: object) -> Session:
            assert page is self.pages[0]
            return self.session

    class Browser:
        contexts = [Context()]
        disconnected = False

        def close(self) -> None:
            self.disconnected = True

    class Log:
        def info(self, message: str) -> None:
            assert message == "Closed dedicated Otter Chrome profile"

    client = object.__new__(PlaywrightOtterClient)
    client._started_chrome = True
    client._log = Log()
    client._warning = lambda message: pytest.fail(message)
    browser = Browser()
    with client._managed_browser(browser):
        pass
    assert browser.contexts[0].session.commands == ["Browser.close"]
    assert browser.disconnected

    client._started_chrome = False
    browser = Browser()
    with client._managed_browser(browser):
        pass
    assert browser.contexts[0].session.commands == ["Browser.close"]
    assert browser.disconnected


def test_otter_recording_navigation_resolves_relative_href() -> None:
    from transcript_weaver.inp.otter import PlaywrightOtterClient

    class Link:
        def is_visible(self, *, timeout: int) -> bool:
            return True

        def get_attribute(self, name: str) -> str:
            assert name == "href"
            return "/u/recording-id"

        def inner_text(self, *, timeout: int) -> str:
            return "Recording"

    class Links:
        def count(self) -> int:
            return 1

        def nth(self, index: int) -> Link:
            assert index == 0
            return Link()

    class Page:
        url = "https://otter.ai/home"
        visited: str | None = None

        def locator(self, selector: str) -> Links:
            return Links()

        def goto(self, url: str, *, wait_until: str) -> None:
            self.visited = url
            self.url = url

        def wait_for_load_state(self, state: str, *, timeout: int) -> None:
            return None

    client = object.__new__(PlaywrightOtterClient)
    page = Page()
    assert client._open_newest(page) == ("Recording", "https://otter.ai/u/recording-id")
    assert page.visited == "https://otter.ai/u/recording-id"

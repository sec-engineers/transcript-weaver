import io
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from transcript_weaver import browser
from transcript_weaver.browser import DOM_SPEC
from transcript_weaver.inp import dom
from transcript_weaver.inp.errors import SourceUnavailableError
from transcript_weaver.prep import cli as prep_cli
from transcript_weaver.prep import core as prep_core


class FakePage:
    def __init__(self, *, html: str = "<html>current</html>") -> None:
        self.url = "https://www.linkedin.com/in/example"
        self._html = html

    def content(self) -> str:
        return self._html

    def title(self) -> str:
        return "Example Person | LinkedIn"


class PlaywrightManager:
    def __init__(self, contexts: list[object]) -> None:
        browser = SimpleNamespace(contexts=contexts)
        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(connect_over_cdp=lambda endpoint: browser)
        )

    def __enter__(self) -> object:
        return self.playwright

    def __exit__(self, *args: object) -> None:
        return None


def playwright_api(contexts: list[object]) -> object:
    return SimpleNamespace(sync_playwright=lambda: PlaywrightManager(contexts))


def test_dom_source_captures_current_page_without_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage()
    context = SimpleNamespace(pages=[page])
    monkeypatch.setattr(dom, "cdp_ready", lambda endpoint: True)
    instant = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    acquired = dom.DomSource(
        endpoint="http://example:9225",
        clock=lambda: instant,
        playwright_api=playwright_api([context]),
    ).acquire()

    assert acquired.transcript == "<html>current</html>"
    assert acquired.recorded_at == instant
    assert acquired.source.type == "dom"
    assert acquired.source.name == "Example Person | LinkedIn"
    assert acquired.source.reference == "https://www.linkedin.com/in/example"


@pytest.mark.parametrize(
    ("contexts", "message"),
    [([], "exactly one browser context; found 0"), ([object(), object()], "found 2")],
)
def test_dom_source_requires_one_context(
    monkeypatch: pytest.MonkeyPatch, contexts: list[object], message: str
) -> None:
    monkeypatch.setattr(dom, "cdp_ready", lambda endpoint: True)
    with pytest.raises(SourceUnavailableError, match=message):
        dom.DomSource(
            endpoint="http://example:9225", playwright_api=playwright_api(contexts)
        ).acquire()


@pytest.mark.parametrize("count", [0, 2])
def test_dom_source_requires_one_page(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    monkeypatch.setattr(dom, "cdp_ready", lambda endpoint: True)
    context = SimpleNamespace(pages=[FakePage() for _ in range(count)])
    with pytest.raises(SourceUnavailableError, match=rf"exactly one tab; found {count}"):
        dom.DomSource(
            endpoint="http://example:9225", playwright_api=playwright_api([context])
        ).acquire()


def test_dom_source_requires_prepared_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dom, "cdp_ready", lambda endpoint: False)
    with pytest.raises(SourceUnavailableError, match="trwprep dom"):
        dom.DomSource(endpoint="http://example:9225").acquire()


def test_dom_source_rejects_empty_dom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dom, "cdp_ready", lambda endpoint: True)
    context = SimpleNamespace(pages=[FakePage(html=" ")])
    with pytest.raises(Exception, match="current browser DOM is empty"):
        dom.DomSource(
            endpoint="http://example:9225", playwright_api=playwright_api([context])
        ).acquire()


def test_dom_prep_starts_once_and_reuses_running_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts: list[tuple[object, str]] = []
    monkeypatch.setattr(prep_core, "forwarding_ready", lambda spec: True)
    monkeypatch.setattr(prep_core, "cdp_url", lambda spec: "http://example:9225")
    monkeypatch.setattr(prep_core, "selected_profile_path", lambda spec: r"C:\TRW-Chrome-DOM")
    monkeypatch.setattr(
        prep_core,
        "start_chrome",
        lambda spec, profile: starts.append((spec, profile)),
    )
    monkeypatch.setattr(prep_core, "wait_for_cdp", lambda endpoint: None)
    monkeypatch.setattr(
        prep_core,
        "_validate_dom_browser",
        lambda endpoint, playwright_api=None: None,
    )

    stdout = io.StringIO()
    prep_core.prepare_browser("dom", stdin=io.StringIO(), stdout=stdout, ready=lambda _: False)
    assert starts == [(DOM_SPEC, r"C:\TRW-Chrome-DOM")]
    assert "trwinp dom" in stdout.getvalue()

    prep_core.prepare_browser("dom", stdin=io.StringIO(), stdout=stdout, ready=lambda _: True)
    assert len(starts) == 1
    assert "already running" in stdout.getvalue()


def test_prep_requires_consent_before_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prep_core, "forwarding_ready", lambda spec: False)
    monkeypatch.setattr(prep_core, "cdp_url", lambda spec: "http://example:9225")
    monkeypatch.setattr(prep_core, "forwarding_commands", lambda spec: ("netsh example",))
    configured: list[object] = []
    monkeypatch.setattr(prep_core, "configure_forwarding", configured.append)

    stdout = io.StringIO()
    with pytest.raises(SourceUnavailableError, match="not configured"):
        prep_core.prepare_browser(
            "dom", stdin=io.StringIO("no\n"), stdout=stdout, ready=lambda _: False
        )
    assert configured == []
    output = stdout.getvalue()
    assert "Administrator PowerShell" in output
    assert "netsh example" in output
    assert "docs/dom.md" in output
    assert output.index("netsh example") < output.index("Configure the Windows")


def test_prep_configures_forwarding_only_after_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prep_core, "forwarding_ready", lambda spec: False)
    monkeypatch.setattr(prep_core, "forwarding_commands", lambda spec: ("netsh example",))
    configured: list[object] = []
    monkeypatch.setattr(prep_core, "configure_forwarding", configured.append)
    stdout = io.StringIO()
    prep_core._ensure_forwarding(DOM_SPEC, stdin=io.StringIO("yes\n"), stdout=stdout)
    assert configured == [DOM_SPEC]
    assert stdout.getvalue().index("netsh example") < stdout.getvalue().index(
        "Configure the Windows"
    )


@pytest.mark.parametrize(("answer", "expected"), [("\n", r"C:\legacy"), ("no\n", r"C:\new")])
def test_otter_prep_chooses_legacy_profile_with_user_control(
    monkeypatch: pytest.MonkeyPatch, answer: str, expected: str
) -> None:
    monkeypatch.setattr(
        prep_core,
        "profile_path",
        lambda spec, legacy=False: r"C:\legacy" if legacy else r"C:\new",
    )
    monkeypatch.setattr(prep_core, "windows_path_exists", lambda path: path == r"C:\legacy")
    assert (
        prep_core._choose_otter_profile(stdin=io.StringIO(answer), stdout=io.StringIO()) == expected
    )


def test_repeated_otter_prep_reuses_browser_and_shows_otter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(prep_core, "forwarding_ready", lambda spec: True)
    monkeypatch.setattr(prep_core, "cdp_url", lambda spec: "http://example:9223")
    monkeypatch.setattr(
        prep_core,
        "_show_otter",
        lambda endpoint, playwright_api=None: shown.append(endpoint),
    )
    prep_core.prepare_browser(
        "otter", stdin=io.StringIO(), stdout=io.StringIO(), ready=lambda _: True
    )
    assert shown == ["http://example:9223"]


def test_trwprep_cli_help_version_and_error(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    help_text = prep_cli.build_parser().format_help()
    assert "dom" in help_text and "otter" in help_text
    assert "trwprep artifacts {enable,status,disable}" in help_text
    assert max(map(len, help_text.splitlines())) <= 72

    with pytest.raises(SystemExit) as caught:
        prep_cli.run(["--version"])
    assert caught.value.code == 0
    assert "trwprep 1.1.0004" in capsys.readouterr().out

    def fail(*args: object, **kwargs: object) -> None:
        raise SourceUnavailableError("not ready")

    monkeypatch.setattr(prep_cli, "prepare_browser", fail)
    stderr = io.StringIO()
    assert prep_cli.run(["dom"], stderr=stderr) == 1
    assert stderr.getvalue() == "trwprep: not ready\n"


def test_trwprep_artifact_permission_workflow(tmp_path) -> None:
    from transcript_weaver.config import ApplicationPaths

    paths = ApplicationPaths(tmp_path / "config.json", tmp_path / "log", tmp_path / "runtime")
    stdout = io.StringIO()
    assert (
        prep_cli.run(
            ["artifacts", "enable"], stdin=io.StringIO("yes\n"), stdout=stdout, paths=paths
        )
        == 0
    )
    assert "WARNING" in stdout.getvalue()
    assert "one hour" in stdout.getvalue()
    warning = stdout.getvalue().split("Permit --debug-artifacts", 1)[0]
    assert max(map(len, warning.splitlines())) <= 72
    assert (tmp_path / "runtime" / "debug-artifacts-permission.json").exists()

    extended = io.StringIO()
    assert (
        prep_cli.run(["artifacts", "enable"], stdin=io.StringIO(), stdout=extended, paths=paths)
        == 0
    )
    assert "extended for one hour" in extended.getvalue()
    assert "WARNING" not in extended.getvalue()
    assert "[y/N]" not in extended.getvalue()

    status = io.StringIO()
    assert prep_cli.run(["artifacts", "status"], stdout=status, paths=paths) == 0
    assert "is enabled" in status.getvalue()
    assert "Expires:" in status.getvalue()

    disabled = io.StringIO()
    assert prep_cli.run(["artifacts", "disable"], stdout=disabled, paths=paths) == 0
    assert "permission disabled" in disabled.getvalue()


def test_browser_specs_and_forwarding_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DOM_SPEC.profile_name == "TRW-Chrome-DOM"
    assert "Transcript%20Weaver%20DOM%20Browser" in DOM_SPEC.start_url
    proxy_dump = (
        "add v4tov4 listenport=9225 listenaddress=172.20.0.1 "
        "connectaddress=127.0.0.1 connectport=9224\n"
    )
    monkeypatch.setattr(
        browser,
        "_run_text",
        lambda command: subprocess.CompletedProcess(command, 0, proxy_dump, ""),
    )
    assert browser.port_proxy_ready(DOM_SPEC)

    monkeypatch.setattr(
        browser,
        "_run_text",
        lambda command: subprocess.CompletedProcess(
            command,
            0,
            "\n".join(
                (
                    "Enabled: Yes",
                    "Direction: In",
                    "LocalIP: 172.20.0.1/32",
                    "RemoteIP: 172.20.0.2/32",
                    "Protocol: TCP",
                    "LocalPort: 9225",
                    "Action: Allow",
                )
            ),
            "",
        ),
    )
    monkeypatch.setattr(browser, "windows_host_ip", lambda: "172.20.0.1")
    monkeypatch.setattr(browser, "wsl_ip", lambda: "172.20.0.2")
    assert browser.firewall_ready(DOM_SPEC)


def test_profile_selection_and_chrome_start_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser, "windows_local_appdata", lambda: r"C:\Users\u\AppData\Local")
    monkeypatch.setattr(browser, "windows_path_exists", lambda path: False)
    assert browser.selected_profile_path(DOM_SPEC).endswith(r"\TRW-Chrome-DOM")
    with pytest.raises(SourceUnavailableError, match="no legacy"):
        browser.profile_path(DOM_SPEC, legacy=True)

    commands: list[list[str]] = []
    monkeypatch.setattr(browser, "chrome_executable", lambda: "chrome.exe")
    monkeypatch.setattr(
        browser.subprocess,
        "Popen",
        lambda command, **kwargs: commands.append(command),
    )
    browser.start_chrome(DOM_SPEC, profile=r"C:\TRW-Chrome-DOM")
    assert "--remote-debugging-port=9224" in commands[0]
    assert "--remote-debugging-address=127.0.0.1" in commands[0]
    assert commands[0][-1].startswith("data:text/html")


def test_show_otter_reuses_existing_page() -> None:
    class Page:
        url = "https://otter.ai/home"
        front = False

        def bring_to_front(self) -> None:
            self.front = True

    page = Page()
    context = SimpleNamespace(pages=[page])
    prep_core._show_otter("http://example:9223", playwright_api=playwright_api([context]))
    assert page.front


def test_dom_prep_validation_rejects_extra_tabs() -> None:
    context = SimpleNamespace(pages=[FakePage(), FakePage()])
    with pytest.raises(SourceUnavailableError, match="exactly one tab; found 2"):
        prep_core._validate_dom_browser(
            "http://example:9225", playwright_api=playwright_api([context])
        )

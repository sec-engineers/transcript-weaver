import re
from pathlib import Path

from transcript_weaver import __version__

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 test environment
    import tomli as tomllib


def test_playwright_is_a_standard_dependency_without_otter_extra() -> None:
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert "playwright>=1.45,<2" in project["dependencies"]
    assert "otter" not in project.get("optional-dependencies", {})
    assert "all" not in project.get("optional-dependencies", {})


def test_project_version_has_one_dynamic_source_and_packet_format() -> None:
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as stream:
        data = tomllib.load(stream)

    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["hatch"]["version"]["path"] == ("src/transcript_weaver/_version.py")
    assert re.fullmatch(r"\d+\.\d+\.\d{4}", __version__)
    assert (project_root / "src/transcript_weaver/_version.py").read_text().count(__version__) == 1

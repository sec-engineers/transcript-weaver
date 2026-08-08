from pathlib import Path

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

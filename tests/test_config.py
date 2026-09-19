import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_test_markers() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    marker_names = [m.split(":")[0].strip() for m in markers]
    assert "gpu" in marker_names
    assert "llm" in marker_names


def test_workspace_members_have_a_pyproject() -> None:
    for pkg_dir in sorted((ROOT / "packages").iterdir()):
        if pkg_dir.is_dir():
            assert (pkg_dir / "pyproject.toml").is_file(), f"{pkg_dir.name} manca pyproject.toml"

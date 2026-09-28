import tomllib
from pathlib import Path

import pytest
from perception.config import BASE, CameraType, Mode, load_config
from pydantic import ValidationError

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


CONFIG_DIR = ROOT / "config"
OVERLAYS = sorted(p.stem for p in CONFIG_DIR.glob("*.yaml") if p.stem != BASE)


def test_config_dir_has_base_and_overlays() -> None:
    assert (CONFIG_DIR / f"{BASE}.yaml").is_file()
    assert {"broadcast", "fixed", "live"} <= set(OVERLAYS)


def test_base_config_is_valid() -> None:
    cfg = load_config(CONFIG_DIR)
    assert (cfg.camera, cfg.mode) == (CameraType.BROADCAST, Mode.BATCH)


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_overlay_validates_against_the_schema(overlay: str) -> None:
    load_config(CONFIG_DIR, overlay)


def test_fixed_overlay_selects_the_fixed_camera() -> None:
    assert load_config(CONFIG_DIR, "fixed").camera == CameraType.TACTICAL_FIXED


def test_live_overlay_lowers_fps_and_disables_ball_tiling() -> None:
    cfg = load_config(CONFIG_DIR, "fixed", "live")
    assert (cfg.camera, cfg.mode, cfg.sample_fps, cfg.ball_tiling) == (
        CameraType.TACTICAL_FIXED,
        Mode.LIVE,
        5,
        False,
    )


def test_overlay_cannot_introduce_unknown_keys(tmp_path: Path) -> None:
    (tmp_path / f"{BASE}.yaml").write_text((CONFIG_DIR / f"{BASE}.yaml").read_text())
    (tmp_path / "typo.yaml").write_text("sample_fsp: 5\n")
    with pytest.raises(ValidationError, match="sample_fsp"):
        load_config(tmp_path, "typo")


def test_unknown_overlay_is_an_error() -> None:
    with pytest.raises(FileNotFoundError):
        load_config(CONFIG_DIR, "nope")

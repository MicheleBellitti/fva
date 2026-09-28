"""Costruisce i DAG su ogni combinazione di config. È il guardiano contro gli errori di nome."""

import inspect
import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from hamilton import driver
from perception import dataflow as perception
from perception.config import Mode, PipelineConfig, load_config

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"

# camera x modo: ogni combinazione che il worker può ricevere
COMBINATIONS = [("broadcast",), ("fixed",), ("broadcast", "live"), ("fixed", "live")]

# nodo → task del piano che lo implementa (docs/technical-design.md §4, docs/index.html)
PERCEPTION_NODES = {
    "frames": "P1.1",
    "shot_boundaries": "P1.2",
    "shot_segments": "P1.3",
    "tactical_frames": "P1.4",
    "detections_full": "P1.7",
    "detections_ball": "P1.8",
    "detections": "P1.8",
    "tracks_raw": "P1.9",
    "player_crops": "P1.10",
    "team_labels": "P1.10",
    "pitch_keypoints": "P1.11",
    "homography_raw": "P1.11",
    "homography": "P1.11",
    "homography_acceptance_rate": "P1.12",
    "pitch_tracks": "P1.13",
    "max_player_speed_kmh": "P1.12",
    "pitch_tracks_parquet": "P1.13",
}

PERCEPTION_INPUTS = {
    "video_uri",
    "detector",
    "tracker_cfg",
    "siglip",
    "kp_model",
    "team_orientation",
    "clock_alignment",
    "match_id",
    "pipeline_version",
    "tracks_root",
}


def build(module: ModuleType, cfg: PipelineConfig) -> driver.Driver:
    return driver.Builder().with_modules(module).with_config(cfg.model_dump(mode="json")).build()


def node_names(dr: driver.Driver) -> set[str]:
    return {v.name for v in dr.list_available_variables()}


def external_inputs(dr: driver.Driver, cfg: PipelineConfig) -> set[str]:
    externals = {v.name for v in dr.list_available_variables() if v.is_external_input}
    return externals - set(cfg.model_dump())


def resolved_function(dr: driver.Driver, name: str) -> Callable[..., object]:
    (var,) = (v for v in dr.list_available_variables() if v.name == name)
    return var.originating_functions[0]


def call_stub(fn: Callable[..., object]) -> None:
    fn(**dict.fromkeys(inspect.signature(fn).parameters))


@pytest.fixture(params=COMBINATIONS, ids="+".join)
def cfg(request: pytest.FixtureRequest) -> PipelineConfig:
    return load_config(CONFIG_DIR, *request.param)


class TestPerceptionDag:
    def test_builds_with_every_node(self, cfg: PipelineConfig) -> None:
        assert set(PERCEPTION_NODES) <= node_names(build(perception, cfg))

    def test_external_inputs_are_exactly_the_expected_ones(self, cfg: PipelineConfig) -> None:
        assert external_inputs(build(perception, cfg), cfg) == PERCEPTION_INPUTS

    def test_homography_smoothing_follows_mode(self, cfg: PipelineConfig) -> None:
        expected = (
            perception.homography__live if cfg.mode is Mode.LIVE else perception.homography__batch
        )
        assert resolved_function(build(perception, cfg), "homography") is expected

    def test_ball_detection_follows_tiling(self, cfg: PipelineConfig) -> None:
        expected = (
            perception.detections_ball__tiled
            if cfg.ball_tiling
            else perception.detections_ball__untiled
        )
        assert resolved_function(build(perception, cfg), "detections_ball") is expected

    def test_sanity_checks_are_attached(self, cfg: PipelineConfig) -> None:
        validators = {
            "homography_acceptance_rate_range_validator",
            "max_player_speed_kmh_range_validator",
        }
        assert validators <= node_names(build(perception, cfg))


PERCEPTION_STUBS = [
    *((name, task) for name, task in PERCEPTION_NODES.items() if hasattr(perception, name)),
    ("detections_ball__tiled", "P1.8"),
    ("detections_ball__untiled", "P1.8"),
    ("homography__batch", "P1.11"),
    ("homography__live", "P1.11"),
]


@pytest.mark.parametrize(("name", "task"), PERCEPTION_STUBS)
def test_perception_stub_names_its_task(name: str, task: str) -> None:
    with pytest.raises(NotImplementedError, match=re.escape(task)):
        call_stub(getattr(perception, name))

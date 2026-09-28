"""Costruisce i DAG su ogni combinazione di config: è il guardiano contro gli errori di nome."""

import inspect
from pathlib import Path
from types import ModuleType

import pytest
from derivation import dataflow as derivation
from hamilton import driver
from hamilton.graph_types import HamiltonNode
from perception import dataflow as perception
from perception.config import Mode, PipelineConfig, load_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Ogni combinazione camera x modo che il worker può ricevere.
COMBINATIONS = [("broadcast",), ("fixed",), ("broadcast", "live"), ("fixed", "live")]

# Funzione → task del piano che la implementa (docs/technical-design.md §4, docs/index.html).
# Le varianti `nodo__variante` diventano un solo nodo `nodo` nel grafo.
PERCEPTION_STUBS = {
    "frames": "P1.1",
    "shot_boundaries": "P1.2",
    "shot_segments": "P1.3",
    "tactical_frames": "P1.4",
    "detections_full": "P1.7",
    "detections_ball__tiled": "P1.8",
    "detections_ball__untiled": "P1.8",
    "detections": "P1.8",
    "tracks_raw": "P1.9",
    "player_crops": "P1.10",
    "team_labels": "P1.10",
    "pitch_keypoints": "P1.11",
    "homography_raw": "P1.11",
    "homography__batch": "P1.11",
    "homography__live": "P1.11",
    "homography_acceptance_rate": "P1.12",
    "pitch_tracks": "P1.13",
    "max_player_speed_kmh": "P1.12",
    "pitch_tracks_parquet": "P1.13",
}

DERIVATION_STUBS = {
    "ball_track": "P2.1",
    "ball_carrier": "P2.2",
    "possessions": "P2.3",
    "possessions_fallback": "P2.10",
    "possessions_merged": "P2.10",
    "team_shape": "P2.8",
    "events_geometric": "P2.5",
    "events_statistical": "P2.9",
    "events": "P2.6",
    "team_metrics": "P3.1",
    "event_embeddings": "P3.2",
    "persist": "P2.6",
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

DERIVATION_INPUTS = {"pitch_tracks", "registry", "text_embedder", "engine", "pipeline_version"}

type Dag = dict[str, HamiltonNode]


def build(module: ModuleType, cfg: PipelineConfig) -> Dag:
    dr = driver.Builder().with_modules(module).with_config(cfg.model_dump(mode="json")).build()
    return {node.name: node for node in dr.list_available_variables()}


def node_names(stubs: dict[str, str]) -> set[str]:
    return {name.split("__")[0] for name in stubs}


def external_inputs(dag: Dag, cfg: PipelineConfig) -> set[str]:
    # Hamilton elenca anche i valori di config tra gli input esterni: non sono dati da passare.
    return {name for name, node in dag.items() if node.is_external_input} - set(cfg.model_dump())


def resolved_function(dag: Dag, node: str) -> object:
    """La funzione che `@config.when` ha scelto per il nodo."""
    functions = dag[node].originating_functions
    assert functions is not None
    return functions[0]


def functions_of(module: ModuleType) -> set[str]:
    return {
        name
        for name, fn in inspect.getmembers(module, inspect.isfunction)
        if fn.__module__ == module.__name__
    }


def assert_stub_raises(module: ModuleType, name: str, task: str) -> None:
    stub = getattr(module, name)
    # Gli stub sollevano prima di toccare gli argomenti: None va bene per tutti.
    with pytest.raises(NotImplementedError) as exc:
        stub(**dict.fromkeys(inspect.signature(stub).parameters))
    assert str(exc.value) == task


@pytest.fixture(params=COMBINATIONS, ids="+".join)
def cfg(request: pytest.FixtureRequest) -> PipelineConfig:
    return load_config(CONFIG_DIR, *request.param)


@pytest.fixture
def perception_dag(cfg: PipelineConfig) -> Dag:
    return build(perception, cfg)


@pytest.fixture
def derivation_dag(cfg: PipelineConfig) -> Dag:
    return build(derivation, cfg)


class TestPerceptionDag:
    def test_has_every_node(self, perception_dag: Dag) -> None:
        assert node_names(PERCEPTION_STUBS) <= perception_dag.keys()

    def test_external_inputs(self, perception_dag: Dag, cfg: PipelineConfig) -> None:
        assert external_inputs(perception_dag, cfg) == PERCEPTION_INPUTS

    def test_homography_follows_mode(self, perception_dag: Dag, cfg: PipelineConfig) -> None:
        if cfg.mode is Mode.LIVE:
            expected = perception.homography__live
        else:
            expected = perception.homography__batch
        assert resolved_function(perception_dag, "homography") is expected

    def test_ball_detection_follows_tiling(self, perception_dag: Dag, cfg: PipelineConfig) -> None:
        if cfg.ball_tiling:
            expected = perception.detections_ball__tiled
        else:
            expected = perception.detections_ball__untiled
        assert resolved_function(perception_dag, "detections_ball") is expected

    def test_sanity_checks_are_attached(self, perception_dag: Dag) -> None:
        validators = {
            "homography_acceptance_rate_range_validator",
            "max_player_speed_kmh_range_validator",
        }
        assert validators <= perception_dag.keys()


class TestDerivationDag:
    def test_has_every_node(self, derivation_dag: Dag) -> None:
        assert node_names(DERIVATION_STUBS) <= derivation_dag.keys()

    def test_external_inputs(self, derivation_dag: Dag, cfg: PipelineConfig) -> None:
        assert external_inputs(derivation_dag, cfg) == DERIVATION_INPUTS


@pytest.mark.parametrize(
    ("module", "stubs"),
    [(perception, PERCEPTION_STUBS), (derivation, DERIVATION_STUBS)],
    ids=["perception", "derivation"],
)
def test_every_function_has_a_task(module: ModuleType, stubs: dict[str, str]) -> None:
    assert functions_of(module) == stubs.keys()


@pytest.mark.parametrize(("name", "task"), PERCEPTION_STUBS.items())
def test_perception_stub_names_its_task(name: str, task: str) -> None:
    assert_stub_raises(perception, name, task)


@pytest.mark.parametrize(("name", "task"), DERIVATION_STUBS.items())
def test_derivation_stub_names_its_task(name: str, task: str) -> None:
    assert_stub_raises(derivation, name, task)

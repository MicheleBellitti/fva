import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from core.models.enums import (
    CameraType,
    EvalCaseStatus,
    EvalKind,
    EventSource,
    EventStatus,
    EventType,
    JobKind,
    JobStatus,
    MatchStatus,
    MetricName,
    PossessionOutcome,
    PossessionSource,
    Team,
    TeamSide,
    ViewType,
)
from core.models.models import (
    EvalCase,
    EvalRun,
    Event,
    EventEmbedding,
    Feedback,
    Job,
    Match,
    PipelineRun,
    Possession,
    TeamMetric,
    TeamOrientation,
    VideoSegment,
)
from pydantic import ValidationError


def sample_match_data() -> dict[str, Any]:
    return {
        "id": "m_2026_09_12_nap_juv",
        "competition": "Serie A",
        "date": date(2026, 9, 12),
        "home_team": "Napoli",
        "away_team": "Juventus",
        "team_a_side": TeamSide.HOME,
        "video_uri": "s3://fva/video/m_2026_09_12_nap_juv/source.mp4",
        "hls_uri": "s3://fva/video/m_2026_09_12_nap_juv/hls/playlist.m3u8",
        "duration_s": 5400.0,
        "fps": 25.0,
        "camera_type": CameraType.BROADCAST,
        "half1_kickoff_s": 10.0,
        "half1_end_s": 2710.0,
        "half2_kickoff_s": 3600.0,
        "half2_end_s": 5350.0,
        "status": MatchStatus.READY,
        "active_pipeline_version": "v1.0.0",
        "created_at": datetime.now(UTC),
    }


def sample_team_orientation_data() -> dict[str, Any]:
    return {
        "match_id": "m_2026_09_12_nap_juv",
        "team": Team.A,
        "half": 1,
        "attack_direction": 1,
    }


def sample_video_segment_data() -> dict[str, Any]:
    return {
        "match_id": "m_2026_09_12_nap_juv",
        "pipeline_version": "synth-v1",
        "t_start": 0.0,
        "t_end": 4.0,
        "view_type": ViewType.TACTICAL,
        "usable": True,
        "half": 1,
        "clock_start": 0.0,
        "clock_end": 4.0,
    }


def sample_possession_data() -> dict[str, Any]:
    return {
        "id": "pos_abc123",
        "match_id": "m_2026_09_12_nap_juv",
        "pipeline_version": "synth-v1",
        "team": Team.A,
        "t_start": 10.0,
        "t_end": 25.0,
        "half": 1,
        "clock_start": 0.0,
        "clock_end": 15.0,
        "x_start": 20.0,
        "y_start": 30.0,
        "x_end": 50.0,
        "y_end": 40.0,
        "outcome": PossessionOutcome.SHOT,
        "n_passes": 4,
        "source": PossessionSource.BALL,
        "confidence": 0.85,
    }


def sample_event_data() -> dict[str, Any]:
    return {
        "id": "evt_abc123def456",
        "match_id": "m_2026_09_12_nap_juv",
        "pipeline_version": "synth-v1",
        "type": EventType.SHOT,
        "team": Team.A,
        "t_video": 25.0,
        "t_end": 27.0,
        "half": 1,
        "match_clock": 15.0,
        "x_pitch": 89.0,
        "y_pitch": 34.0,
        "attrs": {"xg": 0.25},
        "confidence": 0.95,
        "source": EventSource.DETECTOR,
        "status": EventStatus.CONFIRMED,
        "revision": 1,
    }


def sample_team_metric_data() -> dict[str, Any]:
    return {
        "match_id": "m_2026_09_12_nap_juv",
        "pipeline_version": "synth-v1",
        "team": Team.A,
        "half": 1,
        "window_start": 0.0,
        "window_end": 300.0,
        "metric": MetricName.DEFENSIVE_LINE_HEIGHT,
        "value": 45.2,
        "coverage": 0.9,
    }


def sample_event_embedding_data() -> dict[str, Any]:
    return {
        "event_id": "evt_abc123def456",
        "pipeline_version": "synth-v1",
        "model": "clip-base-v1",
        "embedding": [0.01] * 768,
    }


def sample_job_data() -> dict[str, Any]:
    return {
        "id": 1,
        "match_id": "m_2026_09_12_nap_juv",
        "kind": JobKind.INGEST,
        "status": JobStatus.QUEUED,
        "params": {},
        "attempts": 0,
        "created_at": datetime.now(UTC),
    }


def sample_pipeline_run_data() -> dict[str, Any]:
    return {
        "id": 1,
        "run_id": uuid.uuid4(),
        "job_id": 1,
        "match_id": "m_2026_09_12_nap_juv",
        "pipeline_version": "synth-v1",
        "node": "pitch_tracks",
        "started_at": datetime.now(UTC),
        "duration_s": 12.5,
        "ok": True,
        "rows_out": 1000,
        "checks": [{"name": "speed", "passed": True}],
        "config": {"sample_fps": 10},
    }


def sample_feedback_data() -> dict[str, Any]:
    return {
        "id": 1,
        "ts": datetime.now(UTC),
        "conversation_id": "conv_123",
        "turn": 0,
        "query_text": "Quanti tiri ha fatto il Napoli?",
        "structured_query": {"type": "shot"},
        "returned_event_ids": ["evt_abc123def456"],
        "rating": 1,
        "note": "Ottima risposta",
    }


def sample_eval_case_data() -> dict[str, Any]:
    return {
        "case_id": "case_shots_001",
        "kind": EvalKind.ASSISTANT,
        "status": EvalCaseStatus.ACTIVE,
        "input": {"query": "tiri primo tempo"},
        "expected": {"count": 5},
        "content_hash": "sha256_dummy",
        "created_at": datetime.now(UTC),
    }


def sample_eval_run_data() -> dict[str, Any]:
    return {
        "run_id": uuid.uuid4(),
        "case_id": "case_shots_001",
        "content_hash": "sha256_dummy",
        "git_sha": "abc1234",
        "pipeline_version": "synth-v1",
        "started_at": datetime.now(UTC),
        "score": 1.0,
        "passed": True,
        "details": {},
    }


MODELS_AND_SAMPLES: list[tuple[type, dict[str, Any]]] = [
    (Match, sample_match_data()),
    (TeamOrientation, sample_team_orientation_data()),
    (VideoSegment, sample_video_segment_data()),
    (Possession, sample_possession_data()),
    (Event, sample_event_data()),
    (TeamMetric, sample_team_metric_data()),
    (EventEmbedding, sample_event_embedding_data()),
    (Job, sample_job_data()),
    (PipelineRun, sample_pipeline_run_data()),
    (Feedback, sample_feedback_data()),
    (EvalCase, sample_eval_case_data()),
    (EvalRun, sample_eval_run_data()),
]


@pytest.mark.parametrize(("model_cls", "sample_data"), MODELS_AND_SAMPLES)
def test_models_round_trip(model_cls: type, sample_data: dict[str, Any]) -> None:
    instance = model_cls(**sample_data)
    dumped = instance.model_dump()
    restored = model_cls(**dumped)
    assert instance == restored


@pytest.mark.parametrize(("model_cls", "sample_data"), MODELS_AND_SAMPLES)
def test_models_reject_extra_fields(model_cls: type, sample_data: dict[str, Any]) -> None:
    data_with_extra = dict(sample_data)
    data_with_extra["unexpected_extra_field"] = "bad_value"
    with pytest.raises(ValidationError) as exc_info:
        model_cls(**data_with_extra)
    assert "unexpected_extra_field" in str(exc_info.value)


def test_event_pre_m4_invariant() -> None:
    data = sample_event_data()
    data["status"] = EventStatus.PROVISIONAL
    with pytest.raises(ValidationError, match="confirmed"):
        Event(**data)

    data = sample_event_data()
    data["revision"] = 2
    with pytest.raises(ValidationError, match="revision"):
        Event(**data)


def test_possession_fallback_invariants() -> None:
    data = sample_possession_data()
    data["source"] = PossessionSource.FALLBACK
    data["n_passes"] = 2
    with pytest.raises(ValidationError, match="n_passes"):
        Possession(**data)

    data["n_passes"] = None
    data["confidence"] = 0.8
    with pytest.raises(ValidationError, match=r"0\.4"):
        Possession(**data)

    data["confidence"] = 0.4
    pos = Possession(**data)
    assert pos.confidence == 0.4


def test_team_metric_coverage_value_invariant() -> None:
    data = sample_team_metric_data()
    data["coverage"] = 0.0
    data["value"] = 12.0
    with pytest.raises(ValidationError, match="value deve essere NULL"):
        TeamMetric(**data)

    data["value"] = None
    metric = TeamMetric(**data)
    assert metric.value is None


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf")])
def test_models_reject_nan_and_inf(bad_val: float) -> None:
    data = sample_event_data()
    data["t_end"] = bad_val
    with pytest.raises(ValidationError) as exc_info:
        Event(**data)
    assert any(err["type"] == "finite_number" for err in exc_info.value.errors())

    metric_data = sample_team_metric_data()
    metric_data["value"] = bad_val
    with pytest.raises(ValidationError) as exc_info:
        TeamMetric(**metric_data)
    assert any(err["type"] == "finite_number" for err in exc_info.value.errors())

    segment_data = sample_video_segment_data()
    segment_data["t_end"] = bad_val
    with pytest.raises(ValidationError) as exc_info:
        VideoSegment(**segment_data)
    assert any(err["type"] == "finite_number" for err in exc_info.value.errors())


@pytest.mark.parametrize("invalid_half", [0, 3, -1])
def test_models_reject_invalid_half(invalid_half: int) -> None:
    data_event = sample_event_data()
    data_event["half"] = invalid_half
    with pytest.raises(ValidationError):
        Event(**data_event)

    data_orient = sample_team_orientation_data()
    data_orient["half"] = invalid_half
    with pytest.raises(ValidationError):
        TeamOrientation(**data_orient)

    data_seg = sample_video_segment_data()
    data_seg["half"] = invalid_half
    with pytest.raises(ValidationError):
        VideoSegment(**data_seg)

    data_pos = sample_possession_data()
    data_pos["half"] = invalid_half
    with pytest.raises(ValidationError):
        Possession(**data_pos)

    data_metric = sample_team_metric_data()
    data_metric["half"] = invalid_half
    with pytest.raises(ValidationError):
        TeamMetric(**data_metric)


@pytest.mark.parametrize("invalid_pv", ["Synth V1", "invalid/version", "", "_pv", "pv with spaces"])
def test_models_reject_invalid_pipeline_version(invalid_pv: str) -> None:
    data_event = sample_event_data()
    data_event["pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        Event(**data_event)

    data_match = sample_match_data()
    data_match["active_pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        Match(**data_match)

    data_seg = sample_video_segment_data()
    data_seg["pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        VideoSegment(**data_seg)

    data_pos = sample_possession_data()
    data_pos["pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        Possession(**data_pos)

    data_metric = sample_team_metric_data()
    data_metric["pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        TeamMetric(**data_metric)

    data_emb = sample_event_embedding_data()
    data_emb["pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        EventEmbedding(**data_emb)

    data_run = sample_pipeline_run_data()
    data_run["pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        PipelineRun(**data_run)

    data_eval = sample_eval_run_data()
    data_eval["pipeline_version"] = invalid_pv
    with pytest.raises(ValidationError):
        EvalRun(**data_eval)


@pytest.mark.parametrize("invalid_id", ["p_1", "pos_", "pos-123", "POS_123", ""])
def test_possession_rejects_invalid_id(invalid_id: str) -> None:
    data = sample_possession_data()
    data["id"] = invalid_id
    with pytest.raises(ValidationError):
        Possession(**data)


def test_match_ready_invariant() -> None:
    data = sample_match_data()
    data["status"] = MatchStatus.READY
    data["active_pipeline_version"] = None
    with pytest.raises(ValidationError, match="status ready richiede active_pipeline_version"):
        Match(**data)

    data = sample_match_data()
    data["status"] = MatchStatus.READY
    data["active_pipeline_version"] = "synth-v1"
    data["half1_kickoff_s"] = None
    data["half1_end_s"] = None
    data["half2_kickoff_s"] = None
    data["half2_end_s"] = None
    with pytest.raises(ValidationError, match="status ready richiede active_pipeline_version"):
        Match(**data)


def test_team_metric_window_start_non_negative() -> None:
    data = sample_team_metric_data()
    data["window_start"] = -0.5
    with pytest.raises(ValidationError):
        TeamMetric(**data)


@pytest.mark.parametrize("invalid_attempts", [-1, 32768, 40000])
def test_job_attempts_bounds(invalid_attempts: int) -> None:
    data = sample_job_data()
    data["attempts"] = invalid_attempts
    data["locked_at"] = datetime.now(UTC)
    data["finished_at"] = datetime.now(UTC)
    with pytest.raises(ValidationError):
        Job(**data)


def test_model_table_parity_structural() -> None:
    from core.models.tables import PIPELINE_VERSION_PATTERN, metadata
    from sqlalchemy import CheckConstraint

    # Table -> Model map
    table_to_model = {
        "matches": Match,
        "team_orientation": TeamOrientation,
        "video_segments": VideoSegment,
        "possessions": Possession,
        "events": Event,
        "team_metrics": TeamMetric,
        "event_embeddings": EventEmbedding,
        "jobs": Job,
        "pipeline_runs": PipelineRun,
        "eval_runs": EvalRun,
    }

    for table_name, model_cls in table_to_model.items():
        tbl = metadata.tables[table_name]
        check_texts = [str(c.sqltext) for c in tbl.constraints if isinstance(c, CheckConstraint)]

        # Check half IN (1, 2) parity
        if any("half IN (1, 2)" in ct for ct in check_texts):
            field = model_cls.model_fields["half"]
            # annotation should be Literal[1, 2] or Literal[1, 2] | None
            ann_str = str(field.annotation)
            assert "Literal[1, 2]" in ann_str, f"{model_cls.__name__}.half missing Literal[1, 2]"

        # Check pipeline_version regex parity
        if any("pipeline_version ~" in ct for ct in check_texts):
            field = model_cls.model_fields["pipeline_version"]
            patterns = [getattr(m, "pattern", None) for m in field.metadata]
            assert PIPELINE_VERSION_PATTERN in patterns, (
                f"{model_cls.__name__}.pipeline_version does not match PIPELINE_VERSION_PATTERN"
            )

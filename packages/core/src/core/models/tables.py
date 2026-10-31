"""SQLAlchemy 2 Core table definitions — the single source of truth for DDL.

schema.md §5 is translated here 1:1.  No ORM.  No logic.
Alembic (env.py) imports `metadata` for autogenerate.  Migrations import nothing
from here: their values are frozen, and tests/test_tables.py checks they match.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any

from sqlalchemy import (
    ARRAY,
    REAL,
    BigInteger,
    BindParameter,
    Boolean,
    CheckConstraint,
    Column,
    ColumnElement,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    cast,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.types import UserDefinedType

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

# ---------------------------------------------------------------------------
# pgvector custom type
# ---------------------------------------------------------------------------


PIPELINE_VERSION_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"  # schema.md §5.0
EMBEDDING_DIM = 768  # schema.md §5.7


class Vector(UserDefinedType[list[float]]):
    """pgvector `vector(N)`: list[float] in Python, '[x,y,...]' text on the wire."""

    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dim})"

    def bind_expression(self, bindvalue: BindParameter[list[float]]) -> ColumnElement[list[float]]:
        # The value travels as text: cast it so `<=>` & co. resolve on every driver.
        return cast(bindvalue, self)

    # Callable[..., X]: SQLAlchemy's processor protocols call the argument `value`.
    def bind_processor(self, dialect: Dialect) -> Callable[..., str | None]:
        def process(value: list[float] | None) -> str | None:
            return None if value is None else "[" + ",".join(map(str, value)) + "]"

        return process

    def result_processor(
        self, dialect: Dialect, coltype: object
    ) -> Callable[..., list[float] | None]:
        def process(value: str | None) -> list[float] | None:
            return None if value is None else [float(x) for x in value[1:-1].split(",")]

        return process


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_vals(enum_cls: type[Enum]) -> str:
    """Build `'a', 'b', 0, 1` literal list from an Enum for CHECK constraints.

    schema.md D12: text + CHECK, not CREATE TYPE.
    """
    parts: list[str] = []
    for member in enum_cls:
        if isinstance(member.value, str):
            parts.append(f"'{member.value}'")
        else:
            parts.append(str(member.value))
    return ", ".join(parts)


_PV_CHECK = f"pipeline_version ~ '{PIPELINE_VERSION_PATTERN}'"

# float4 is a Python float; without the type argument pyright sees REAL[Unknown].
_REAL: REAL[float] = REAL()


# ---------------------------------------------------------------------------
# Shared MetaData — imported by env.py as target_metadata
# ---------------------------------------------------------------------------

metadata = MetaData()


# ---------------------------------------------------------------------------
# 5.1 matches
# ---------------------------------------------------------------------------

matches = Table(
    "matches",
    metadata,
    Column("id", Text, primary_key=True),
    Column("competition", Text, nullable=True),
    Column("date", Date, nullable=False),
    Column("home_team", Text, nullable=False),
    Column("away_team", Text, nullable=False),
    Column("team_a_side", Text, nullable=False),
    Column("video_uri", Text, nullable=False),
    Column("hls_uri", Text, nullable=False),
    Column("duration_s", _REAL, nullable=False),
    Column("fps", _REAL, nullable=False),
    Column("camera_type", Text, nullable=False),
    Column("half1_kickoff_s", _REAL, nullable=True),
    Column("half1_end_s", _REAL, nullable=True),
    Column("half2_kickoff_s", _REAL, nullable=True),
    Column("half2_end_s", _REAL, nullable=True),
    Column("status", Text, nullable=False, server_default=MatchStatus.QUEUED.value),
    Column("active_pipeline_version", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("id ~ '^m_[a-z0-9_]{1,62}$'", name="ck_matches_id_pattern"),
    CheckConstraint(f"team_a_side IN ({_check_vals(TeamSide)})", name="ck_matches_team_a_side"),
    CheckConstraint("duration_s > 0", name="ck_matches_duration_s"),
    CheckConstraint("fps > 0", name="ck_matches_fps"),
    CheckConstraint(f"camera_type IN ({_check_vals(CameraType)})", name="ck_matches_camera_type"),
    CheckConstraint(f"status IN ({_check_vals(MatchStatus)})", name="ck_matches_status"),
    CheckConstraint(
        # all NULL or all set with the ordering invariant
        "(half1_kickoff_s IS NULL AND half1_end_s IS NULL"
        " AND half2_kickoff_s IS NULL AND half2_end_s IS NULL)"
        " OR ("
        "half1_kickoff_s IS NOT NULL AND half1_end_s IS NOT NULL"
        " AND half2_kickoff_s IS NOT NULL AND half2_end_s IS NOT NULL"
        " AND 0 <= half1_kickoff_s"
        " AND half1_kickoff_s < half1_end_s"
        " AND half1_end_s <= half2_kickoff_s"
        " AND half2_kickoff_s < half2_end_s"
        " AND half2_end_s <= duration_s)",
        name="ck_matches_halves_valid",
    ),
    CheckConstraint(
        f"status != '{MatchStatus.READY.value}'"
        " OR (active_pipeline_version IS NOT NULL AND half1_kickoff_s IS NOT NULL)",
        name="ck_matches_ready_invariant",
    ),
)


# ---------------------------------------------------------------------------
# 5.2 team_orientation
# ---------------------------------------------------------------------------

team_orientation = Table(
    "team_orientation",
    metadata,
    Column("match_id", Text, ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True),
    Column("team", SmallInteger, primary_key=True),
    Column("half", SmallInteger, primary_key=True),
    Column("attack_direction", SmallInteger, nullable=False),
    CheckConstraint(f"team IN ({_check_vals(Team)})", name="ck_team_orientation_team"),
    CheckConstraint("half IN (1, 2)", name="ck_team_orientation_half"),
    CheckConstraint("attack_direction IN (-1, 1)", name="ck_team_orientation_attack_dir"),
)


# ---------------------------------------------------------------------------
# 5.3 video_segments
# ---------------------------------------------------------------------------

video_segments = Table(
    "video_segments",
    metadata,
    Column("match_id", Text, ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True),
    Column("pipeline_version", Text, primary_key=True),
    Column("t_start", _REAL, primary_key=True),
    Column("t_end", _REAL, nullable=False),
    Column("view_type", Text, nullable=False),
    Column("usable", Boolean, nullable=False),
    Column("half", SmallInteger, nullable=True),
    Column("clock_start", _REAL, nullable=True),
    Column("clock_end", _REAL, nullable=True),
    CheckConstraint(_PV_CHECK, name="ck_video_segments_pv"),
    CheckConstraint("t_start >= 0", name="ck_video_segments_tstart_ge_0"),
    CheckConstraint("t_end > t_start", name="ck_video_segments_tend_gt_tstart"),
    CheckConstraint(f"view_type IN ({_check_vals(ViewType)})", name="ck_video_segments_view_type"),
    CheckConstraint(
        f"NOT usable OR view_type = '{ViewType.TACTICAL.value}'",
        name="ck_video_segments_usable_tactical",
    ),
    CheckConstraint("half IN (1, 2)", name="ck_video_segments_half"),
    CheckConstraint(
        "(half IS NULL AND clock_start IS NULL AND clock_end IS NULL)"
        " OR (half IS NOT NULL AND clock_start IS NOT NULL AND clock_end IS NOT NULL)",
        name="ck_video_segments_clock_half",
    ),
)


# ---------------------------------------------------------------------------
# 5.4 possessions
# ---------------------------------------------------------------------------

possessions = Table(
    "possessions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("match_id", Text, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("team", SmallInteger, nullable=False),
    Column("t_start", _REAL, nullable=False),
    Column("t_end", _REAL, nullable=False),
    Column("half", SmallInteger, nullable=False),
    Column("clock_start", _REAL, nullable=False),
    Column("clock_end", _REAL, nullable=False),
    Column("x_start", _REAL, nullable=True),
    Column("y_start", _REAL, nullable=True),
    Column("x_end", _REAL, nullable=True),
    Column("y_end", _REAL, nullable=True),
    Column("outcome", Text, nullable=False),
    Column("n_passes", SmallInteger, nullable=True),
    Column("source", Text, nullable=False),
    Column("confidence", _REAL, nullable=False),
    CheckConstraint("id ~ '^pos_[a-z0-9_]+$'", name="ck_possessions_id_pattern"),
    CheckConstraint(_PV_CHECK, name="ck_possessions_pv"),
    CheckConstraint(f"team IN ({_check_vals(Team)})", name="ck_possessions_team"),
    CheckConstraint("t_start >= 0", name="ck_possessions_tstart_ge_0"),
    CheckConstraint("t_end > t_start", name="ck_possessions_tend_gt_tstart"),
    CheckConstraint("half IN (1, 2)", name="ck_possessions_half"),
    CheckConstraint(
        f"outcome IN ({_check_vals(PossessionOutcome)})", name="ck_possessions_outcome"
    ),
    CheckConstraint(f"source IN ({_check_vals(PossessionSource)})", name="ck_possessions_source"),
    CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_possessions_conf_range"),
    CheckConstraint(
        "(x_start IS NULL AND y_start IS NULL AND x_end IS NULL AND y_end IS NULL)"
        " OR (x_start IS NOT NULL AND y_start IS NOT NULL"
        "     AND x_end IS NOT NULL AND y_end IS NOT NULL)",
        name="ck_possessions_coords_pairing",
    ),
    # Index defined after table — see below
)

Index(
    "ix_possessions_match_pv_tstart",
    possessions.c.match_id,
    possessions.c.pipeline_version,
    possessions.c.t_start,
)


# ---------------------------------------------------------------------------
# 5.5 events
# ---------------------------------------------------------------------------

events = Table(
    "events",
    metadata,
    Column("id", Text, primary_key=True),
    Column("match_id", Text, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("team", SmallInteger, nullable=True),
    Column("t_video", _REAL, nullable=False),
    Column("t_end", _REAL, nullable=True),
    Column("half", SmallInteger, nullable=False),
    Column("match_clock", _REAL, nullable=False),
    Column("x_pitch", _REAL, nullable=True),
    Column("y_pitch", _REAL, nullable=True),
    Column("attrs", JSONB(none_as_null=True), nullable=False, server_default=text("'{}'::jsonb")),
    Column("confidence", _REAL, nullable=False),
    Column("source", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=EventStatus.CONFIRMED.value),
    Column("revision", Integer, nullable=False, server_default="1"),
    CheckConstraint("id ~ '^evt_[a-z0-9]{12}$'", name="ck_events_id_pattern"),
    CheckConstraint(_PV_CHECK, name="ck_events_pv"),
    CheckConstraint(f"type IN ({_check_vals(EventType)})", name="ck_events_type"),
    CheckConstraint(f"team IN ({_check_vals(Team)})", name="ck_events_team"),
    CheckConstraint("half IN (1, 2)", name="ck_events_half"),
    CheckConstraint("t_video >= 0", name="ck_events_tvideo_ge_0"),
    CheckConstraint("t_end IS NULL OR t_end >= t_video", name="ck_events_tend_ge_tvideo"),
    CheckConstraint("match_clock >= 0", name="ck_events_match_clock_ge_0"),
    CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_events_conf_range"),
    CheckConstraint(f"source IN ({_check_vals(EventSource)})", name="ck_events_source"),
    CheckConstraint(f"status IN ({_check_vals(EventStatus)})", name="ck_events_status"),
    CheckConstraint("revision >= 1", name="ck_events_revision_ge_1"),
    CheckConstraint(
        "(x_pitch IS NULL AND y_pitch IS NULL) OR (x_pitch IS NOT NULL AND y_pitch IS NOT NULL)",
        name="ck_events_coords_pairing",
    ),
    # Pre-M4 constraint — schema.md §5.5; dropped in M4 migration
    CheckConstraint(
        f"status = '{EventStatus.CONFIRMED.value}' AND revision = 1", name="events_pre_m4"
    ),
)

# Indexes — schema.md §5.5 + technical-design §3.3
Index(
    "ix_events_match_pv_type_half",
    events.c.match_id,
    events.c.pipeline_version,
    events.c.type,
    events.c.half,
)
Index(
    "ix_events_match_pv_tvideo",
    events.c.match_id,
    events.c.pipeline_version,
    events.c.t_video,
)


# ---------------------------------------------------------------------------
# 5.6 team_metrics
# ---------------------------------------------------------------------------

team_metrics = Table(
    "team_metrics",
    metadata,
    Column("match_id", Text, ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True),
    Column("pipeline_version", Text, primary_key=True),
    Column("team", SmallInteger, primary_key=True),
    Column("half", SmallInteger, primary_key=True),
    Column("window_start", _REAL, primary_key=True),
    Column("window_end", _REAL, nullable=False),
    Column("metric", Text, primary_key=True),
    Column("value", _REAL, nullable=True),
    Column("coverage", _REAL, nullable=False),
    CheckConstraint(_PV_CHECK, name="ck_team_metrics_pv"),
    CheckConstraint(f"team IN ({_check_vals(Team)})", name="ck_team_metrics_team"),
    CheckConstraint("half IN (1, 2)", name="ck_team_metrics_half"),
    CheckConstraint("window_start >= 0", name="ck_team_metrics_wstart_ge_0"),
    CheckConstraint("window_end > window_start", name="ck_team_metrics_wend_gt_wstart"),
    CheckConstraint(f"metric IN ({_check_vals(MetricName)})", name="ck_team_metrics_metric"),
    CheckConstraint("coverage BETWEEN 0 AND 1", name="ck_team_metrics_cov_range"),
    CheckConstraint(
        "(coverage = 0 AND value IS NULL) OR (coverage > 0 AND value IS NOT NULL)",
        name="ck_team_metrics_value_coverage",
    ),
)


# ---------------------------------------------------------------------------
# 5.7 event_embeddings  (pgvector — schema.md §5.7)
# ---------------------------------------------------------------------------

event_embeddings = Table(
    "event_embeddings",
    metadata,
    Column("event_id", Text, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("pipeline_version", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    CheckConstraint(_PV_CHECK, name="ck_event_embeddings_pv"),
)

# HNSW index for cosine similarity — schema.md §5.7
Index(
    "ix_event_embeddings_hnsw",
    event_embeddings.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)


# ---------------------------------------------------------------------------
# 5.8 jobs
# ---------------------------------------------------------------------------

jobs = Table(
    "jobs",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("match_id", Text, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=JobStatus.QUEUED.value),
    Column("params", JSONB(none_as_null=True), nullable=False, server_default=text("'{}'::jsonb")),
    Column("attempts", SmallInteger, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", Text, nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error", Text, nullable=True),
    CheckConstraint(f"kind IN ({_check_vals(JobKind)})", name="ck_jobs_kind"),
    CheckConstraint(f"status IN ({_check_vals(JobStatus)})", name="ck_jobs_status"),
    CheckConstraint("attempts >= 0", name="ck_jobs_attempts_ge_0"),
    CheckConstraint(
        f"(status = '{JobStatus.FAILED.value}' AND error IS NOT NULL)"
        f" OR (status != '{JobStatus.FAILED.value}' AND error IS NULL)",
        name="ck_jobs_error_status",
    ),
)

# schema.md §5.8: partial unique — at most one active job per match
Index(
    "uq_jobs_active_match",
    jobs.c.match_id,
    unique=True,
    postgresql_where=text(f"status IN ('{JobStatus.QUEUED.value}', '{JobStatus.RUNNING.value}')"),
)
# schema.md §5.8: FIFO dequeue index
Index(
    "ix_jobs_dequeue",
    jobs.c.created_at,
    jobs.c.id,
    postgresql_where=text(f"status = '{JobStatus.QUEUED.value}'"),
)


# ---------------------------------------------------------------------------
# 5.9 pipeline_runs
# ---------------------------------------------------------------------------

pipeline_runs = Table(
    "pipeline_runs",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("run_id", UUID(as_uuid=True), nullable=False),
    Column("job_id", BigInteger, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
    Column("match_id", Text, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("node", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("duration_s", _REAL, nullable=False),
    Column("ok", Boolean, nullable=False),
    Column("rows_out", BigInteger, nullable=True),
    Column("checks", JSONB(none_as_null=True), nullable=False, server_default=text("'[]'::jsonb")),
    Column("config", JSONB(none_as_null=True), nullable=False),
    Column("error", Text, nullable=True),
    UniqueConstraint("run_id", "node", name="uq_pipeline_runs_run_node"),
    CheckConstraint(_PV_CHECK, name="ck_pipeline_runs_pv"),
    CheckConstraint("duration_s >= 0", name="ck_pipeline_runs_duration_ge_0"),
    CheckConstraint(
        "(ok = false AND error IS NOT NULL) OR (ok = true AND error IS NULL)",
        name="ck_pipeline_runs_ok_error",
    ),
)


# ---------------------------------------------------------------------------
# 5.10 feedback
# ---------------------------------------------------------------------------

feedback = Table(
    "feedback",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("conversation_id", Text, nullable=False),
    Column("turn", Integer, nullable=False),
    Column("query_text", Text, nullable=False),
    Column("structured_query", JSONB(none_as_null=True), nullable=True),
    Column(
        "returned_event_ids",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'"),
    ),
    Column("rating", SmallInteger, nullable=False),
    Column("note", Text, nullable=True),
    UniqueConstraint("conversation_id", "turn", name="uq_feedback_conv_turn"),
    CheckConstraint("turn >= 0", name="ck_feedback_turn_ge_0"),
    CheckConstraint("rating IN (-1, 1)", name="ck_feedback_rating"),
)


# ---------------------------------------------------------------------------
# 5.12 eval_cases
# ---------------------------------------------------------------------------

eval_cases = Table(
    "eval_cases",
    metadata,
    Column("case_id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("input", JSONB(none_as_null=True), nullable=False),
    Column("expected", JSONB(none_as_null=True), nullable=False),
    Column(
        "feedback_id",
        BigInteger,
        ForeignKey("feedback.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("content_hash", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(f"kind IN ({_check_vals(EvalKind)})", name="ck_eval_cases_kind"),
    CheckConstraint(f"status IN ({_check_vals(EvalCaseStatus)})", name="ck_eval_cases_status"),
)


# ---------------------------------------------------------------------------
# 5.12 eval_runs
# ---------------------------------------------------------------------------

eval_runs = Table(
    "eval_runs",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "case_id",
        Text,
        ForeignKey("eval_cases.case_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("content_hash", Text, nullable=False),
    Column("git_sha", Text, nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("score", _REAL, nullable=False),
    Column("passed", Boolean, nullable=False),
    Column("details", JSONB(none_as_null=True), nullable=False, server_default=text("'{}'::jsonb")),
    CheckConstraint(_PV_CHECK, name="ck_eval_runs_pv"),
)


__all__ = [
    "EMBEDDING_DIM",
    "PIPELINE_VERSION_PATTERN",
    "Vector",
    "eval_cases",
    "eval_runs",
    "event_embeddings",
    "events",
    "feedback",
    "jobs",
    "matches",
    "metadata",
    "pipeline_runs",
    "possessions",
    "team_metrics",
    "team_orientation",
    "video_segments",
]

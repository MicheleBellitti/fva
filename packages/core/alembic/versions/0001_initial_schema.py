"""Initial schema — all tables, constraints, pgvector, and indexes.

Translates docs/schema.md §5 1:1 onto a blank Postgres database.
The Vector type is emitted as a raw `vector(768)` column; pgvector is
installed first via `CREATE EXTENSION IF NOT EXISTS vector`.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-26 23:25:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
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
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Helper — build CHECK literal list from enum without hardcoding strings
# ---------------------------------------------------------------------------


def _cv(enum_cls: type) -> str:  # type: ignore[type-arg]
    parts: list[str] = []
    for m in enum_cls:  # type: ignore[attr-defined]
        v = m.value
        parts.append(f"'{v}'" if isinstance(v, str) else str(v))
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. pgvector extension — must exist before any vector() column
    # ------------------------------------------------------------------
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # ------------------------------------------------------------------
    # 1. matches  (schema.md §5.1)
    # ------------------------------------------------------------------
    op.create_table(
        "matches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("competition", sa.Text(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("home_team", sa.Text(), nullable=False),
        sa.Column("away_team", sa.Text(), nullable=False),
        sa.Column("team_a_side", sa.Text(), nullable=False),
        sa.Column("video_uri", sa.Text(), nullable=False),
        sa.Column("hls_uri", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.REAL(), nullable=False),
        sa.Column("fps", sa.REAL(), nullable=False),
        sa.Column("camera_type", sa.Text(), nullable=False),
        sa.Column("half1_kickoff_s", sa.REAL(), nullable=True),
        sa.Column("half1_end_s", sa.REAL(), nullable=True),
        sa.Column("half2_kickoff_s", sa.REAL(), nullable=True),
        sa.Column("half2_end_s", sa.REAL(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=MatchStatus.QUEUED.value,
        ),
        sa.Column("active_pipeline_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("id ~ '^m_[a-z0-9_]{1,62}$'", name="ck_matches_id_pattern"),
        sa.CheckConstraint(f"team_a_side IN ({_cv(TeamSide)})", name="ck_matches_team_a_side"),
        sa.CheckConstraint("duration_s > 0", name="ck_matches_duration_s"),
        sa.CheckConstraint("fps > 0", name="ck_matches_fps"),
        sa.CheckConstraint(f"camera_type IN ({_cv(CameraType)})", name="ck_matches_camera_type"),
        sa.CheckConstraint(f"status IN ({_cv(MatchStatus)})", name="ck_matches_status"),
        sa.CheckConstraint(
            "(half1_kickoff_s IS NULL AND half1_end_s IS NULL"
            " AND half2_kickoff_s IS NULL AND half2_end_s IS NULL)"
            " OR (half1_kickoff_s IS NOT NULL AND half1_end_s IS NOT NULL"
            "     AND half2_kickoff_s IS NOT NULL AND half2_end_s IS NOT NULL"
            "     AND 0 <= half1_kickoff_s AND half1_kickoff_s < half1_end_s"
            "     AND half1_end_s <= half2_kickoff_s"
            "     AND half2_kickoff_s < half2_end_s"
            "     AND half2_end_s <= duration_s)",
            name="ck_matches_halves_valid",
        ),
        sa.CheckConstraint(
            "status != 'ready'"
            " OR (active_pipeline_version IS NOT NULL AND half1_kickoff_s IS NOT NULL)",
            name="ck_matches_ready_invariant",
        ),
    )

    # ------------------------------------------------------------------
    # 2. team_orientation  (schema.md §5.2)
    # ------------------------------------------------------------------
    op.create_table(
        "team_orientation",
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("team", sa.SmallInteger(), nullable=False),
        sa.Column("half", sa.SmallInteger(), nullable=False),
        sa.Column("attack_direction", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id", "team", "half"),
        sa.CheckConstraint(f"team IN ({_cv(Team)})", name="ck_team_orientation_team"),
        sa.CheckConstraint("half IN (1, 2)", name="ck_team_orientation_half"),
        sa.CheckConstraint("attack_direction IN (-1, 1)", name="ck_team_orientation_attack_dir"),
    )

    # ------------------------------------------------------------------
    # 3. video_segments  (schema.md §5.3)
    # ------------------------------------------------------------------
    op.create_table(
        "video_segments",
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("t_start", sa.REAL(), nullable=False),
        sa.Column("t_end", sa.REAL(), nullable=False),
        sa.Column("view_type", sa.Text(), nullable=False),
        sa.Column("usable", sa.Boolean(), nullable=False),
        sa.Column("half", sa.SmallInteger(), nullable=True),
        sa.Column("clock_start", sa.REAL(), nullable=True),
        sa.Column("clock_end", sa.REAL(), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id", "pipeline_version", "t_start"),
        sa.CheckConstraint(
            "pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="ck_video_segments_pv",
        ),
        sa.CheckConstraint("t_start >= 0", name="ck_video_segments_tstart_ge_0"),
        sa.CheckConstraint("t_end > t_start", name="ck_video_segments_tend_gt_tstart"),
        sa.CheckConstraint(f"view_type IN ({_cv(ViewType)})", name="ck_video_segments_view_type"),
        sa.CheckConstraint(
            "NOT usable OR view_type = 'tactical'", name="ck_video_segments_usable_tactical"
        ),
        sa.CheckConstraint("half IN (1, 2)", name="ck_video_segments_half"),
        sa.CheckConstraint(
            "(half IS NULL AND clock_start IS NULL AND clock_end IS NULL)"
            " OR (half IS NOT NULL AND clock_start IS NOT NULL AND clock_end IS NOT NULL)",
            name="ck_video_segments_clock_half",
        ),
    )

    # ------------------------------------------------------------------
    # 4. possessions  (schema.md §5.4)
    # ------------------------------------------------------------------
    op.create_table(
        "possessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("team", sa.SmallInteger(), nullable=False),
        sa.Column("t_start", sa.REAL(), nullable=False),
        sa.Column("t_end", sa.REAL(), nullable=False),
        sa.Column("half", sa.SmallInteger(), nullable=False),
        sa.Column("clock_start", sa.REAL(), nullable=False),
        sa.Column("clock_end", sa.REAL(), nullable=False),
        sa.Column("x_start", sa.REAL(), nullable=True),
        sa.Column("y_start", sa.REAL(), nullable=True),
        sa.Column("x_end", sa.REAL(), nullable=True),
        sa.Column("y_end", sa.REAL(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("n_passes", sa.SmallInteger(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.REAL(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id ~ '^pos_[a-z0-9_]+$'", name="ck_possessions_id_pattern"),
        sa.CheckConstraint(
            "pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="ck_possessions_pv"
        ),
        sa.CheckConstraint(f"team IN ({_cv(Team)})", name="ck_possessions_team"),
        sa.CheckConstraint("t_start >= 0", name="ck_possessions_tstart_ge_0"),
        sa.CheckConstraint("t_end > t_start", name="ck_possessions_tend_gt_tstart"),
        sa.CheckConstraint("half IN (1, 2)", name="ck_possessions_half"),
        sa.CheckConstraint(f"outcome IN ({_cv(PossessionOutcome)})", name="ck_possessions_outcome"),
        sa.CheckConstraint(f"source IN ({_cv(PossessionSource)})", name="ck_possessions_source"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_possessions_conf_range"),
        sa.CheckConstraint(
            "(x_start IS NULL AND y_start IS NULL AND x_end IS NULL AND y_end IS NULL)"
            " OR (x_start IS NOT NULL AND y_start IS NOT NULL"
            "     AND x_end IS NOT NULL AND y_end IS NOT NULL)",
            name="ck_possessions_coords_pairing",
        ),
    )
    # schema.md §5.4 index
    op.create_index(
        "ix_possessions_match_pv_tstart",
        "possessions",
        ["match_id", "pipeline_version", "t_start"],
    )

    # ------------------------------------------------------------------
    # 5. events  (schema.md §5.5)
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("team", sa.SmallInteger(), nullable=True),
        sa.Column("t_video", sa.REAL(), nullable=False),
        sa.Column("t_end", sa.REAL(), nullable=True),
        sa.Column("half", sa.SmallInteger(), nullable=False),
        sa.Column("match_clock", sa.REAL(), nullable=False),
        sa.Column("x_pitch", sa.REAL(), nullable=True),
        sa.Column("y_pitch", sa.REAL(), nullable=True),
        sa.Column(
            "attrs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confidence", sa.REAL(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=EventStatus.CONFIRMED.value,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id ~ '^evt_[a-z0-9]{12}$'", name="ck_events_id_pattern"),
        sa.CheckConstraint("pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="ck_events_pv"),
        sa.CheckConstraint(f"type IN ({_cv(EventType)})", name="ck_events_type"),
        sa.CheckConstraint(f"team IN ({_cv(Team)})", name="ck_events_team"),
        sa.CheckConstraint("half IN (1, 2)", name="ck_events_half"),
        sa.CheckConstraint("t_video >= 0", name="ck_events_tvideo_ge_0"),
        sa.CheckConstraint("t_end IS NULL OR t_end >= t_video", name="ck_events_tend_ge_tvideo"),
        sa.CheckConstraint("match_clock >= 0", name="ck_events_match_clock_ge_0"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_events_conf_range"),
        sa.CheckConstraint(f"source IN ({_cv(EventSource)})", name="ck_events_source"),
        sa.CheckConstraint(f"status IN ({_cv(EventStatus)})", name="ck_events_status"),
        sa.CheckConstraint("revision >= 1", name="ck_events_revision_ge_1"),
        sa.CheckConstraint(
            "(x_pitch IS NULL AND y_pitch IS NULL)"
            " OR (x_pitch IS NOT NULL AND y_pitch IS NOT NULL)",
            name="ck_events_coords_pairing",
        ),
        # Pre-M4 invariant — schema.md §5.5; removed in M4 migration
        sa.CheckConstraint("status = 'confirmed' AND revision = 1", name="events_pre_m4"),
    )
    # schema.md §5.5 + technical-design §3.3 indexes
    op.create_index(
        "ix_events_match_pv_type_half",
        "events",
        ["match_id", "pipeline_version", "type", "half"],
    )
    op.create_index(
        "ix_events_match_pv_tvideo",
        "events",
        ["match_id", "pipeline_version", "t_video"],
    )

    # ------------------------------------------------------------------
    # 6. team_metrics  (schema.md §5.6)
    # ------------------------------------------------------------------
    op.create_table(
        "team_metrics",
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("team", sa.SmallInteger(), nullable=False),
        sa.Column("half", sa.SmallInteger(), nullable=False),
        sa.Column("window_start", sa.REAL(), nullable=False),
        sa.Column("window_end", sa.REAL(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.REAL(), nullable=True),
        sa.Column("coverage", sa.REAL(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "match_id", "pipeline_version", "team", "half", "window_start", "metric"
        ),
        sa.CheckConstraint(
            "pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="ck_team_metrics_pv"
        ),
        sa.CheckConstraint(f"team IN ({_cv(Team)})", name="ck_team_metrics_team"),
        sa.CheckConstraint("half IN (1, 2)", name="ck_team_metrics_half"),
        sa.CheckConstraint("window_start >= 0", name="ck_team_metrics_wstart_ge_0"),
        sa.CheckConstraint("window_end > window_start", name="ck_team_metrics_wend_gt_wstart"),
        sa.CheckConstraint(f"metric IN ({_cv(MetricName)})", name="ck_team_metrics_metric"),
        sa.CheckConstraint("coverage BETWEEN 0 AND 1", name="ck_team_metrics_cov_range"),
        sa.CheckConstraint(
            "(coverage = 0 AND value IS NULL) OR (coverage > 0 AND value IS NOT NULL)",
            name="ck_team_metrics_value_coverage",
        ),
    )

    # ------------------------------------------------------------------
    # 7. event_embeddings  (schema.md §5.7) — requires pgvector
    # ------------------------------------------------------------------
    op.create_table(
        "event_embeddings",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        # vector(768) — emitted as raw DDL because SQLAlchemy has no built-in
        sa.Column(
            "embedding",
            sa.Text().with_variant(
                # We use execute_raw DDL below; this column type is replaced
                sa.Text(),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.CheckConstraint(
            "pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="ck_event_embeddings_pv",
        ),
    )
    # Replace the placeholder Text column with the real vector(768) type
    op.execute(
        sa.text(
            "ALTER TABLE event_embeddings ALTER COLUMN embedding TYPE vector(768)"
            " USING embedding::vector(768)"
        )
    )
    # HNSW cosine similarity index — schema.md §5.7
    op.execute(
        sa.text(
            "CREATE INDEX ix_event_embeddings_hnsw ON event_embeddings"
            " USING hnsw (embedding vector_cosine_ops)"
        )
    )

    # ------------------------------------------------------------------
    # 8. jobs  (schema.md §5.8)
    # ------------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=JobStatus.QUEUED.value,
        ),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"kind IN ({_cv(JobKind)})", name="ck_jobs_kind"),
        sa.CheckConstraint(f"status IN ({_cv(JobStatus)})", name="ck_jobs_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_ge_0"),
        sa.CheckConstraint(
            "(status = 'failed' AND error IS NOT NULL) OR (status != 'failed' AND error IS NULL)",
            name="ck_jobs_error_status",
        ),
    )
    # schema.md §5.8: at most one active job per match
    op.create_index(
        "uq_jobs_active_match",
        "jobs",
        ["match_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    # schema.md §5.8: FIFO dequeue
    op.create_index(
        "ix_jobs_dequeue",
        "jobs",
        ["created_at", "id"],
        postgresql_where=sa.text("status = 'queued'"),
    )

    # ------------------------------------------------------------------
    # 9. pipeline_runs  (schema.md §5.9)
    # ------------------------------------------------------------------
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_s", sa.REAL(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("rows_out", sa.BigInteger(), nullable=True),
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "node", name="uq_pipeline_runs_run_node"),
        sa.CheckConstraint(
            "pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="ck_pipeline_runs_pv"
        ),
        sa.CheckConstraint("duration_s >= 0", name="ck_pipeline_runs_duration_ge_0"),
        sa.CheckConstraint(
            "(ok = false AND error IS NOT NULL) OR (ok = true AND error IS NULL)",
            name="ck_pipeline_runs_ok_error",
        ),
    )

    # ------------------------------------------------------------------
    # 10. feedback  (schema.md §5.10)
    # ------------------------------------------------------------------
    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column(
            "structured_query",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "returned_event_ids",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("conversation_id", "turn", name="uq_feedback_conv_turn"),
        sa.CheckConstraint("turn >= 0", name="ck_feedback_turn_ge_0"),
        sa.CheckConstraint("rating IN (-1, 1)", name="ck_feedback_rating"),
    )

    # ------------------------------------------------------------------
    # 11. eval_cases  (schema.md §5.12)
    # ------------------------------------------------------------------
    op.create_table(
        "eval_cases",
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feedback_id", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("case_id"),
        sa.CheckConstraint(f"kind IN ({_cv(EvalKind)})", name="ck_eval_cases_kind"),
        sa.CheckConstraint(f"status IN ({_cv(EvalCaseStatus)})", name="ck_eval_cases_status"),
    )

    # ------------------------------------------------------------------
    # 12. eval_runs  (schema.md §5.12)
    # ------------------------------------------------------------------
    op.create_table(
        "eval_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.REAL(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["case_id"], ["eval_cases.case_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "case_id"),
        sa.CheckConstraint(
            "pipeline_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="ck_eval_runs_pv"
        ),
    )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
    op.drop_table("feedback")
    op.drop_table("pipeline_runs")
    op.drop_index("ix_jobs_dequeue", table_name="jobs")
    op.drop_index("uq_jobs_active_match", table_name="jobs")
    op.drop_table("jobs")
    op.execute(sa.text("DROP INDEX IF EXISTS ix_event_embeddings_hnsw"))
    op.drop_table("event_embeddings")
    op.drop_table("team_metrics")
    op.drop_index("ix_events_match_pv_tvideo", table_name="events")
    op.drop_index("ix_events_match_pv_type_half", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_possessions_match_pv_tstart", table_name="possessions")
    op.drop_table("possessions")
    op.drop_table("video_segments")
    op.drop_table("team_orientation")
    op.drop_table("matches")
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector CASCADE"))

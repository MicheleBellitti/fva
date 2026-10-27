import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

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


class Match(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(frozen=True, pattern=r"^m_[a-z0-9_]{1,62}$")
    competition: str
    date: date
    home_team: str
    away_team: str
    team_a_side: TeamSide | str
    video_uri: str
    duration_s: float = Field(gt=0)
    fps: float = Field(gt=0)
    camera_type: CameraType | str
    hls_uri: str
    half1_kickoff_s: float | None = None
    half1_end_s: float | None = None
    half2_kickoff_s: float | None = None
    half2_end_s: float | None = None
    status: MatchStatus | str = Field(default=MatchStatus.QUEUED)
    active_pipeline_version: str | None = None
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_halves(self) -> "Match":
        h1k = self.half1_kickoff_s
        h1e = self.half1_end_s
        h2k = self.half2_kickoff_s
        h2e = self.half2_end_s
        if h1k is None and h1e is None and h2k is None and h2e is None:
            return self

        if h1k is None or h1e is None or h2k is None or h2e is None:
            raise ValueError("I 4 tempi devono essere o tutti valorizzati o tutti None")
        if not (0 <= h1k < h1e <= h2k < h2e <= self.duration_s):
            raise ValueError("Invariante tempi violato: 0 <= h1k < h1e <= h2k < h2e <= duration_s")
        return self


class TeamOrientation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str
    team: Team | int
    half: int
    attack_direction: int

    @field_validator("attack_direction")
    @classmethod
    def attack_direction_check(cls, v: int) -> int:
        if v in (-1, 1):
            return v
        raise ValueError("Valore errato: attack_direction deve essere 1 o -1")


class VideoSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str
    pipeline_version: str
    t_start: float = Field(ge=0)
    t_end: float
    view_type: ViewType | str
    usable: bool
    half: int | None = None
    clock_start: float | None = None
    clock_end: float | None = None

    @model_validator(mode="after")
    def validate_segment(self) -> "VideoSegment":
        if self.t_end <= self.t_start:
            raise ValueError("t_end deve essere > t_start")
        if self.usable and self.view_type not in (ViewType.TACTICAL, "tactical"):
            raise ValueError("usable is True but view_type is not tactical")
        if self.half is None:
            if self.clock_start is not None or self.clock_end is not None:
                raise ValueError("clock_start e clock_end devono essere None quando half è None")
        else:
            if self.clock_start is None or self.clock_end is None:
                raise ValueError(
                    "clock_start e clock_end devono essere valorizzati quando half non è None"
                )
        return self


class Possession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    match_id: str
    pipeline_version: str
    team: Team | int
    t_start: float = Field(default=0.0, ge=0.0)
    t_end: float
    half: int
    clock_start: float
    clock_end: float
    x_start: float | None = None
    y_start: float | None = None
    x_end: float | None = None
    y_end: float | None = None
    outcome: PossessionOutcome | str
    source: PossessionSource | str
    n_passes: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_possession(self) -> "Possession":
        if self.t_end <= self.t_start:
            raise ValueError("t_end deve essere > t_start")
        coords = (self.x_start, self.y_start, self.x_end, self.y_end)
        n_none = sum(c is None for c in coords)
        if n_none not in (0, 4):
            raise ValueError("Le coordinate devono essere tutte valorizzate o tutte None")
        if self.source in (PossessionSource.FALLBACK, "fallback"):
            if self.n_passes is not None:
                raise ValueError("n_passes deve essere None per source fallback")
            if self.confidence != 0.4:
                raise ValueError("confidence deve essere 0.4 per source fallback")
        return self


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^evt_[a-z0-9]{12}$")
    match_id: str
    pipeline_version: str
    type: EventType | str
    team: Team | int | None = None
    t_video: float = Field(ge=0.0)
    t_end: float | None = None
    half: int
    match_clock: float = Field(ge=0.0)
    x_pitch: float | None = None
    y_pitch: float | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    source: EventSource | str
    status: EventStatus | str = Field(default=EventStatus.CONFIRMED)
    revision: int = Field(default=1, ge=1)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: EventStatus | str) -> EventStatus | str:
        if v not in (EventStatus.CONFIRMED, "confirmed"):
            raise ValueError("status deve essere 'confirmed'")
        return v

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, v: int) -> int:
        if v != 1:
            raise ValueError("revision deve essere 1")
        return v

    @model_validator(mode="after")
    def validate_event(self) -> "Event":
        if self.t_end is not None and self.t_end < self.t_video:
            raise ValueError("t_end deve essere >= t_video")
        if (self.x_pitch is None) != (self.y_pitch is None):
            raise ValueError("x_pitch e y_pitch devono essere entrambi valorizzati o entrambi None")
        return self


class TeamMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str
    pipeline_version: str
    team: Team | int
    half: int
    window_start: float
    window_end: float
    metric: MetricName | str
    coverage: float = Field(ge=0.0, le=1.0)
    value: float | None = None

    @model_validator(mode="after")
    def validate_metric(self) -> "TeamMetric":
        if self.window_end <= self.window_start:
            raise ValueError("window_end deve essere > window_start")
        if self.coverage == 0.0 and self.value is not None:
            raise ValueError("value deve essere NULL quando coverage è 0")
        if self.coverage > 0.0 and self.value is None:
            raise ValueError("value non può essere NULL quando coverage > 0")
        return self


class EventEmbedding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    pipeline_version: str
    model: str
    embedding: list[float] = Field(min_length=768, max_length=768)


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    match_id: str
    kind: JobKind | str
    status: JobStatus | str = Field(default=JobStatus.QUEUED)
    params: dict[str, Any] = Field(default_factory=dict)
    attempts: int = Field(default=0)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    locked_at: AwareDatetime | None = None
    locked_by: str | None = None
    finished_at: AwareDatetime | None = None
    error: str | None = Field(default=None)

    @model_validator(mode="after")
    def validate_error(self) -> "Job":
        if self.status in (JobStatus.FAILED, "failed") and self.error is None:
            raise ValueError("error deve essere valorizzato quando status è failed")
        if self.status not in (JobStatus.FAILED, "failed") and self.error is not None:
            raise ValueError("error deve essere None quando status non è failed")
        return self


class PipelineRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    run_id: uuid.UUID
    job_id: int | None = None
    match_id: str
    pipeline_version: str
    node: str
    started_at: AwareDatetime
    duration_s: float = Field(ge=0)
    ok: bool
    rows_out: int | None = None
    checks: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None)

    @model_validator(mode="after")
    def validate_error(self) -> "PipelineRun":
        if not self.ok and self.error is None:
            raise ValueError("error deve essere valorizzato quando ok è False")
        if self.ok and self.error is not None:
            raise ValueError("error deve essere None quando ok è True")
        return self


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    ts: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    conversation_id: str
    turn: int = Field(ge=0)
    query_text: str
    structured_query: dict[str, Any] | None = None
    returned_event_ids: list[str] = Field(default_factory=list)
    rating: int  # 1 o -1
    note: str | None = None

    @field_validator("rating")
    @classmethod
    def rating_check(cls, v: int) -> int:
        if v not in (-1, 1):
            raise ValueError("rating deve essere 1 o -1")
        return v


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    kind: EvalKind | str
    status: EvalCaseStatus | str
    input: dict[str, Any]
    expected: dict[str, Any]
    feedback_id: int | None = None
    content_hash: str
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class EvalRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    case_id: str
    content_hash: str
    git_sha: str
    pipeline_version: str
    started_at: AwareDatetime
    score: float
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


# Backwards-compatibility aliases
Possessions = Possession
Events = Event
TeamMetrics = TeamMetric
EventEmbeddings = EventEmbedding
Jobs = Job
Pipeline_runs = PipelineRun
EvalCases = EvalCase
EvalRuns = EvalRun

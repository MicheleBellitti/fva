"""DSL di query: l'LLM sceglie tra opzioni chiuse, il compilatore scrive l'SQL.

Vedi `docs/technical-design.md` §5.2 e ADR-009.
"""

from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, Field, TypeAdapter, model_validator

# TODO(P2.4): generare dal registry dei detector, così l'LLM può chiedere solo ciò che
# esiste. Finché il registry non c'è, la lista è a mano e ordinata come sorted(DETECTORS).
EventType = Literal[
    "corner",
    "counter_attack",
    "cross",
    "goal_kick",
    "kickoff",
    "pass_final_third",
    "press_trigger",
    "shot",
    "throw_in",
    "turnover",
]

MetricName = Literal[
    "compactness",
    "defensive_line_height",
    "possession_share",
    "ppda_proxy",
    "recoveries_by_zone",
    "team_width",
]

Zone = Literal[
    "defensive_third",
    "middle_third",
    "final_third",
    "left_flank",
    "center",
    "right_flank",
    "box",
]

# Unica fonte degli intent: classify_intent sceglie tra INTENTS, build_query produce una
# Query solo per QUERY_INTENTS. report compone più Query, chitchat non ne produce.
QueryIntent = Literal["find_moments", "compute_metric", "compare", "similar"]
NonQueryIntent = Literal["report", "chitchat"]
Intent = QueryIntent | NonQueryIntent

Team = Literal["A", "B"]
TeamFilter = Literal["A", "B", "both"]

EVENT_TYPES: tuple[EventType, ...] = get_args(EventType)
METRIC_NAMES: tuple[MetricName, ...] = get_args(MetricName)
ZONES: tuple[Zone, ...] = get_args(Zone)
QUERY_INTENTS: tuple[QueryIntent, ...] = get_args(QueryIntent)
INTENTS: tuple[Intent, ...] = (*QUERY_INTENTS, *get_args(NonQueryIntent))


class TimeWindow(BaseModel):
    """Finestra temporale in minuti di gioco. `last_n_min` è per il live."""

    model_config = {"extra": "forbid"}

    half: Literal[1, 2] | None = None
    clock_from_min: int | None = Field(default=None, ge=0, le=130)
    clock_to_min: int | None = Field(default=None, ge=0, le=130)
    last_n_min: int | None = Field(default=None, ge=1, le=90)

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        has_range = self.clock_from_min is not None or self.clock_to_min is not None
        if self.last_n_min is not None and has_range:
            raise ValueError("last_n_min non si combina con clock_from_min/clock_to_min")
        if (
            self.clock_from_min is not None
            and self.clock_to_min is not None
            and self.clock_from_min > self.clock_to_min
        ):
            raise ValueError("clock_from_min deve essere <= clock_to_min")
        return self


class FindMoments(BaseModel):
    """Momenti della partita di certi tipi, filtrati per squadra, zona e tempo."""

    model_config = {"extra": "forbid"}

    intent: Literal["find_moments"]
    match_ids: list[str] = Field(min_length=1)
    event_types: list[EventType] = Field(min_length=1)
    team: TeamFilter = "both"
    zone: Zone | None = None
    time: TimeWindow | None = None
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    limit: int = Field(default=20, ge=1, le=100)


class ComputeMetric(BaseModel):
    """Una metrica tattica di una squadra, aggregata per partita, tempo o finestra."""

    model_config = {"extra": "forbid"}

    intent: Literal["compute_metric"]
    match_ids: list[str] = Field(min_length=1)
    metric: MetricName
    team: Team
    time: TimeWindow | None = None
    group_by: Literal["match", "half", "window"] = "match"


class CompareMatches(BaseModel):
    """La stessa metrica di una squadra su più partite distinte."""

    model_config = {"extra": "forbid"}

    intent: Literal["compare"]
    match_ids: list[str] = Field(min_length=2)
    metric: MetricName
    team: Team

    @model_validator(mode="after")
    def _check_distinct(self) -> Self:
        if len(set(self.match_ids)) != len(self.match_ids):
            raise ValueError("match_ids devono essere partite distinte")
        return self


class SimilarMoments(BaseModel):
    """Momenti simili a un evento di riferimento, via `event_embeddings`."""

    model_config = {"extra": "forbid"}

    intent: Literal["similar"]
    anchor_event_id: str = Field(min_length=1)
    match_ids: list[str] | None = Field(default=None, min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


Query = Annotated[
    FindMoments | ComputeMetric | CompareMatches | SimilarMoments,
    Field(discriminator="intent"),
]

# Valida l'output strutturato dell'LLM: `QUERY_ADAPTER.validate_json(raw)`.
QUERY_ADAPTER: TypeAdapter[Query] = TypeAdapter(Query)

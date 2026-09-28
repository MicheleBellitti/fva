import json
from typing import get_args

import pytest
from assistant.dsl import (
    EVENT_TYPES,
    INTENTS,
    METRIC_NAMES,
    QUERY_ADAPTER,
    QUERY_INTENTS,
    ZONES,
    CompareMatches,
    ComputeMetric,
    FindMoments,
    Query,
    SimilarMoments,
    TimeWindow,
)
from pydantic import BaseModel, ValidationError


class TestTimeWindow:
    def test_empty_window_is_valid(self) -> None:
        assert TimeWindow() == TimeWindow(half=None)

    def test_half_and_clock_range(self) -> None:
        w = TimeWindow(half=2, clock_from_min=60, clock_to_min=75)
        assert (w.half, w.clock_from_min, w.clock_to_min) == (2, 60, 75)

    def test_rejects_unknown_half(self) -> None:
        with pytest.raises(ValidationError):
            TimeWindow.model_validate({"half": 3})

    @pytest.mark.parametrize("minute", [-1, 131])
    def test_rejects_clock_out_of_range(self, minute: int) -> None:
        with pytest.raises(ValidationError):
            TimeWindow(clock_from_min=minute)

    def test_rejects_inverted_clock_range(self) -> None:
        with pytest.raises(ValidationError, match="clock_from_min"):
            TimeWindow(clock_from_min=80, clock_to_min=70)

    def test_single_minute_range_is_valid(self) -> None:
        assert TimeWindow(clock_from_min=70, clock_to_min=70).clock_to_min == 70

    @pytest.mark.parametrize("minutes", [0, 91])
    def test_rejects_last_n_min_out_of_range(self, minutes: int) -> None:
        with pytest.raises(ValidationError):
            TimeWindow(last_n_min=minutes)

    def test_last_n_min_excludes_explicit_clock_range(self) -> None:
        with pytest.raises(ValidationError, match="last_n_min"):
            TimeWindow(last_n_min=10, clock_from_min=30)

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            TimeWindow.model_validate({"minute": 12})


class TestVocabularies:
    def test_event_types_are_closed_and_sorted(self) -> None:
        assert "corner" in EVENT_TYPES
        assert list(EVENT_TYPES) == sorted(EVENT_TYPES)

    def test_vocabularies_have_no_duplicates(self) -> None:
        for vocab in (EVENT_TYPES, METRIC_NAMES, ZONES):
            assert len(set(vocab)) == len(vocab)


def find_moments(**overrides: object) -> dict[str, object]:
    return {"intent": "find_moments", "match_ids": ["m1"], "event_types": ["corner"]} | overrides


class TestFindMoments:
    def test_minimal_query_gets_defaults(self) -> None:
        q = FindMoments.model_validate(find_moments())
        assert (q.team, q.zone, q.time, q.min_confidence, q.limit) == ("both", None, None, 0.5, 20)

    @pytest.mark.parametrize("field", ["match_ids", "event_types"])
    def test_rejects_empty_lists(self, field: str) -> None:
        with pytest.raises(ValidationError, match=field):
            FindMoments.model_validate(find_moments(**{field: list[str]()}))

    def test_rejects_unknown_event_type(self) -> None:
        with pytest.raises(ValidationError, match="event_types"):
            FindMoments.model_validate(find_moments(event_types=["goal"]))

    def test_rejects_unknown_zone(self) -> None:
        with pytest.raises(ValidationError, match="zone"):
            FindMoments.model_validate(find_moments(zone="half_space"))

    @pytest.mark.parametrize(
        ("field", "value"), [("min_confidence", 1.1), ("limit", 0), ("limit", 101)]
    )
    def test_rejects_out_of_range(self, field: str, value: float) -> None:
        with pytest.raises(ValidationError, match=field):
            FindMoments.model_validate(find_moments(**{field: value}))

    def test_nested_time_window_is_validated(self) -> None:
        with pytest.raises(ValidationError, match="clock_from_min"):
            FindMoments.model_validate(
                find_moments(time={"clock_from_min": 80, "clock_to_min": 10})
            )

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            FindMoments.model_validate(find_moments(sql="SELECT 1"))


def compute_metric(**overrides: object) -> dict[str, object]:
    base = {"intent": "compute_metric", "match_ids": ["m1"], "metric": "team_width", "team": "A"}
    return base | overrides


class TestComputeMetric:
    def test_minimal_query_gets_defaults(self) -> None:
        q = ComputeMetric.model_validate(compute_metric())
        assert (q.time, q.group_by) == (None, "match")

    def test_rejects_empty_match_ids(self) -> None:
        with pytest.raises(ValidationError, match="match_ids"):
            ComputeMetric.model_validate(compute_metric(match_ids=list[str]()))

    def test_rejects_unknown_metric(self) -> None:
        with pytest.raises(ValidationError, match="metric"):
            ComputeMetric.model_validate(compute_metric(metric="xg"))

    def test_metric_needs_a_single_team(self) -> None:
        with pytest.raises(ValidationError, match="team"):
            ComputeMetric.model_validate(compute_metric(team="both"))

    def test_rejects_unknown_group_by(self) -> None:
        with pytest.raises(ValidationError, match="group_by"):
            ComputeMetric.model_validate(compute_metric(group_by="minute"))


def compare(**overrides: object) -> dict[str, object]:
    base = {"intent": "compare", "match_ids": ["m1", "m2"], "metric": "compactness", "team": "B"}
    return base | overrides


class TestCompareMatches:
    def test_valid_comparison(self) -> None:
        assert CompareMatches.model_validate(compare()).match_ids == ["m1", "m2"]

    def test_needs_at_least_two_matches(self) -> None:
        with pytest.raises(ValidationError, match="match_ids"):
            CompareMatches.model_validate(compare(match_ids=["m1"]))

    def test_rejects_duplicate_matches(self) -> None:
        with pytest.raises(ValidationError, match="distinte"):
            CompareMatches.model_validate(compare(match_ids=["m1", "m1"]))

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            CompareMatches.model_validate(compare(group_by="half"))


class TestSimilarMoments:
    def test_minimal_query_searches_everywhere(self) -> None:
        q = SimilarMoments(intent="similar", anchor_event_id="evt_1")
        assert (q.match_ids, q.limit) == (None, 10)

    def test_rejects_empty_anchor(self) -> None:
        with pytest.raises(ValidationError, match="anchor_event_id"):
            SimilarMoments(intent="similar", anchor_event_id="")

    def test_rejects_empty_match_ids(self) -> None:
        with pytest.raises(ValidationError, match="match_ids"):
            SimilarMoments(intent="similar", anchor_event_id="evt_1", match_ids=[])

    @pytest.mark.parametrize("limit", [0, 101])
    def test_limit_is_bounded_like_find_moments(self, limit: int) -> None:
        with pytest.raises(ValidationError, match="limit"):
            SimilarMoments(intent="similar", anchor_event_id="evt_1", limit=limit)


class TestQuery:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (find_moments(), FindMoments),
            (compute_metric(), ComputeMetric),
            (compare(), CompareMatches),
            ({"intent": "similar", "anchor_event_id": "evt_1"}, SimilarMoments),
        ],
    )
    def test_llm_json_dispatches_on_intent(
        self, payload: dict[str, object], expected: type
    ) -> None:
        assert type(QUERY_ADAPTER.validate_json(json.dumps(payload))) is expected

    def test_rejects_unknown_intent(self) -> None:
        with pytest.raises(ValidationError, match="intent"):
            QUERY_ADAPTER.validate_python({"intent": "report", "match_ids": ["m1"]})

    def test_rejects_missing_intent(self) -> None:
        with pytest.raises(ValidationError, match="intent"):
            QUERY_ADAPTER.validate_python({"match_ids": ["m1"], "event_types": ["corner"]})

    def test_errors_point_to_the_chosen_variant(self) -> None:
        with pytest.raises(ValidationError) as exc:
            QUERY_ADAPTER.validate_python(find_moments(event_types=["goal"]))
        assert all(e["loc"][0] == "find_moments" for e in exc.value.errors())

    def test_every_query_intent_has_exactly_one_variant(self) -> None:
        union, _discriminator = get_args(Query)
        variants: tuple[type[BaseModel], ...] = get_args(union)
        tags = sorted(get_args(v.model_fields["intent"].annotation)[0] for v in variants)
        assert tags == sorted(QUERY_INTENTS)


class TestIntent:
    def test_query_intents_are_a_subset_of_intents(self) -> None:
        assert set(QUERY_INTENTS) < set(INTENTS)

    def test_non_query_intents(self) -> None:
        assert set(INTENTS) - set(QUERY_INTENTS) == {"report", "chitchat"}

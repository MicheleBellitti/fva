import json

import pytest
from assistant.dsl import (
    EVENT_TYPES,
    INTENTS,
    QUERY_ADAPTER,
    QUERY_INTENTS,
    CompareMatches,
    ComputeMetric,
    FindMoments,
    SimilarMoments,
    TimeWindow,
)
from pydantic import ValidationError

# Payload minimi validi, come li produrrebbe l'LLM. I test sovrascrivono solo ciò che provano.


def find_moments(**overrides: object) -> dict[str, object]:
    return {"intent": "find_moments", "match_ids": ["m1"], "event_types": ["corner"]} | overrides


def compute_metric(**overrides: object) -> dict[str, object]:
    base = {"intent": "compute_metric", "match_ids": ["m1"], "metric": "team_width", "team": "A"}
    return base | overrides


def compare(**overrides: object) -> dict[str, object]:
    base = {"intent": "compare", "match_ids": ["m1", "m2"], "metric": "compactness", "team": "B"}
    return base | overrides


def similar(**overrides: object) -> dict[str, object]:
    return {"intent": "similar", "anchor_event_id": "evt_1"} | overrides


def test_event_types_are_sorted_like_the_registry() -> None:
    assert list(EVENT_TYPES) == sorted(EVENT_TYPES)


class TestTimeWindow:
    def test_everything_is_optional(self) -> None:
        w = TimeWindow.model_validate({})
        assert (w.half, w.clock_from_min, w.clock_to_min, w.last_n_min) == (None, None, None, None)

    def test_half_and_clock_range(self) -> None:
        w = TimeWindow.model_validate({"half": 2, "clock_from_min": 60, "clock_to_min": 75})
        assert (w.half, w.clock_from_min, w.clock_to_min) == (2, 60, 75)

    def test_a_single_minute_is_a_valid_range(self) -> None:
        TimeWindow.model_validate({"clock_from_min": 70, "clock_to_min": 70})

    @pytest.mark.parametrize(
        "window",
        [
            {"half": 3},
            {"clock_from_min": -1},
            {"clock_to_min": 131},
            {"last_n_min": 0},
            {"last_n_min": 91},
            {"minute": 12},
        ],
    )
    def test_rejects_invalid_fields(self, window: dict[str, int]) -> None:
        with pytest.raises(ValidationError):
            TimeWindow.model_validate(window)

    def test_rejects_inverted_range(self) -> None:
        with pytest.raises(ValidationError, match="clock_from_min"):
            TimeWindow.model_validate({"clock_from_min": 80, "clock_to_min": 70})

    def test_last_n_min_excludes_an_explicit_range(self) -> None:
        with pytest.raises(ValidationError, match="last_n_min"):
            TimeWindow.model_validate({"last_n_min": 10, "clock_from_min": 30})


class TestFindMoments:
    def test_defaults(self) -> None:
        q = FindMoments.model_validate(find_moments())
        assert (q.team, q.zone, q.time, q.min_confidence, q.limit) == ("both", None, None, 0.5, 20)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("match_ids", []),
            ("event_types", []),
            ("event_types", ["goal"]),
            ("zone", "half_space"),
            ("min_confidence", 1.1),
            ("limit", 0),
            ("limit", 101),
        ],
    )
    def test_rejects_invalid_values(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError, match=field):
            FindMoments.model_validate(find_moments(**{field: value}))

    def test_validates_the_nested_time_window(self) -> None:
        with pytest.raises(ValidationError, match="clock_from_min"):
            FindMoments.model_validate(
                find_moments(time={"clock_from_min": 80, "clock_to_min": 10})
            )

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="sql"):
            FindMoments.model_validate(find_moments(sql="SELECT 1"))


class TestComputeMetric:
    def test_defaults(self) -> None:
        q = ComputeMetric.model_validate(compute_metric())
        assert (q.time, q.group_by) == (None, "match")

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("match_ids", []),
            ("metric", "xg"),
            ("team", "both"),
            ("group_by", "minute"),
        ],
    )
    def test_rejects_invalid_values(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError, match=field):
            ComputeMetric.model_validate(compute_metric(**{field: value}))


class TestCompareMatches:
    def test_valid_comparison(self) -> None:
        assert CompareMatches.model_validate(compare()).match_ids == ["m1", "m2"]

    def test_needs_at_least_two_matches(self) -> None:
        with pytest.raises(ValidationError, match="match_ids"):
            CompareMatches.model_validate(compare(match_ids=["m1"]))

    def test_matches_must_be_distinct(self) -> None:
        with pytest.raises(ValidationError, match="distinte"):
            CompareMatches.model_validate(compare(match_ids=["m1", "m1"]))

    def test_has_no_group_by(self) -> None:
        with pytest.raises(ValidationError, match="group_by"):
            CompareMatches.model_validate(compare(group_by="half"))


class TestSimilarMoments:
    def test_defaults_search_every_match(self) -> None:
        q = SimilarMoments.model_validate(similar())
        assert (q.match_ids, q.limit) == (None, 10)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("anchor_event_id", ""),
            ("match_ids", []),
            ("limit", 0),
            ("limit", 101),
        ],
    )
    def test_rejects_invalid_values(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError, match=field):
            SimilarMoments.model_validate(similar(**{field: value}))


class TestQuery:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (find_moments(), FindMoments),
            (compute_metric(), ComputeMetric),
            (compare(), CompareMatches),
            (similar(), SimilarMoments),
        ],
    )
    def test_json_dispatches_on_intent(self, payload: dict[str, object], expected: type) -> None:
        assert type(QUERY_ADAPTER.validate_json(json.dumps(payload))) is expected

    def test_every_query_intent_has_a_variant(self) -> None:
        mapping = QUERY_ADAPTER.json_schema()["discriminator"]["mapping"]
        assert set(mapping) == set(QUERY_INTENTS)

    @pytest.mark.parametrize("intent", sorted(set(INTENTS) - set(QUERY_INTENTS)))
    def test_non_query_intents_produce_no_query(self, intent: str) -> None:
        with pytest.raises(ValidationError, match=intent):
            QUERY_ADAPTER.validate_python({"intent": intent})

    def test_rejects_missing_intent(self) -> None:
        with pytest.raises(ValidationError, match="intent"):
            QUERY_ADAPTER.validate_python({"match_ids": ["m1"], "event_types": ["corner"]})

    def test_errors_point_to_the_chosen_variant(self) -> None:
        with pytest.raises(ValidationError) as exc:
            QUERY_ADAPTER.validate_python(find_moments(event_types=["goal"]))
        assert all(e["loc"][0] == "find_moments" for e in exc.value.errors())

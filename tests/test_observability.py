from datetime import UTC, datetime, timedelta

import pytest

from app.constants import DashboardWindow, FeedType
from app.observability import (
    RequestObservation,
    aggregate_observability,
    nearest_rank,
)

NOW = datetime(2026, 9, 2, 1, 0, tzinfo=UTC)


def _row(
    latency: float,
    *,
    feed: str = "personalized",
    model: str = "v1",
    fallback: bool = False,
) -> RequestObservation:
    return RequestObservation(
        feed_type=feed,
        model_version=model,
        feed_build_latency_ms=latency,
        fallback_reason="model error" if fallback else None,
    )


def _aggregate(rows: list[RequestObservation]):
    return aggregate_observability(
        rows,
        window=DashboardWindow.HOUR_24,
        window_start=NOW - timedelta(hours=24),
        window_end=NOW,
    )


def test_nearest_rank_percentiles_are_deterministic() -> None:
    values = [4.0, 1.0, 3.0, 2.0]

    assert nearest_rank(values, 0.50) == 2.0
    assert nearest_rank(values, 0.95) == 4.0
    assert nearest_rank(values, 1.0) == 4.0
    assert nearest_rank([], 0.95) == 0.0
    with pytest.raises(ValueError, match="percentile"):
        nearest_rank(values, 0.0)


def test_low_sample_count_never_alerts() -> None:
    rows = [_row(700.0, fallback=True) for _ in range(19)]

    response = _aggregate(rows)

    assert response.requests == 19
    assert response.fallback_rate == 1.0
    assert response.latency_ms.p95 == 700.0
    assert response.alerts == []


def test_thresholds_emit_fallback_and_p95_alerts() -> None:
    rows = [_row(12.0) for _ in range(18)]
    rows.extend([_row(500.0, fallback=True), _row(620.0)])

    response = _aggregate(rows)

    assert response.requests == 20
    assert response.fallback_count == 1
    assert response.fallback_rate == pytest.approx(0.05)
    assert response.latency_ms.p50 == 12.0
    assert response.latency_ms.p95 == 500.0
    assert response.latency_ms.max == 620.0
    assert [alert.code for alert in response.alerts] == ["fallback_rate", "p95_latency"]


def test_feed_and_model_groups_are_sorted_and_independent() -> None:
    rows = [
        _row(10.0, feed=FeedType.POPULAR, model="v2"),
        _row(30.0, feed=FeedType.PERSONALIZED, model="v1", fallback=True),
        _row(20.0, feed=FeedType.POPULAR, model="v1"),
    ]

    response = _aggregate(rows)

    assert [group.key for group in response.by_feed] == ["personalized", "popular"]
    assert [group.key for group in response.by_model] == ["v1", "v2"]
    popular = response.by_feed[1]
    assert popular.requests == 2
    assert popular.fallback_count == 0
    assert popular.latency_ms.p50 == 10.0
    model_v1 = response.by_model[0]
    assert model_v1.requests == 2
    assert model_v1.fallback_rate == pytest.approx(0.5)


def test_empty_window_and_invalid_latency_are_explicit() -> None:
    response = _aggregate([])

    assert response.requests == 0
    assert response.latency_ms.model_dump() == {"p50": 0.0, "p95": 0.0, "max": 0.0}
    assert response.by_feed == []
    assert response.by_model == []
    assert response.alerts == []

    with pytest.raises(ValueError, match="latencies"):
        _aggregate([_row(float("nan"))])

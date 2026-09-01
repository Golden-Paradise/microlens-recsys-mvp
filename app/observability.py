from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.constants import DashboardWindow
from app.schemas import (
    LatencySummary,
    ObservabilityAlert,
    ObservabilityGroup,
    ObservabilityResponse,
)


@dataclass(frozen=True)
class RequestObservation:
    feed_type: str
    model_version: str
    feed_build_latency_ms: float
    fallback_reason: str | None = None


def nearest_rank(values: Iterable[float], percentile: float) -> float:
    """Return the nearest-rank percentile, using one-based ceil(p * n)."""
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise ValueError("latencies must be finite non-negative values")
    rank = math.ceil(percentile * len(ordered))
    return ordered[rank - 1]


def _latency_summary(observations: list[RequestObservation]) -> LatencySummary:
    values = [observation.feed_build_latency_ms for observation in observations]
    return LatencySummary(
        p50=nearest_rank(values, 0.50),
        p95=nearest_rank(values, 0.95),
        max=nearest_rank(values, 1.0),
    )


def _group(key: str, observations: list[RequestObservation]) -> ObservabilityGroup:
    fallback_count = sum(bool(observation.fallback_reason) for observation in observations)
    requests = len(observations)
    return ObservabilityGroup(
        key=key,
        requests=requests,
        fallback_count=fallback_count,
        fallback_rate=fallback_count / requests if requests else 0.0,
        latency_ms=_latency_summary(observations),
    )


def aggregate_observability(
    observations: Iterable[RequestObservation],
    *,
    window: DashboardWindow,
    window_start: datetime | None,
    window_end: datetime,
    minimum_alert_samples: int = 20,
    fallback_rate_threshold: float = 0.05,
    p95_latency_threshold_ms: float = 500.0,
) -> ObservabilityResponse:
    """Aggregate already window-filtered request observations without I/O."""
    rows = list(observations)
    if minimum_alert_samples < 1:
        raise ValueError("minimum_alert_samples must be positive")
    if not 0 <= fallback_rate_threshold <= 1:
        raise ValueError("fallback_rate_threshold must be in [0, 1]")
    if p95_latency_threshold_ms < 0:
        raise ValueError("p95_latency_threshold_ms must be non-negative")

    by_feed: defaultdict[str, list[RequestObservation]] = defaultdict(list)
    by_model: defaultdict[str, list[RequestObservation]] = defaultdict(list)
    for row in rows:
        nearest_rank([row.feed_build_latency_ms], 1.0)
        feed_key = getattr(row.feed_type, "value", row.feed_type)
        by_feed[str(feed_key)].append(row)
        by_model[str(row.model_version)].append(row)

    overall = _group("all", rows)
    alerts: list[ObservabilityAlert] = []
    if overall.requests >= minimum_alert_samples:
        if overall.fallback_rate >= fallback_rate_threshold:
            alerts.append(
                ObservabilityAlert(
                    code="fallback_rate",
                    message=f"Fallback rate reached {overall.fallback_rate:.2%}.",
                )
            )
        if overall.latency_ms.p95 >= p95_latency_threshold_ms:
            alerts.append(
                ObservabilityAlert(
                    code="p95_latency",
                    message=(
                        "P95 feed build latency reached "
                        f"{overall.latency_ms.p95:.2f} ms."
                    ),
                )
            )

    return ObservabilityResponse(
        window=window,
        window_start=window_start,
        window_end=window_end,
        requests=overall.requests,
        fallback_count=overall.fallback_count,
        fallback_rate=overall.fallback_rate,
        latency_ms=overall.latency_ms,
        by_feed=[_group(key, by_feed[key]) for key in sorted(by_feed)],
        by_model=[_group(key, by_model[key]) for key in sorted(by_model)],
        alerts=alerts,
    )


from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np

from recsys.contracts import MetricSet


def reciprocal_rank_fusion(
    rankings: Iterable[Iterable[int]],
    *,
    rrf_k: int = 60,
    limit: int | None = None,
) -> list[tuple[int, float]]:
    """Fuse ranked item IDs with stable, score-scale-independent RRF."""
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    scores: dict[int, float] = {}
    for ranking in rankings:
        seen_in_source: set[int] = set()
        for rank, item_id in enumerate(ranking, start=1):
            item_id = int(item_id)
            if item_id in seen_in_source:
                continue
            seen_in_source.add(item_id)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (rrf_k + rank)
    fused = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    return fused if limit is None else fused[:limit]


def rrf_recommendations(
    recommendation_sets: Iterable[Mapping[int, Iterable[int]]],
    *,
    rrf_k: int,
    limit: int,
) -> dict[int, list[int]]:
    """Fuse several user -> ranking mappings, retaining deterministic item order."""
    sources = list(recommendation_sets)
    user_ids = sorted({user_id for source in sources for user_id in source})
    return {
        user_id: [
            item_id
            for item_id, _ in reciprocal_rank_fusion(
                (source.get(user_id, []) for source in sources),
                rrf_k=rrf_k,
                limit=limit,
            )
        ]
        for user_id in user_ids
    }


def ranking_metrics(
    recommendations: Mapping[int, Iterable[int]],
    targets: Mapping[int, int],
    *,
    catalog_size: int,
    k: int,
) -> MetricSet:
    """Compute macro Recall/NDCG for one held-out item per user and catalog coverage."""
    if k <= 0 or catalog_size <= 0:
        raise ValueError("k and catalog_size must be positive")
    if not targets:
        return MetricSet(recall_at_k=0.0, ndcg_at_k=0.0, coverage_at_k=0.0)

    hits = 0.0
    ndcg = 0.0
    covered: set[int] = set()
    for user_id, target in targets.items():
        ranked = list(recommendations.get(user_id, []))[:k]
        covered.update(ranked)
        try:
            rank = ranked.index(target)
        except ValueError:
            continue
        hits += 1.0
        ndcg += 1.0 / math.log2(rank + 2)
    users = len(targets)
    return MetricSet(
        recall_at_k=hits / users,
        ndcg_at_k=ndcg / users,
        coverage_at_k=min(len(covered) / catalog_size, 1.0),
    )


def target_by_user(matrix) -> dict[int, int]:
    targets: dict[int, int] = {}
    for user_index in range(matrix.shape[0]):
        start, end = matrix.indptr[user_index : user_index + 2]
        if end - start != 1:
            raise ValueError("each evaluation user must have exactly one held-out target")
        targets[user_index] = int(matrix.indices[start])
    return targets


def popularity_order(user_items) -> np.ndarray:
    counts = np.asarray(user_items.sum(axis=0)).ravel()
    item_indices = np.arange(user_items.shape[1])
    order = np.lexsort((item_indices, -counts))
    return order[counts[order] > 0]


def popularity_recommendations(user_items, *, k: int) -> dict[int, list[int]]:
    order = popularity_order(user_items)
    result: dict[int, list[int]] = {}
    for user_index in range(user_items.shape[0]):
        seen = set(user_items[user_index].indices.tolist())
        ranked: list[int] = []
        for item in order:
            item = int(item)
            if item not in seen:
                ranked.append(item)
                if len(ranked) == k:
                    break
        result[user_index] = ranked
    return result


def random_recommendations(user_items, *, k: int, seed: int) -> dict[int, list[int]]:
    warm_items = np.flatnonzero(np.asarray(user_items.sum(axis=0)).ravel() > 0)
    rng = np.random.default_rng(seed)
    random_order = rng.permutation(warm_items)
    result: dict[int, list[int]] = {}
    for user_index in range(user_items.shape[0]):
        seen = set(user_items[user_index].indices.tolist())
        ranked: list[int] = []
        if len(random_order):
            start = (seed + user_index * 104_729) % len(random_order)
            for offset in range(len(random_order)):
                item = int(random_order[(start + offset) % len(random_order)])
                if item not in seen:
                    ranked.append(item)
                    if len(ranked) == k:
                        break
        result[user_index] = ranked
    return result


def sliced_metrics(
    recommendations: Mapping[int, Iterable[int]],
    targets: Mapping[int, int],
    *,
    warm_items: set[int],
    catalog_size: int,
    k: int,
) -> dict[str, MetricSet]:
    warm_targets = {user: item for user, item in targets.items() if item in warm_items}
    return {
        "overall": ranking_metrics(
            recommendations, targets, catalog_size=catalog_size, k=k
        ),
        "warm_item": ranking_metrics(
            recommendations, warm_targets, catalog_size=catalog_size, k=k
        ),
    }

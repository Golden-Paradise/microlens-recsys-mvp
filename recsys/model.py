from __future__ import annotations

import hashlib
import json
import os
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd
from implicit.cpu.als import AlternatingLeastSquares
from implicit.nearest_neighbours import (
    BM25Recommender,
    CosineRecommender,
    ItemItemRecommender,
)
from scipy import sparse

from recsys.content import (
    CONFIG_FILE as CONTENT_CONFIG_FILE,
)
from recsys.content import (
    ITEM_VECTORS_FILE,
    TitleTfidfRetriever,
    fit_title_tfidf,
    hybrid_tail_quota,
    load_title_tfidf,
)
from recsys.contracts import ArtifactPointer, MetricSet, ModelManifest
from recsys.data import PreparedDataset, load_prepared_dataset
from recsys.evaluation import (
    popularity_order,
    popularity_recommendations,
    random_recommendations,
    reciprocal_rank_fusion,
    rrf_recommendations,
    sliced_metrics,
    target_by_user,
)

SERVING_POLICIES = ("als", "cosine", "bm25", "rrf")
CONTENT_ANALYZERS = ("word", "char_wb")
DEFAULT_COLD_QUOTAS = (1, 2, 3, 5)


@dataclass(frozen=True)
class TrainingConfig:
    seed: int
    factors: tuple[int, ...]
    iterations: int
    regularization: float
    alpha: float
    top_k: int
    item_item_neighbors: int
    retrieval_candidates: int
    bm25_k1: float
    bm25_b: float
    rrf_k: int
    content_analyzers: tuple[str, ...]
    cold_quotas: tuple[int, ...]
    content_candidate_pool: int


@dataclass
class ModelBundle:
    manifest: ModelManifest
    model: AlternatingLeastSquares
    user_items: sparse.csr_matrix
    user_ids: list[int]
    item_ids: list[int]
    popularity: list[int]
    cosine_model: ItemItemRecommender | None = None
    bm25_model: ItemItemRecommender | None = None
    content_retriever: TitleTfidfRetriever | None = None

    @cached_property
    def user_to_index(self) -> dict[int, int]:
        return {value: index for index, value in enumerate(self.user_ids)}

    @cached_property
    def item_to_index(self) -> dict[int, int]:
        return {value: index for index, value in enumerate(self.item_ids)}

    def _filters(
        self, user_index: int, excluded: set[int]
    ) -> tuple[np.ndarray, set[int]]:
        cold_indices = np.flatnonzero(
            np.asarray(self.user_items.sum(axis=0)).ravel() == 0
        )
        item_to_index = self.item_to_index
        excluded_indices = np.asarray(
            [item_to_index[item_id] for item_id in excluded if item_id in item_to_index],
            dtype=np.int64,
        )
        filter_indices = np.unique(np.concatenate([cold_indices, excluded_indices]))
        blocked = set(self.user_items[user_index].indices.tolist())
        blocked.update(filter_indices.tolist())
        return filter_indices, blocked

    def _recommend_indices(
        self,
        retriever: AlternatingLeastSquares | ItemItemRecommender,
        user_index: int,
        *,
        limit: int,
        filter_indices: np.ndarray,
        blocked: set[int],
    ) -> list[tuple[int, float]]:
        item_indices, scores = retriever.recommend(
            user_index,
            self.user_items[user_index],
            N=min(limit, self.user_items.shape[1]),
            filter_already_liked_items=True,
            filter_items=filter_indices,
        )
        ranked = [
            (int(item_index), float(score))
            for item_index, score in zip(item_indices, scores, strict=True)
            if int(item_index) >= 0 and int(item_index) not in blocked
        ]
        # implicit ItemItemRecommender temporarily expands N by filter_items length.
        return ranked[:limit]

    def recommend(
        self,
        user_id: int,
        *,
        limit: int,
        exclude_item_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Recommend business item IDs according to the manifest serving policy."""
        if limit <= 0:
            return []
        excluded = exclude_item_ids or set()
        user_index = self.user_to_index.get(user_id)
        if user_index is None:
            return [
                (item_id, 0.0)
                for item_id in self.popularity
                if item_id not in excluded
            ][:limit]

        filter_indices, blocked = self._filters(user_index, excluded)
        policy = self.manifest.serving_policy
        if policy == "als":
            ranked = self._recommend_indices(
                self.model,
                user_index,
                limit=limit,
                filter_indices=filter_indices,
                blocked=blocked,
            )
        elif policy == "cosine":
            if self.cosine_model is None:
                raise RuntimeError("cosine serving policy has no cosine artifact")
            ranked = self._recommend_indices(
                self.cosine_model,
                user_index,
                limit=limit,
                filter_indices=filter_indices,
                blocked=blocked,
            )
        elif policy == "bm25":
            if self.bm25_model is None:
                raise RuntimeError("bm25 serving policy has no BM25 artifact")
            ranked = self._recommend_indices(
                self.bm25_model,
                user_index,
                limit=limit,
                filter_indices=filter_indices,
                blocked=blocked,
            )
        elif policy == "rrf":
            if self.bm25_model is None:
                raise RuntimeError("rrf serving policy has no BM25 artifact")
            source_limit = max(limit, min(int(self.bm25_model.K), 100))
            als_ranked = self._recommend_indices(
                self.model,
                user_index,
                limit=source_limit,
                filter_indices=filter_indices,
                blocked=blocked,
            )
            bm25_ranked = self._recommend_indices(
                self.bm25_model,
                user_index,
                limit=source_limit,
                filter_indices=filter_indices,
                blocked=blocked,
            )
            ranked = reciprocal_rank_fusion(
                ([item for item, _ in als_ranked], [item for item, _ in bm25_ranked]),
                rrf_k=self.manifest.rrf_k,
                limit=limit,
            )
        elif policy == "bm25_content":
            if self.bm25_model is None or self.content_retriever is None:
                raise RuntimeError("bm25_content serving policy has incomplete artifacts")
            hybrid_k = max(limit, self.manifest.top_k)
            source_limit = max(hybrid_k, self.content_retriever.manifest.candidate_pool)
            warm_ranked = self._recommend_indices(
                self.bm25_model,
                user_index,
                limit=source_limit,
                filter_indices=filter_indices,
                blocked=blocked,
            )
            cold_ranked = self.content_retriever.recommend(
                user_id,
                limit=source_limit,
                exclude_item_ids=excluded,
            )
            final_item_ids = hybrid_tail_quota(
                (self.item_ids[item_index] for item_index, _ in warm_ranked),
                (item_id for item_id, _ in cold_ranked),
                k=hybrid_k,
                cold_quota=self.content_retriever.manifest.cold_quota,
            )[:limit]
            score_denominator = len(final_item_ids) + 1
            return [
                (item_id, 1.0 - rank / score_denominator)
                for rank, item_id in enumerate(final_item_ids, start=1)
            ]
        else:
            raise RuntimeError(f"unsupported serving policy: {policy}")

        return [(self.item_ids[item_index], score) for item_index, score in ranked]


def load_training_config(path: Path) -> TrainingConfig:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    data, model = payload["data"], payload["model"]
    item_item = payload.get("item_item", {})
    fusion = payload.get("fusion", {})
    content = payload.get("content", {})
    factors = tuple(int(value) for value in model["factors"])
    top_k = int(model["top_k"])
    if not factors or any(value <= 0 for value in factors):
        raise ValueError("model.factors must contain positive integers")
    config = TrainingConfig(
        seed=int(data.get("seed", 42)),
        factors=factors,
        iterations=int(model["iterations"]),
        regularization=float(model["regularization"]),
        alpha=float(model["alpha"]),
        top_k=top_k,
        item_item_neighbors=int(item_item.get("neighbors", 100)),
        retrieval_candidates=int(item_item.get("candidate_pool_size", max(100, top_k))),
        bm25_k1=float(item_item.get("bm25_k1", 1.2)),
        bm25_b=float(item_item.get("bm25_b", 0.75)),
        rrf_k=int(fusion.get("rrf_k", 60)),
        content_analyzers=tuple(content.get("analyzers", CONTENT_ANALYZERS)),
        cold_quotas=tuple(
            int(value) for value in content.get("cold_quotas", DEFAULT_COLD_QUOTAS)
        ),
        content_candidate_pool=int(
            content.get("candidate_pool_size", max(100, top_k))
        ),
    )
    if min(
        config.iterations,
        config.top_k,
        config.item_item_neighbors,
        config.retrieval_candidates,
        config.rrf_k,
        config.content_candidate_pool,
    ) <= 0:
        raise ValueError("iterations, K values and candidate sizes must be positive")
    if config.retrieval_candidates < config.top_k:
        raise ValueError("item_item.candidate_pool_size cannot be smaller than top_k")
    if not config.content_analyzers or any(
        analyzer not in CONTENT_ANALYZERS for analyzer in config.content_analyzers
    ):
        raise ValueError(f"content.analyzers must use {CONTENT_ANALYZERS}")
    if not config.cold_quotas or any(
        quota not in DEFAULT_COLD_QUOTAS for quota in config.cold_quotas
    ):
        raise ValueError(f"content.cold_quotas must use {DEFAULT_COLD_QUOTAS}")
    return config


def _fit_als(matrix: sparse.csr_matrix, config: TrainingConfig, factors: int):
    model = AlternatingLeastSquares(
        factors=factors,
        iterations=config.iterations,
        regularization=config.regularization,
        random_state=config.seed,
        num_threads=1,
    )
    model.fit((matrix * config.alpha).astype(np.float32), show_progress=False)
    return model


def _fit_cosine(matrix: sparse.csr_matrix, config: TrainingConfig):
    model = CosineRecommender(K=config.item_item_neighbors, num_threads=1)
    model.fit(matrix, show_progress=False)
    return model


def _fit_bm25(matrix: sparse.csr_matrix, config: TrainingConfig):
    model = BM25Recommender(
        K=config.item_item_neighbors,
        K1=config.bm25_k1,
        B=config.bm25_b,
        num_threads=1,
    )
    model.fit(matrix, show_progress=False)
    return model


def _als_recommendations(model, user_items, *, k: int) -> dict[int, list[int]]:
    cold_items = np.flatnonzero(np.asarray(user_items.sum(axis=0)).ravel() == 0)
    cold_item_set = set(cold_items.tolist())
    recommendations: dict[int, list[int]] = {}
    batch_size = 5_000
    for batch_start in range(0, user_items.shape[0], batch_size):
        user_indices = np.arange(
            batch_start, min(batch_start + batch_size, user_items.shape[0])
        )
        item_indices, _ = model.recommend(
            user_indices,
            user_items[user_indices],
            N=min(k, user_items.shape[1]),
            filter_already_liked_items=True,
            filter_items=cold_items,
        )
        for user_index, ranked in zip(user_indices, item_indices, strict=True):
            blocked_items = set(user_items[int(user_index)].indices.tolist()) | cold_item_set
            recommendations[int(user_index)] = [
                int(item)
                for item in ranked
                if int(item) >= 0 and int(item) not in blocked_items
            ]
    return recommendations


def _item_item_recommendations(model, user_items, *, k: int) -> dict[int, list[int]]:
    cold_items = np.flatnonzero(np.asarray(user_items.sum(axis=0)).ravel() == 0)
    cold_item_set = set(cold_items.tolist())
    recommendations: dict[int, list[int]] = {}
    for user_index in range(user_items.shape[0]):
        item_indices, _ = model.recommend(
            user_index,
            user_items[user_index],
            N=min(k, user_items.shape[1]),
            filter_already_liked_items=True,
            filter_items=cold_items,
        )
        blocked_items = set(user_items[user_index].indices.tolist()) | cold_item_set
        recommendations[user_index] = [
            int(item)
            for item in item_indices
            if int(item) >= 0 and int(item) not in blocked_items
        ][:k]
    return recommendations


def _history_by_user(
    dataset: PreparedDataset, *, splits: tuple[str, ...]
) -> dict[int, tuple[int, ...]]:
    frame = pd.read_csv(dataset.path / "interactions.csv")
    frame = frame.loc[frame["split"].isin(splits)].sort_values(
        ["user_id", "sequence_position"], kind="stable"
    )
    return {
        int(user_id): tuple(int(item_id) for item_id in group["item_id"])
        for user_id, group in frame.groupby("user_id", sort=False)
    }


def _content_recommendations(
    retriever: TitleTfidfRetriever,
    dataset: PreparedDataset,
    *,
    k: int,
) -> dict[int, list[int]]:
    item_to_index = retriever.item_to_index
    return {
        user_index: [
            item_to_index[item_id]
            for item_id, _ in retriever.recommend(user_id, limit=k)
        ]
        for user_index, user_id in enumerate(dataset.user_ids)
    }


def _hybrid_content_recommendations(
    warm_recommendations: dict[int, list[int]],
    cold_recommendations: dict[int, list[int]],
    *,
    k: int,
    cold_quota: int,
) -> dict[int, list[int]]:
    return {
        user_index: hybrid_tail_quota(
            warm_recommendations.get(user_index, []),
            cold_recommendations.get(user_index, []),
            k=k,
            cold_quota=cold_quota,
        )
        for user_index in warm_recommendations
    }


def _content_policy_name(analyzer: str, cold_quota: int) -> str:
    return f"bm25_content_{analyzer}_q{cold_quota}"


def _evaluate_all(recommendations, targets, user_items, *, k: int):
    warm_items = set(np.flatnonzero(np.asarray(user_items.sum(axis=0)).ravel() > 0).tolist())
    return sliced_metrics(
        recommendations,
        targets,
        warm_items=warm_items,
        catalog_size=user_items.shape[1],
        k=k,
    )


def _metric_payload(metrics: dict[str, MetricSet]) -> dict[str, dict[str, float]]:
    return {name: metric.model_dump() for name, metric in metrics.items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as target:
            temporary_path = Path(target.name)
            json.dump(payload, target, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _resolve_dataset(path: Path) -> PreparedDataset:
    return load_prepared_dataset(path / "latest.json" if (path / "latest.json").exists() else path)


def _select_policy(
    report: dict[str, dict[str, dict[str, float]]],
    policies: tuple[str, ...],
) -> tuple[str, float]:
    selected_policy = policies[0]
    best_ndcg = -1.0
    for policy in policies:
        ndcg = report[policy]["overall"]["ndcg_at_k"]
        if ndcg > best_ndcg:
            selected_policy = policy
            best_ndcg = ndcg
    return selected_policy, best_ndcg


def _ordered_content_analyzers(analyzers: tuple[str, ...]) -> tuple[str, ...]:
    """Freeze exact-tie preference independently from the TOML list order."""
    return tuple(sorted(analyzers, key=lambda analyzer: (analyzer != "word", analyzer)))


def train_pipeline(
    processed_path: Path,
    artifact_root: Path,
    config_path: Path,
    *,
    activate: bool = False,
) -> Path:
    """Select a retrieval policy on validation, retrain, then evaluate test once."""
    dataset = _resolve_dataset(processed_path)
    config = load_training_config(config_path)
    train = sparse.load_npz(dataset.path / "train_matrix.npz").tocsr()
    validation = sparse.load_npz(dataset.path / "validation_matrix.npz").tocsr()
    test = sparse.load_npz(dataset.path / "test_matrix.npz").tocsr()
    validation_targets = target_by_user(validation)
    test_targets = target_by_user(test)
    item_frame = pd.read_csv(dataset.path / "items.csv")
    item_frame["title"] = item_frame["title"].fillna("")
    item_frame = item_frame.set_index("item_id")
    titles = [str(item_frame.at[item_id, "title"]) for item_id in dataset.item_ids]
    validation_histories = _history_by_user(dataset, splits=("train",))

    validation_report: dict[str, dict[str, dict[str, float]]] = {}
    selected_factors = config.factors[0]
    best_als_ndcg = -1.0
    best_als_recommendations: dict[int, list[int]] = {}
    for factors in config.factors:
        candidate = _fit_als(train, config, factors)
        recommendations = _als_recommendations(
            candidate, train, k=config.retrieval_candidates
        )
        metrics = _evaluate_all(
            recommendations, validation_targets, train, k=config.top_k
        )
        validation_report[f"als_{factors}"] = _metric_payload(metrics)
        if metrics["overall"].ndcg_at_k > best_als_ndcg:
            best_als_ndcg = metrics["overall"].ndcg_at_k
            selected_factors = factors
            best_als_recommendations = recommendations
    validation_report["als"] = validation_report[f"als_{selected_factors}"]

    cosine_model = _fit_cosine(train, config)
    cosine_recommendations = _item_item_recommendations(
        cosine_model, train, k=config.top_k
    )
    validation_report["cosine"] = _metric_payload(
        _evaluate_all(cosine_recommendations, validation_targets, train, k=config.top_k)
    )

    bm25_model = _fit_bm25(train, config)
    bm25_recommendations = _item_item_recommendations(
        bm25_model, train, k=config.retrieval_candidates
    )
    validation_report["bm25"] = _metric_payload(
        _evaluate_all(bm25_recommendations, validation_targets, train, k=config.top_k)
    )
    fused_recommendations = rrf_recommendations(
        [best_als_recommendations, bm25_recommendations],
        rrf_k=config.rrf_k,
        limit=config.top_k,
    )
    validation_report["rrf"] = _metric_payload(
        _evaluate_all(fused_recommendations, validation_targets, train, k=config.top_k)
    )

    validation_content_rankings: dict[str, dict[int, list[int]]] = {}
    ordered_content_analyzers = _ordered_content_analyzers(config.content_analyzers)
    for analyzer in ordered_content_analyzers:
        retriever = fit_title_tfidf(
            item_ids=dataset.item_ids,
            titles=titles,
            fit_matrix=train,
            user_histories=validation_histories,
            analyzer=analyzer,
            candidate_pool=config.content_candidate_pool,
        )
        validation_content_rankings[analyzer] = _content_recommendations(
            retriever,
            dataset,
            k=config.content_candidate_pool,
        )

    content_policy_details: dict[str, tuple[str, int]] = {}
    for cold_quota in sorted(quota for quota in config.cold_quotas if quota <= config.top_k):
        for analyzer in ordered_content_analyzers:
            policy_name = _content_policy_name(analyzer, cold_quota)
            content_policy_details[policy_name] = (analyzer, cold_quota)
            recommendations = _hybrid_content_recommendations(
                bm25_recommendations,
                validation_content_rankings[analyzer],
                k=config.top_k,
                cold_quota=cold_quota,
            )
            validation_report[policy_name] = _metric_payload(
                _evaluate_all(recommendations, validation_targets, train, k=config.top_k)
            )

    selection_order = (*SERVING_POLICIES, *content_policy_details)
    selected_candidate, selected_validation_ndcg = _select_policy(
        validation_report, selection_order
    )
    selected_policy = (
        "bm25_content" if selected_candidate in content_policy_details else selected_candidate
    )
    best_content_candidate, _ = _select_policy(
        validation_report, tuple(content_policy_details)
    )
    selected_content_candidate = (
        selected_candidate
        if selected_candidate in content_policy_details
        else best_content_candidate
    )
    selected_analyzer, selected_cold_quota = content_policy_details[
        selected_content_candidate
    ]

    for name, recommendations in {
        "random": random_recommendations(train, k=config.top_k, seed=config.seed),
        "popularity": popularity_recommendations(train, k=config.top_k),
    }.items():
        validation_report[name] = _metric_payload(
            _evaluate_all(recommendations, validation_targets, train, k=config.top_k)
        )

    serving_matrix = (train + validation).tocsr()
    serving_histories = _history_by_user(dataset, splits=("train", "validation"))
    selected_als_model = _fit_als(serving_matrix, config, selected_factors)
    serving_cosine_model = _fit_cosine(serving_matrix, config)
    serving_bm25_model = _fit_bm25(serving_matrix, config)
    test_bm25_recommendations = _item_item_recommendations(
        serving_bm25_model, serving_matrix, k=config.retrieval_candidates
    )
    serving_content_retriever = fit_title_tfidf(
        item_ids=dataset.item_ids,
        titles=titles,
        fit_matrix=serving_matrix,
        user_histories=serving_histories,
        analyzer=selected_analyzer,
        candidate_pool=config.content_candidate_pool,
        cold_quota=selected_cold_quota,
    )
    test_recommendations = {"bm25": test_bm25_recommendations}
    if selected_candidate == "als":
        test_recommendations["als"] = _als_recommendations(
            selected_als_model, serving_matrix, k=config.retrieval_candidates
        )
    elif selected_candidate == "cosine":
        test_recommendations["cosine"] = _item_item_recommendations(
            serving_cosine_model, serving_matrix, k=config.top_k
        )
    elif selected_candidate == "rrf":
        test_als_recommendations = _als_recommendations(
            selected_als_model, serving_matrix, k=config.retrieval_candidates
        )
        test_recommendations["rrf"] = rrf_recommendations(
            [test_als_recommendations, test_bm25_recommendations],
            rrf_k=config.rrf_k,
            limit=config.top_k,
        )
    elif selected_candidate in content_policy_details:
        test_content_recommendations = _content_recommendations(
            serving_content_retriever,
            dataset,
            k=config.content_candidate_pool,
        )
        test_recommendations[selected_candidate] = _hybrid_content_recommendations(
            test_bm25_recommendations,
            test_content_recommendations,
            k=config.top_k,
            cold_quota=selected_cold_quota,
        )
    test_report = {
        name: _metric_payload(
            _evaluate_all(recommendations, test_targets, serving_matrix, k=config.top_k)
        )
        for name, recommendations in test_recommendations.items()
    }

    created_at = datetime.now(UTC)
    model_version = (
        f"hybrid-{selected_policy}-f{selected_factors}-{dataset.data_version}-"
        f"{created_at:%Y%m%dT%H%M%S%fZ}"
    )
    output = artifact_root / model_version
    output.mkdir(parents=True, exist_ok=False)
    als_file = output / "als_model.npz"
    cosine_file = output / "cosine_model.npz"
    bm25_file = output / "bm25_model.npz"
    selected_als_model.save(als_file)
    serving_cosine_model.save(cosine_file)
    serving_bm25_model.save(bm25_file)
    serving_content_retriever.save(output)
    sparse.save_npz(output / "serving_user_items.npz", serving_matrix, compressed=True)
    (output / "mappings.json").write_text(
        json.dumps({"user_ids": dataset.user_ids, "item_ids": dataset.item_ids}),
        encoding="utf-8",
    )
    popularity_indices = popularity_order(serving_matrix).astype(int).tolist()
    popularity_item_ids = [dataset.item_ids[index] for index in popularity_indices]
    (output / "popularity.json").write_text(
        json.dumps(popularity_item_ids), encoding="utf-8"
    )

    validation_warm_items = set(train.indices.tolist())
    test_warm_items = set(serving_matrix.indices.tolist())
    selection_metric = f"validation.overall.ndcg_at_{config.top_k}"
    metrics_payload = {
        "protocol": {
            "split": "per-user leave-last-two: train / validation / test",
            "selection": (
                "highest validation overall NDCG@K; exact ties prefer lower cold quota, "
                "then word analyzer"
            ),
            "test_usage": (
                "evaluate the frozen policy and BM25 baseline once after train+validation "
                "retraining"
            ),
            "coverage_denominator": len(dataset.item_ids),
            "rrf": f"equal sum(1 / ({config.rrf_k} + one_based_rank))",
            "content_hybrid": "BM25 head plus TF-IDF pure-cold candidates in reserved tail",
        },
        "selection": {
            "metric": selection_metric,
            "selected_factors": selected_factors,
            "selected_policy": selected_policy,
            "selected_candidate": selected_candidate,
            "best_content_candidate": best_content_candidate,
            "content_analyzer": selected_analyzer,
            "cold_quota": selected_cold_quota,
            "validation_ndcg_at_k": selected_validation_ndcg,
        },
        "slices": {
            "validation": {
                "total_targets": len(validation_targets),
                "warm_targets": sum(
                    target in validation_warm_items for target in validation_targets.values()
                ),
                "pure_cold_targets": sum(
                    target not in validation_warm_items
                    for target in validation_targets.values()
                ),
            },
            "test": {
                "total_targets": len(test_targets),
                "warm_targets": sum(
                    target in test_warm_items for target in test_targets.values()
                ),
                "pure_cold_targets": sum(
                    target not in test_warm_items for target in test_targets.values()
                ),
            },
        },
        "validation": validation_report,
        "test": test_report,
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics_payload, indent=2), encoding="utf-8"
    )

    history_by_user = {
        user_id: list(history[-10:]) for user_id, history in serving_histories.items()
    }
    rows = []
    selected_test_recommendations = test_recommendations[selected_candidate]
    for user_index, target_index in test_targets.items():
        ranked = selected_test_recommendations[user_index]
        if target_index in ranked[: config.top_k]:
            continue
        user_id = dataset.user_ids[user_index]
        rows.append(
            {
                "user_id": user_id,
                "target_item_id": dataset.item_ids[target_index],
                "target_is_warm": target_index in test_warm_items,
                "serving_policy": selected_candidate,
                "history_item_ids": json.dumps(history_by_user[user_id]),
                "recommended_item_ids": json.dumps(
                    [dataset.item_ids[index] for index in ranked[: config.top_k]]
                ),
            }
        )
    pd.DataFrame(
        rows,
        columns=[
            "user_id",
            "target_item_id",
            "target_is_warm",
            "serving_policy",
            "history_item_ids",
            "recommended_item_ids",
        ],
    ).to_csv(output / "badcases.csv", index=False)

    manifest_metrics = {
        f"test_{policy}_{slice_name}": MetricSet.model_validate(values)
        for policy, slices in test_report.items()
        for slice_name, values in slices.items()
    }
    retrievers = {
        "als": ["als"],
        "cosine": ["cosine"],
        "bm25": ["bm25"],
        "rrf": ["als", "bm25"],
        "bm25_content": ["bm25", "title_tfidf"],
    }[selected_policy]
    manifest = ModelManifest(
        model_version=model_version,
        data_version=dataset.data_version,
        created_at=created_at,
        algorithm="validation-selected ALS / Item-Item CF / RRF / title TF-IDF",
        factors=selected_factors,
        iterations=config.iterations,
        regularization=config.regularization,
        alpha=config.alpha,
        top_k=config.top_k,
        files={
            "model": als_file.name,
            "cosine_model": cosine_file.name,
            "bm25_model": bm25_file.name,
            "user_items": "serving_user_items.npz",
            "mappings": "mappings.json",
            "popularity": "popularity.json",
            "metrics": "metrics.json",
            "badcases": "badcases.csv",
            "checksums": "checksums.json",
            "content_items": ITEM_VECTORS_FILE,
            "content_config": CONTENT_CONFIG_FILE,
        },
        metrics=manifest_metrics,
        serving_policy=selected_policy,
        retrievers=retrievers,
        rrf_k=config.rrf_k,
        selection_metric=selection_metric,
        content_retriever=serving_content_retriever.manifest,
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    checksum_targets = [
        "manifest.json",
        "als_model.npz",
        "cosine_model.npz",
        "bm25_model.npz",
        "serving_user_items.npz",
        "mappings.json",
        "popularity.json",
        "metrics.json",
        "badcases.csv",
        ITEM_VECTORS_FILE,
        CONTENT_CONFIG_FILE,
    ]
    (output / "checksums.json").write_text(
        json.dumps({name: _sha256(output / name) for name in checksum_targets}, indent=2),
        encoding="utf-8",
    )
    if activate:
        pointer_path = artifact_root / "latest.json"
        previous = None
        if pointer_path.is_file():
            previous = ArtifactPointer.model_validate_json(
                pointer_path.read_text(encoding="utf-8")
            ).current
        pointer = ArtifactPointer(
            current={"model_version": model_version, "path": model_version},
            previous=previous,
            updated_at=created_at,
        )
        _atomic_write_json(pointer_path, pointer.model_dump(mode="json"))
    return output


def load_model_bundle(path: Path) -> ModelBundle:
    if path.name == "latest.json":
        pointer = ArtifactPointer.model_validate_json(path.read_text(encoding="utf-8"))
        path = path.parent / pointer.current.path
    elif (path / "latest.json").exists() and not (path / "manifest.json").exists():
        pointer = ArtifactPointer.model_validate_json(
            (path / "latest.json").read_text(encoding="utf-8")
        )
        path = path / pointer.current.path
    manifest = ModelManifest.model_validate_json(
        (path / "manifest.json").read_text(encoding="utf-8")
    )
    mappings = json.loads((path / manifest.files["mappings"]).read_text(encoding="utf-8"))
    cosine_model = None
    if cosine_file := manifest.files.get("cosine_model"):
        cosine_model = CosineRecommender.load(path / cosine_file)
    bm25_model = None
    if bm25_file := manifest.files.get("bm25_model"):
        bm25_model = BM25Recommender.load(path / bm25_file)
    content_retriever = None
    if manifest.files.get("content_items") and manifest.files.get("content_config"):
        content_retriever = load_title_tfidf(path)
    return ModelBundle(
        manifest=manifest,
        model=AlternatingLeastSquares.load(path / manifest.files["model"]),
        user_items=sparse.load_npz(path / manifest.files["user_items"]).tocsr(),
        user_ids=[int(value) for value in mappings["user_ids"]],
        item_ids=[int(value) for value in mappings["item_ids"]],
        popularity=[
            int(value)
            for value in json.loads(
                (path / manifest.files["popularity"]).read_text(encoding="utf-8")
            )
        ],
        cosine_model=cosine_model,
        bm25_model=bm25_model,
        content_retriever=content_retriever,
    )

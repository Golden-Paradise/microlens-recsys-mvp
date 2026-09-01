from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
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

from recsys.contracts import MetricSet, ModelManifest
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

    @property
    def user_to_index(self) -> dict[int, int]:
        return {value: index for index, value in enumerate(self.user_ids)}

    @property
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
        else:
            raise RuntimeError(f"unsupported serving policy: {policy}")

        return [(self.item_ids[item_index], score) for item_index, score in ranked]


def load_training_config(path: Path) -> TrainingConfig:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    data, model = payload["data"], payload["model"]
    item_item = payload.get("item_item", {})
    fusion = payload.get("fusion", {})
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
    )
    if min(
        config.iterations,
        config.top_k,
        config.item_item_neighbors,
        config.retrieval_candidates,
        config.rrf_k,
    ) <= 0:
        raise ValueError("iterations, K values and candidate sizes must be positive")
    if config.retrieval_candidates < config.top_k:
        raise ValueError("item_item.candidate_pool_size cannot be smaller than top_k")
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


def _resolve_dataset(path: Path) -> PreparedDataset:
    return load_prepared_dataset(path / "latest.json" if (path / "latest.json").exists() else path)


def _select_policy(
    report: dict[str, dict[str, dict[str, float]]],
) -> tuple[str, float]:
    selected_policy = SERVING_POLICIES[0]
    best_ndcg = -1.0
    for policy in SERVING_POLICIES:
        ndcg = report[policy]["overall"]["ndcg_at_k"]
        if ndcg > best_ndcg:
            selected_policy = policy
            best_ndcg = ndcg
    return selected_policy, best_ndcg


def train_pipeline(
    processed_path: Path,
    artifact_root: Path,
    config_path: Path,
) -> Path:
    """Select a retrieval policy on validation, retrain, then evaluate test once."""
    dataset = _resolve_dataset(processed_path)
    config = load_training_config(config_path)
    train = sparse.load_npz(dataset.path / "train_matrix.npz").tocsr()
    validation = sparse.load_npz(dataset.path / "validation_matrix.npz").tocsr()
    test = sparse.load_npz(dataset.path / "test_matrix.npz").tocsr()
    validation_targets = target_by_user(validation)
    test_targets = target_by_user(test)

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
    selected_policy, selected_validation_ndcg = _select_policy(validation_report)

    for name, recommendations in {
        "random": random_recommendations(train, k=config.top_k, seed=config.seed),
        "popularity": popularity_recommendations(train, k=config.top_k),
    }.items():
        validation_report[name] = _metric_payload(
            _evaluate_all(recommendations, validation_targets, train, k=config.top_k)
        )

    serving_matrix = (train + validation).tocsr()
    selected_als_model = _fit_als(serving_matrix, config, selected_factors)
    serving_cosine_model = _fit_cosine(serving_matrix, config)
    serving_bm25_model = _fit_bm25(serving_matrix, config)
    test_als_recommendations = _als_recommendations(
        selected_als_model, serving_matrix, k=config.retrieval_candidates
    )
    test_cosine_recommendations = _item_item_recommendations(
        serving_cosine_model, serving_matrix, k=config.top_k
    )
    test_bm25_recommendations = _item_item_recommendations(
        serving_bm25_model, serving_matrix, k=config.retrieval_candidates
    )
    test_rrf_recommendations = rrf_recommendations(
        [test_als_recommendations, test_bm25_recommendations],
        rrf_k=config.rrf_k,
        limit=config.top_k,
    )
    test_recommendations = {
        "als": test_als_recommendations,
        "cosine": test_cosine_recommendations,
        "bm25": test_bm25_recommendations,
        "rrf": test_rrf_recommendations,
        "random": random_recommendations(
            serving_matrix, k=config.top_k, seed=config.seed
        ),
        "popularity": popularity_recommendations(serving_matrix, k=config.top_k),
    }
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
            "selection": "highest validation overall NDCG@K; stable policy order breaks ties",
            "test_usage": "evaluate frozen policies once after train+validation retraining",
            "coverage_denominator": len(dataset.item_ids),
            "rrf": f"equal sum(1 / ({config.rrf_k} + one_based_rank))",
        },
        "selection": {
            "metric": selection_metric,
            "selected_factors": selected_factors,
            "selected_policy": selected_policy,
            "validation_ndcg_at_k": selected_validation_ndcg,
        },
        "slices": {
            "validation": {
                "total_targets": len(validation_targets),
                "warm_targets": sum(
                    target in validation_warm_items for target in validation_targets.values()
                ),
            },
            "test": {
                "total_targets": len(test_targets),
                "warm_targets": sum(
                    target in test_warm_items for target in test_targets.values()
                ),
            },
        },
        "validation": validation_report,
        "test": test_report,
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics_payload, indent=2), encoding="utf-8"
    )

    history_frame = pd.read_csv(dataset.path / "interactions.csv")
    history_frame = history_frame.loc[history_frame["split"].isin(["train", "validation"])]
    history_by_user = {
        int(user_id): group.sort_values("sequence_position")["item_id"].tail(10).tolist()
        for user_id, group in history_frame.groupby("user_id", sort=False)
    }
    rows = []
    selected_test_recommendations = test_recommendations[selected_policy]
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
                "serving_policy": selected_policy,
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

    checksum_targets = [
        "als_model.npz",
        "cosine_model.npz",
        "bm25_model.npz",
        "serving_user_items.npz",
        "mappings.json",
        "popularity.json",
        "metrics.json",
        "badcases.csv",
    ]
    (output / "checksums.json").write_text(
        json.dumps({name: _sha256(output / name) for name in checksum_targets}, indent=2),
        encoding="utf-8",
    )
    manifest_metrics = {
        f"test_{policy}_{slice_name}": MetricSet.model_validate(values)
        for policy in (*SERVING_POLICIES, "random", "popularity")
        for slice_name, values in test_report[policy].items()
    }
    retrievers = {
        "als": ["als"],
        "cosine": ["cosine"],
        "bm25": ["bm25"],
        "rrf": ["als", "bm25"],
    }[selected_policy]
    manifest = ModelManifest(
        model_version=model_version,
        data_version=dataset.data_version,
        created_at=created_at,
        algorithm="validation-selected implicit ALS / Item-Item CF / RRF",
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
        },
        metrics=manifest_metrics,
        serving_policy=selected_policy,
        retrievers=retrievers,
        rrf_k=config.rrf_k,
        selection_metric=selection_metric,
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    (artifact_root / "latest.json").write_text(
        json.dumps({"model_version": model_version, "path": model_version}, indent=2),
        encoding="utf-8",
    )
    return output


def load_model_bundle(path: Path) -> ModelBundle:
    if path.name == "latest.json":
        pointer = json.loads(path.read_text(encoding="utf-8"))
        path = path.parent / pointer["path"]
    elif (path / "latest.json").exists() and not (path / "manifest.json").exists():
        pointer = json.loads((path / "latest.json").read_text(encoding="utf-8"))
        path = path / pointer["path"]
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
    )

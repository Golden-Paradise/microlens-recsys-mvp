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
from scipy import sparse

from recsys.contracts import MetricSet, ModelManifest
from recsys.data import PreparedDataset, load_prepared_dataset
from recsys.evaluation import (
    popularity_order,
    popularity_recommendations,
    random_recommendations,
    sliced_metrics,
    target_by_user,
)


@dataclass(frozen=True)
class TrainingConfig:
    seed: int
    factors: tuple[int, ...]
    iterations: int
    regularization: float
    alpha: float
    top_k: int


@dataclass
class ModelBundle:
    manifest: ModelManifest
    model: AlternatingLeastSquares
    user_items: sparse.csr_matrix
    user_ids: list[int]
    item_ids: list[int]
    popularity: list[int]

    @property
    def user_to_index(self) -> dict[int, int]:
        return {value: index for index, value in enumerate(self.user_ids)}

    @property
    def item_to_index(self) -> dict[int, int]:
        return {value: index for index, value in enumerate(self.item_ids)}

    def recommend(
        self,
        user_id: int,
        *,
        limit: int,
        exclude_item_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Return business item IDs; unknown users fall back to the training popularity list."""
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

        item_to_index = self.item_to_index
        cold_indices = np.flatnonzero(np.asarray(self.user_items.sum(axis=0)).ravel() == 0)
        excluded_indices = [
            item_to_index[item_id] for item_id in excluded if item_id in item_to_index
        ]
        filter_indices = np.unique(
            np.concatenate([cold_indices, np.asarray(excluded_indices, dtype=np.int64)])
        )
        ranked_indices, scores = self.model.recommend(
            user_index,
            self.user_items[user_index],
            N=min(limit, self.user_items.shape[1]),
            filter_already_liked_items=True,
            filter_items=filter_indices,
        )
        blocked_indices = set(self.user_items[user_index].indices.tolist())
        blocked_indices.update(filter_indices.tolist())
        return [
            (self.item_ids[int(item_index)], float(score))
            for item_index, score in zip(ranked_indices, scores, strict=True)
            if int(item_index) >= 0 and int(item_index) not in blocked_indices
        ]


def load_training_config(path: Path) -> TrainingConfig:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    data, model = payload["data"], payload["model"]
    factors = tuple(int(value) for value in model["factors"])
    if not factors or any(value <= 0 for value in factors):
        raise ValueError("model.factors must contain positive integers")
    return TrainingConfig(
        seed=int(data.get("seed", 42)),
        factors=factors,
        iterations=int(model["iterations"]),
        regularization=float(model["regularization"]),
        alpha=float(model["alpha"]),
        top_k=int(model["top_k"]),
    )


def _fit(matrix: sparse.csr_matrix, config: TrainingConfig, factors: int):
    model = AlternatingLeastSquares(
        factors=factors,
        iterations=config.iterations,
        regularization=config.regularization,
        random_state=config.seed,
        num_threads=1,
    )
    model.fit((matrix * config.alpha).astype(np.float32), show_progress=False)
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


def train_pipeline(
    processed_path: Path,
    artifact_root: Path,
    config_path: Path,
) -> Path:
    """Select ALS factors on validation, evaluate test once, then persist serving artifacts."""
    dataset = _resolve_dataset(processed_path)
    config = load_training_config(config_path)
    train = sparse.load_npz(dataset.path / "train_matrix.npz").tocsr()
    validation = sparse.load_npz(dataset.path / "validation_matrix.npz").tocsr()
    test = sparse.load_npz(dataset.path / "test_matrix.npz").tocsr()
    validation_targets = target_by_user(validation)
    test_targets = target_by_user(test)

    validation_report: dict[str, dict[str, dict[str, float]]] = {}
    selected_factors = config.factors[0]
    best_ndcg = -1.0
    for factors in config.factors:
        candidate = _fit(train, config, factors)
        metrics = _evaluate_all(
            _als_recommendations(candidate, train, k=config.top_k),
            validation_targets,
            train,
            k=config.top_k,
        )
        validation_report[f"als_{factors}"] = _metric_payload(metrics)
        ndcg = metrics["overall"].ndcg_at_k
        if ndcg > best_ndcg:
            best_ndcg = ndcg
            selected_factors = factors

    for name, recommendations in {
        "random": random_recommendations(train, k=config.top_k, seed=config.seed),
        "popularity": popularity_recommendations(train, k=config.top_k),
    }.items():
        validation_report[name] = _metric_payload(
            _evaluate_all(recommendations, validation_targets, train, k=config.top_k)
        )

    serving_matrix = (train + validation).tocsr()
    selected_model = _fit(serving_matrix, config, selected_factors)
    test_recommendations = _als_recommendations(
        selected_model, serving_matrix, k=config.top_k
    )
    test_report = {
        "als": _metric_payload(
            _evaluate_all(test_recommendations, test_targets, serving_matrix, k=config.top_k)
        ),
        "random": _metric_payload(
            _evaluate_all(
                random_recommendations(serving_matrix, k=config.top_k, seed=config.seed),
                test_targets,
                serving_matrix,
                k=config.top_k,
            )
        ),
        "popularity": _metric_payload(
            _evaluate_all(
                popularity_recommendations(serving_matrix, k=config.top_k),
                test_targets,
                serving_matrix,
                k=config.top_k,
            )
        ),
    }

    created_at = datetime.now(UTC)
    model_version = f"als-f{selected_factors}-{dataset.data_version}-{created_at:%Y%m%dT%H%M%S%fZ}"
    output = artifact_root / model_version
    output.mkdir(parents=True, exist_ok=False)
    model_file = output / "als_model.npz"
    selected_model.save(model_file)
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
    metrics_payload = {
        "protocol": {
            "split": "per-user leave-last-two: train / validation / test",
            "selection": "highest validation overall NDCG@K; ties keep fewer factors",
            "test_usage": "evaluate once after retraining selected factors on train+validation",
            "coverage_denominator": len(dataset.item_ids),
        },
        "selection": {
            "metric": f"validation.overall.ndcg_at_{config.top_k}",
            "selected_factors": selected_factors,
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

    warm_items = test_warm_items
    history_frame = pd.read_csv(dataset.path / "interactions.csv")
    history_frame = history_frame.loc[history_frame["split"].isin(["train", "validation"])]
    history_by_user = {
        int(user_id): group.sort_values("sequence_position")["item_id"].tail(10).tolist()
        for user_id, group in history_frame.groupby("user_id", sort=False)
    }
    rows = []
    for user_index, target_index in test_targets.items():
        ranked = test_recommendations[user_index]
        if target_index in ranked:
            continue
        user_id = dataset.user_ids[user_index]
        rows.append(
            {
                "user_id": user_id,
                "target_item_id": dataset.item_ids[target_index],
                "target_is_warm": target_index in warm_items,
                "history_item_ids": json.dumps(history_by_user[user_id]),
                "recommended_item_ids": json.dumps(
                    [dataset.item_ids[index] for index in ranked]
                ),
            }
        )
    # Preserve columns even when a synthetic test happens to have no misses.
    pd.DataFrame(
        rows,
        columns=[
            "user_id",
            "target_item_id",
            "target_is_warm",
            "history_item_ids",
            "recommended_item_ids",
        ],
    ).to_csv(output / "badcases.csv", index=False)

    manifest_metrics = {
        f"test_als_{slice_name}": MetricSet.model_validate(values)
        for slice_name, values in test_report["als"].items()
    }
    checksum_targets = [
        "als_model.npz",
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
    manifest = ModelManifest(
        model_version=model_version,
        data_version=dataset.data_version,
        created_at=created_at,
        algorithm="implicit.als.AlternatingLeastSquares",
        factors=selected_factors,
        iterations=config.iterations,
        regularization=config.regularization,
        alpha=config.alpha,
        top_k=config.top_k,
        files={
            "model": model_file.name,
            "user_items": "serving_user_items.npz",
            "mappings": "mappings.json",
            "popularity": "popularity.json",
            "metrics": "metrics.json",
            "badcases": "badcases.csv",
            "checksums": "checksums.json",
        },
        metrics=manifest_metrics,
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
    )

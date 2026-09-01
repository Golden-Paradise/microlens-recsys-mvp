from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.constants import FeedType
from app.models import Item
from app.recommendation import ALSRecommendationEngine
from recsys.contracts import MetricSet
from recsys.data import OFFICIAL_FILES, prepare_dataset
from recsys.evaluation import ranking_metrics, reciprocal_rank_fusion
from recsys.model import load_model_bundle, train_pipeline


def _write_raw(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True)
    (raw_dir / OFFICIAL_FILES["pairs"]).write_text(
        "1\t1 2 3 4 5\n"
        "2\t2 3 1 5 6\n"
        "3\t3 1 2 6 4\n"
        "4\t1 3 2 4 6\n",
        encoding="utf-8",
    )
    (raw_dir / OFFICIAL_FILES["titles"]).write_text(
        "item,title\n" + "".join(f'{item},"Item {item}"\n' for item in range(1, 7)),
        encoding="utf-8",
    )
    (raw_dir / OFFICIAL_FILES["stats"]).write_text(
        "".join(f"{item}\t{item * 10}\t{item * 100}\n" for item in range(1, 7)),
        encoding="utf-8",
    )


@pytest.fixture
def prepared(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    _write_raw(raw_dir)
    return prepare_dataset(raw_dir, tmp_path / "processed")


def test_leave_last_two_split_has_no_temporal_leakage(prepared) -> None:
    import pandas as pd

    interactions = pd.read_csv(prepared.path / "interactions.csv")
    assert prepared.summary.train_interactions == 12
    assert prepared.summary.validation_interactions == 4
    assert prepared.summary.test_interactions == 4
    for _, group in interactions.groupby("user_id"):
        train_max = group.loc[group["split"].eq("train"), "sequence_position"].max()
        validation_position = group.loc[
            group["split"].eq("validation"), "sequence_position"
        ].item()
        test_position = group.loc[group["split"].eq("test"), "sequence_position"].item()
        assert train_max < validation_position < test_position
    summary = json.loads((prepared.path / "summary.json").read_text(encoding="utf-8"))
    assert summary["absolute_timestamps_available"] is False
    assert (prepared.path / "train_matrix.npz").is_file()
    histories = pd.read_csv(prepared.path / "user_histories.csv")
    assert len(histories) == 4
    assert json.loads(histories.loc[histories["user_id"].eq(1), "history_item_ids"].item()) == [
        1,
        2,
        3,
    ]


def test_ranking_metrics_known_example() -> None:
    metrics = ranking_metrics(
        {1: [8, 9], 2: [4, 5], 3: [7, 6]},
        {1: 9, 2: 4, 3: 3},
        catalog_size=10,
        k=2,
    )
    assert isinstance(metrics, MetricSet)
    assert metrics.recall_at_k == pytest.approx(2 / 3)
    assert metrics.ndcg_at_k == pytest.approx((1 / 1.584962500721156 + 1) / 3)
    assert metrics.coverage_at_k == pytest.approx(0.6)


def test_reciprocal_rank_fusion_is_equal_weighted_and_stable() -> None:
    fused = reciprocal_rank_fusion(
        [[2, 1, 2], [1, 2, 3]],
        rrf_k=60,
        limit=3,
    )
    assert [item_id for item_id, _ in fused] == [1, 2, 3]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1][1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[2][1] == pytest.approx(1 / 63)


def test_train_save_and_load_bundle(prepared, tmp_path: Path) -> None:
    config = tmp_path / "als.toml"
    config.write_text(
        "[data]\nseed = 42\n\n"
        "[model]\nfactors = [2, 3]\niterations = 2\n"
        "regularization = 0.05\nalpha = 10.0\ntop_k = 2\n\n"
        "[item_item]\nneighbors = 4\ncandidate_pool_size = 4\n"
        "bm25_k1 = 1.2\nbm25_b = 0.75\n\n"
        "[fusion]\nrrf_k = 60\n",
        encoding="utf-8",
    )
    artifact_root = tmp_path / "artifacts"
    artifact = train_pipeline(prepared.path, artifact_root, config)
    bundle = load_model_bundle(artifact_root)

    assert bundle.manifest.factors in {2, 3}
    assert bundle.manifest.data_version == prepared.data_version
    assert bundle.user_items.shape == (4, 6)
    assert bundle.user_ids == [1, 2, 3, 4]
    assert set(bundle.item_ids) == set(range(1, 7))
    assert bundle.model.user_factors.shape[0] == 4
    assert bundle.cosine_model is not None
    assert bundle.bm25_model is not None
    assert bundle.manifest.serving_policy in {
        "als",
        "cosine",
        "bm25",
        "rrf",
        "bm25_content",
    }
    assert bundle.manifest.selection_metric == "validation.overall.ndcg_at_2"
    metrics = json.loads((artifact / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["selection"]["selected_policy"] == bundle.manifest.serving_policy
    assert {"als", "cosine", "bm25", "rrf"} <= set(metrics["validation"])
    known_recommendations = bundle.recommend(1, limit=2, exclude_item_ids={6})
    assert len(known_recommendations) <= 2
    assert all(
        item_id not in {1, 2, 3, 4, 6} for item_id, _ in known_recommendations
    ), known_recommendations
    cold_start = bundle.recommend(
        999, limit=2, exclude_item_ids={bundle.popularity[0]}
    )
    assert cold_start
    assert all(item_id != bundle.popularity[0] for item_id, _ in cold_start)
    assert bundle.recommend(1, limit=2, exclude_item_ids={6}) == load_model_bundle(
        artifact
    ).recommend(1, limit=2, exclude_item_ids={6})
    engine = ALSRecommendationEngine(bundle)
    online = engine.recommend(
        user_id=1,
        feed_type=FeedType.PERSONALIZED,
        items=[Item(id=item_id, title=f"Item {item_id}") for item_id in bundle.item_ids],
        limit=2,
        feedback_by_bucket={},
        exposure_counts={},
    )
    expected_source = {
        "als": "als",
        "cosine": "itemcf_cosine",
        "bm25": "itemcf_bm25",
        "rrf": "rrf:als+itemcf",
        "bm25_content": "hybrid:bm25+title_tfidf",
    }[bundle.manifest.serving_policy]
    assert all(candidate.source == expected_source for candidate in online)
    assert (artifact / "badcases.csv").is_file()
    assert (artifact / "metrics.json").is_file()
    checksums = json.loads((artifact / "checksums.json").read_text(encoding="utf-8"))
    assert set(checksums) == {
        "als_model.npz",
        "cosine_model.npz",
        "bm25_model.npz",
        "serving_user_items.npz",
        "mappings.json",
        "popularity.json",
        "metrics.json",
        "badcases.csv",
        "title_tfidf_items.npz",
        "content_config.json",
    }


def test_each_serving_policy_hard_filters_seen_and_excluded(prepared, tmp_path: Path) -> None:
    config = tmp_path / "als.toml"
    config.write_text(
        "[data]\nseed = 42\n\n"
        "[model]\nfactors = [2]\niterations = 2\n"
        "regularization = 0.05\nalpha = 10.0\ntop_k = 2\n\n"
        "[item_item]\nneighbors = 4\ncandidate_pool_size = 4\n\n"
        "[fusion]\nrrf_k = 60\n",
        encoding="utf-8",
    )
    artifact = train_pipeline(prepared.path, tmp_path / "artifacts", config)
    bundle = load_model_bundle(artifact)

    for policy in ["als", "cosine", "bm25", "rrf", "bm25_content"]:
        bundle.manifest = bundle.manifest.model_copy(update={"serving_policy": policy})
        ranked = bundle.recommend(1, limit=3, exclude_item_ids={6})
        assert len(ranked) <= 3
        assert all(item_id not in {1, 2, 3, 4, 6} for item_id, _ in ranked), (
            policy,
            ranked,
        )


def test_load_legacy_manifest_defaults_to_als(prepared, tmp_path: Path) -> None:
    config = tmp_path / "als.toml"
    config.write_text(
        "[data]\nseed = 42\n\n"
        "[model]\nfactors = [2]\niterations = 2\n"
        "regularization = 0.05\nalpha = 10.0\ntop_k = 2\n",
        encoding="utf-8",
    )
    artifact = train_pipeline(prepared.path, tmp_path / "artifacts", config)
    manifest_path = artifact / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in [
        "serving_policy",
        "retrievers",
        "rrf_k",
        "selection_metric",
        "content_retriever",
    ]:
        payload.pop(field)
    payload["files"].pop("cosine_model")
    payload["files"].pop("bm25_model")
    payload["files"].pop("content_items")
    payload["files"].pop("content_config")
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    legacy = load_model_bundle(artifact)
    assert legacy.manifest.serving_policy == "als"
    assert legacy.manifest.retrievers == ["als"]
    assert legacy.cosine_model is None
    assert legacy.bm25_model is None
    assert legacy.recommend(1, limit=2)

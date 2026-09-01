from __future__ import annotations

import json
from pathlib import Path

import pytest

from recsys.contracts import MetricSet
from recsys.data import OFFICIAL_FILES, prepare_dataset
from recsys.evaluation import ranking_metrics
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


def test_train_save_and_load_bundle(prepared, tmp_path: Path) -> None:
    config = tmp_path / "als.toml"
    config.write_text(
        "[data]\nseed = 42\n\n"
        "[model]\nfactors = [2, 3]\niterations = 2\n"
        "regularization = 0.05\nalpha = 10.0\ntop_k = 2\n",
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
    known_recommendations = bundle.recommend(1, limit=2, exclude_item_ids={6})
    assert len(known_recommendations) <= 2
    assert all(
        item_id not in {1, 2, 3, 4, 6} for item_id, _ in known_recommendations
    ), known_recommendations
    assert bundle.recommend(999, limit=2, exclude_item_ids={bundle.popularity[0]})
    assert (artifact / "badcases.csv").is_file()
    assert (artifact / "metrics.json").is_file()
    checksums = json.loads((artifact / "checksums.json").read_text(encoding="utf-8"))
    assert set(checksums) == {
        "als_model.npz",
        "serving_user_items.npz",
        "mappings.json",
        "popularity.json",
        "metrics.json",
        "badcases.csv",
    }

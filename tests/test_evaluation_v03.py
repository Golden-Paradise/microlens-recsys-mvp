from recsys.evaluation import sliced_metrics


def test_sliced_metrics_separates_warm_and_pure_cold_targets() -> None:
    metrics = sliced_metrics(
        {0: [3, 1], 1: [4, 2]},
        {0: 1, 1: 4},
        warm_items={1, 2, 3},
        catalog_size=5,
        k=2,
    )

    assert metrics["overall"].recall_at_k == 1.0
    assert metrics["warm_item"].recall_at_k == 1.0
    assert metrics["pure_cold"].recall_at_k == 1.0
    assert metrics["warm_item"].ndcg_at_k < metrics["pure_cold"].ndcg_at_k


def test_empty_pure_cold_slice_is_explicit_zero() -> None:
    metrics = sliced_metrics(
        {0: [1]},
        {0: 1},
        warm_items={1},
        catalog_size=2,
        k=1,
    )

    assert metrics["pure_cold"].model_dump() == {
        "recall_at_k": 0.0,
        "ndcg_at_k": 0.0,
        "coverage_at_k": 0.0,
    }

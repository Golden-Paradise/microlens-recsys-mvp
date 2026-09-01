from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from recsys.content import (
    CONFIG_FILE,
    ITEM_VECTORS_FILE,
    fit_title_tfidf,
    hybrid_tail_quota,
    load_title_tfidf,
)


@pytest.fixture
def content_retriever():
    item_ids = [10, 20, 30, 40, 50, 60]
    titles = [
        "space hero mission",
        "space hero story",
        "cooking food story",
        "",
        "space hero story",
        "space hero story",
    ]
    fit_matrix = sparse.csr_matrix(
        np.asarray(
            [
                [1, 1, 0, 0, 0, 0],
                [0, 0, 1, 0, 0, 0],
            ],
            dtype=np.float32,
        )
    )
    return fit_title_tfidf(
        item_ids=item_ids,
        titles=titles,
        fit_matrix=fit_matrix,
        user_histories={1: [10, 20], 2: [40]},
        analyzer="word",
    )


def test_content_retriever_is_cold_only_stable_and_filters(content_retriever) -> None:
    ranked = content_retriever.recommend(1, limit=10)
    assert [item_id for item_id, _ in ranked] == [50, 60]
    assert ranked[0][1] == pytest.approx(ranked[1][1])
    assert not ({10, 20, 30} & {item_id for item_id, _ in ranked})

    assert [
        item_id
        for item_id, _ in content_retriever.recommend(
            1, limit=10, history_item_ids=[10, 50]
        )
    ] == [60]
    assert [
        item_id
        for item_id, _ in content_retriever.recommend(
            1, limit=10, exclude_item_ids={60}
        )
    ] == [50]

    assert [
        item_id
        for item_id, _ in content_retriever.recommend(
            1, limit=10, history_item_ids=[50, *([10] * 10)]
        )
    ] == [60]


def test_content_retriever_returns_empty_for_unknown_or_empty_profile(
    content_retriever,
) -> None:
    assert content_retriever.recommend(999, limit=10) == []
    assert content_retriever.recommend(2, limit=10) == []
    assert content_retriever.recommend(1, limit=0) == []


def test_content_retriever_save_load_without_pickle(
    content_retriever, tmp_path: Path
) -> None:
    content_retriever.save(tmp_path)
    loaded = load_title_tfidf(tmp_path)

    assert (tmp_path / ITEM_VECTORS_FILE).is_file()
    assert (tmp_path / CONFIG_FILE).is_file()
    assert not list(tmp_path.glob("*.pkl"))
    assert loaded.item_vectors.dtype == np.float32
    assert loaded.manifest == content_retriever.manifest
    assert loaded.recommend(1, limit=10) == content_retriever.recommend(1, limit=10)


@pytest.mark.parametrize(
    ("analyzer", "expected_range"), [("word", (1, 2)), ("char_wb", (3, 5))]
)
def test_content_retriever_freezes_required_vectorizer_contract(
    analyzer: str, expected_range: tuple[int, int]
) -> None:
    retriever = fit_title_tfidf(
        item_ids=[1, 2, 3],
        titles=["shared title one", "shared title two", "shared title three"],
        fit_matrix=sparse.csr_matrix([[1, 0, 0]], dtype=np.float32),
        user_histories={1: [1]},
        analyzer=analyzer,
    )
    assert (retriever.manifest.ngram_min, retriever.manifest.ngram_max) == expected_range
    assert retriever.manifest.min_df == 2
    assert retriever.manifest.max_features == 50_000
    assert retriever.manifest.sublinear_tf is True
    assert retriever.manifest.history_limit == 10
    assert retriever.item_vectors.dtype == np.float32
    row_norms = sparse.linalg.norm(retriever.item_vectors, axis=1)
    assert np.allclose(row_norms[row_norms > 0], 1.0)


def test_hybrid_tail_quota_is_stable_deduplicated_and_backfills() -> None:
    assert hybrid_tail_quota(
        [1, 1, 2, 3, 4, 5], [3, 6, 6, 7], k=5, cold_quota=2
    ) == [1, 2, 3, 6, 7]
    assert hybrid_tail_quota([1, 2, 3, 4, 5], [6], k=5, cold_quota=3) == [1, 2, 3, 4, 6]
    assert hybrid_tail_quota([1, 2, 3], [4, 5], k=5, cold_quota=0) == [1, 2, 3]


def test_hybrid_tail_quota_rejects_invalid_contract() -> None:
    with pytest.raises(ValueError, match="one of"):
        hybrid_tail_quota([1], [2], k=5, cold_quota=4)
    with pytest.raises(ValueError, match="exceed"):
        hybrid_tail_quota([1], [2], k=2, cold_quota=3)

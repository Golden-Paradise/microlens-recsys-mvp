from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Literal

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from recsys.contracts import ContentRetrieverManifest

Analyzer = Literal["word", "char_wb"]

ITEM_VECTORS_FILE = "title_tfidf_items.npz"
CONFIG_FILE = "content_config.json"
ALLOWED_COLD_QUOTAS = frozenset({0, 1, 2, 3, 5})
NGRAM_RANGES: dict[Analyzer, tuple[int, int]] = {
    "word": (1, 2),
    "char_wb": (3, 5),
}


@dataclass(frozen=True)
class TitleTfidfRetriever:
    manifest: ContentRetrieverManifest
    item_ids: tuple[int, ...]
    item_vectors: sparse.csr_matrix
    cold_item_ids: frozenset[int]
    user_histories: Mapping[int, tuple[int, ...]]

    def __post_init__(self) -> None:
        if self.item_vectors.shape[0] != len(self.item_ids):
            raise ValueError("item vector rows must match item_ids")
        if self.item_vectors.dtype != np.float32:
            raise ValueError("item vectors must use float32")
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("item_ids must be unique")
        if not self.cold_item_ids <= set(self.item_ids):
            raise ValueError("cold_item_ids must be present in item_ids")

    @cached_property
    def item_to_index(self) -> dict[int, int]:
        return {item_id: index for index, item_id in enumerate(self.item_ids)}

    @cached_property
    def ordered_cold_item_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self.cold_item_ids))

    @cached_property
    def cold_item_indices(self) -> tuple[int, ...]:
        return tuple(self.item_to_index[item_id] for item_id in self.ordered_cold_item_ids)

    def recommend(
        self,
        user_id: int,
        *,
        limit: int,
        exclude_item_ids: set[int] | None = None,
        history_item_ids: Sequence[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Rank only interaction-cold items against an equal-weight recent-history profile."""
        if limit <= 0:
            return []
        if history_item_ids is None:
            history_item_ids = self.user_histories.get(int(user_id))
            if history_item_ids is None:
                return []

        full_history = [int(value) for value in history_item_ids]
        recent_history = full_history[-self.manifest.history_limit :]
        item_to_index = self.item_to_index
        history_indices = [
            item_to_index[item_id] for item_id in recent_history if item_id in item_to_index
        ]
        if not history_indices or self.item_vectors.shape[1] == 0:
            return []

        profile = sparse.csr_matrix(
            self.item_vectors[history_indices].sum(axis=0), dtype=np.float32
        )
        profile *= np.float32(1.0 / len(history_indices))
        if profile.nnz == 0:
            return []
        profile = normalize(profile, norm="l2", axis=1, copy=False)

        blocked = set(full_history)
        blocked.update(exclude_item_ids or set())
        if not self.ordered_cold_item_ids:
            return []
        scores = (self.item_vectors[list(self.cold_item_indices)] @ profile.T).toarray().ravel()
        ranked = [
            (item_id, float(score))
            for item_id, score in zip(self.ordered_cold_item_ids, scores, strict=True)
            if item_id not in blocked and np.isfinite(score) and score > 0.0
        ]
        ranked.sort(key=lambda pair: (-pair[1], pair[0]))
        return ranked[: min(limit, self.manifest.candidate_pool)]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        sparse.save_npz(
            directory / ITEM_VECTORS_FILE,
            self.item_vectors.astype(np.float32, copy=False),
            compressed=True,
        )
        payload = {
            "schema_version": 1,
            "manifest": self.manifest.model_dump(mode="json"),
            "item_ids": list(self.item_ids),
            "cold_item_ids": sorted(self.cold_item_ids),
            "user_histories": {
                str(user_id): list(history)
                for user_id, history in sorted(self.user_histories.items())
            },
        }
        (directory / CONFIG_FILE).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _empty_item_vectors(item_count: int) -> sparse.csr_matrix:
    return sparse.csr_matrix((item_count, 0), dtype=np.float32)


def _fit_item_vectors(
    titles: Sequence[str], manifest: ContentRetrieverManifest
) -> sparse.csr_matrix:
    if not any(title.strip() for title in titles):
        return _empty_item_vectors(len(titles))
    vectorizer = TfidfVectorizer(
        analyzer=manifest.analyzer,
        ngram_range=(manifest.ngram_min, manifest.ngram_max),
        min_df=manifest.min_df,
        max_features=manifest.max_features,
        sublinear_tf=manifest.sublinear_tf,
        norm="l2",
        dtype=np.float32,
    )
    try:
        vectors = vectorizer.fit_transform(titles)
    except ValueError as exc:
        empty_vocabulary_messages = (
            "empty vocabulary",
            "no terms remain",
            "max_df corresponds to < documents than min_df",
        )
        if not any(message in str(exc) for message in empty_vocabulary_messages):
            raise
        return _empty_item_vectors(len(titles))
    return vectors.tocsr().astype(np.float32, copy=False)


def fit_title_tfidf(
    *,
    item_ids: Sequence[int],
    titles: Sequence[str | None],
    fit_matrix: sparse.spmatrix,
    user_histories: Mapping[int, Sequence[int]],
    analyzer: Analyzer,
    candidate_pool: int = 100,
    cold_quota: int = 0,
) -> TitleTfidfRetriever:
    """Fit static title vectors and freeze the cold set from the supplied interaction matrix."""
    if analyzer not in NGRAM_RANGES:
        raise ValueError(f"unsupported analyzer: {analyzer}")
    normalized_item_ids = tuple(int(value) for value in item_ids)
    if len(set(normalized_item_ids)) != len(normalized_item_ids):
        raise ValueError("item_ids must be unique")
    if len(titles) != len(normalized_item_ids):
        raise ValueError("titles must align with item_ids")
    if fit_matrix.shape[1] != len(normalized_item_ids):
        raise ValueError("fit_matrix columns must align with item_ids")
    if cold_quota not in ALLOWED_COLD_QUOTAS:
        raise ValueError(f"cold_quota must be one of {sorted(ALLOWED_COLD_QUOTAS)}")

    ngram_min, ngram_max = NGRAM_RANGES[analyzer]
    manifest = ContentRetrieverManifest(
        analyzer=analyzer,
        ngram_min=ngram_min,
        ngram_max=ngram_max,
        min_df=2,
        max_features=50_000,
        sublinear_tf=True,
        history_limit=10,
        candidate_pool=candidate_pool,
        cold_quota=cold_quota,
    )
    normalized_titles = ["" if title is None else str(title).strip() for title in titles]
    item_vectors = _fit_item_vectors(normalized_titles, manifest)
    interaction_counts = np.asarray(fit_matrix.sum(axis=0)).ravel()
    cold_item_ids = frozenset(
        item_id
        for item_id, count in zip(normalized_item_ids, interaction_counts, strict=True)
        if count == 0
    )
    normalized_histories = {
        int(user_id): tuple(int(value) for value in history)
        for user_id, history in user_histories.items()
    }
    return TitleTfidfRetriever(
        manifest=manifest,
        item_ids=normalized_item_ids,
        item_vectors=item_vectors,
        cold_item_ids=cold_item_ids,
        user_histories=normalized_histories,
    )


def load_title_tfidf(directory: Path) -> TitleTfidfRetriever:
    payload = json.loads((directory / CONFIG_FILE).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported content artifact schema")
    item_vectors = sparse.load_npz(directory / ITEM_VECTORS_FILE).tocsr()
    item_vectors = item_vectors.astype(np.float32, copy=False)
    return TitleTfidfRetriever(
        manifest=ContentRetrieverManifest.model_validate(payload["manifest"]),
        item_ids=tuple(int(value) for value in payload["item_ids"]),
        item_vectors=item_vectors,
        cold_item_ids=frozenset(int(value) for value in payload["cold_item_ids"]),
        user_histories={
            int(user_id): tuple(int(value) for value in history)
            for user_id, history in payload["user_histories"].items()
        },
    )


def hybrid_tail_quota(
    warm_ranking: Iterable[int],
    cold_ranking: Iterable[int],
    *,
    k: int,
    cold_quota: int,
) -> list[int]:
    """Reserve a stable Top-K tail for cold candidates without returning duplicates."""
    if k <= 0:
        raise ValueError("k must be positive")
    if cold_quota not in ALLOWED_COLD_QUOTAS:
        raise ValueError(f"cold_quota must be one of {sorted(ALLOWED_COLD_QUOTAS)}")
    if cold_quota > k:
        raise ValueError("cold_quota cannot exceed k")

    warm = list(dict.fromkeys(int(item_id) for item_id in warm_ranking))
    warm_items = set(warm)
    cold = list(
        dict.fromkeys(
            int(item_id) for item_id in cold_ranking if int(item_id) not in warm_items
        )
    )
    selected_cold = cold[:cold_quota]
    warm_slots = k - len(selected_cold)
    return warm[:warm_slots] + selected_cold

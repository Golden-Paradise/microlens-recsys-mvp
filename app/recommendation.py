from dataclasses import dataclass
from typing import Protocol

from app.constants import FeedType
from app.models import Item
from recsys.model import ModelBundle


@dataclass(frozen=True)
class Candidate:
    item_id: int
    score: float
    source: str
    reason: str


class RecommendationEngine(Protocol):
    model_version: str

    def recommend(
        self,
        *,
        user_id: int,
        feed_type: FeedType,
        items: list[Item],
        limit: int,
        feedback_by_bucket: dict[int, float],
        exposure_counts: dict[int, int],
    ) -> list[Candidate]: ...


class DeterministicRecommendationEngine:
    """Small, replaceable engine used until an offline ALS artifact is available."""

    model_version = "deterministic-v1"

    def recommend(
        self,
        *,
        user_id: int,
        feed_type: FeedType,
        items: list[Item],
        limit: int,
        feedback_by_bucket: dict[int, float],
        exposure_counts: dict[int, int],
    ) -> list[Candidate]:
        if feed_type == FeedType.POPULAR:
            ranked = sorted(items, key=lambda item: (-self._popularity(item), item.id))
            return [
                Candidate(item.id, self._popularity(item), "popular", "近期热门内容")
                for item in ranked[:limit]
            ]

        if feed_type == FeedType.EXPLORE:
            ranked = sorted(
                items,
                key=lambda item: (
                    exposure_counts.get(item.id, 0),
                    self._stable_key(user_id, item.id),
                    item.id,
                ),
            )
            return [
                Candidate(
                    item.id,
                    1.0 / (1 + exposure_counts.get(item.id, 0)),
                    "explore",
                    "低曝光探索内容",
                )
                for item in ranked[:limit]
            ]

        ranked_with_score = []
        for item in items:
            affinity = feedback_by_bucket.get(item.id % 5, 0.0)
            personal = (10_000 - self._stable_key(user_id, item.id)) / 10_000
            popularity_signal = min(item.train_interactions / 40, 1.0)
            score = personal + 0.15 * popularity_signal + affinity
            ranked_with_score.append((score, item))
        ranked_with_score.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [
            Candidate(item.id, score, "personalized", "基于用户画像与历史热度")
            for score, item in ranked_with_score[:limit]
        ]

    @staticmethod
    def _stable_key(user_id: int, item_id: int) -> int:
        return ((user_id * 2_654_435_761) ^ (item_id * 2_246_822_519)) % 10_000

    @staticmethod
    def _popularity(item: Item) -> float:
        return float(item.train_interactions * 10_000 + item.likes * 10 + item.views)


class ALSRecommendationEngine:
    """Serve a validation-selected artifact while keeping non-personalized feeds simple."""

    _POLICY_PRESENTATION = {
        "als": ("als", "ALS 协同过滤与实时行为重排"),
        "cosine": ("itemcf_cosine", "Item-Item Cosine 共现召回与实时行为重排"),
        "bm25": ("itemcf_bm25", "Item-Item BM25 共现召回与实时行为重排"),
        "rrf": ("rrf:als+itemcf", "ALS 与 ItemCF 的 RRF 融合及实时行为重排"),
        "bm25_content": (
            "hybrid:bm25+title_tfidf",
            "BM25 协同头部与标题 TF-IDF 纯冷内容配额",
        ),
    }

    def __init__(self, bundle: ModelBundle) -> None:
        self.bundle = bundle
        self.model_version = bundle.manifest.model_version
        self._deterministic = DeterministicRecommendationEngine()

    def recommend(
        self,
        *,
        user_id: int,
        feed_type: FeedType,
        items: list[Item],
        limit: int,
        feedback_by_bucket: dict[int, float],
        exposure_counts: dict[int, int],
    ) -> list[Candidate]:
        if feed_type != FeedType.PERSONALIZED:
            return self._deterministic.recommend(
                user_id=user_id,
                feed_type=feed_type,
                items=items,
                limit=limit,
                feedback_by_bucket=feedback_by_bucket,
                exposure_counts=exposure_counts,
            )

        item_by_id = {item.id: item for item in items}
        unavailable = set(self.bundle.item_ids) - set(item_by_id)
        ranked = self.bundle.recommend(
            user_id,
            limit=max(limit * 5, 100),
            exclude_item_ids=unavailable,
        )
        policy = self.bundle.manifest.serving_policy
        source, reason = self._POLICY_PRESENTATION.get(
            policy, (policy, "验证集选定的协同召回与实时行为重排")
        )
        raw_scores = [score for item_id, score in ranked if item_id in item_by_id]
        score_span = max(raw_scores) - min(raw_scores) if raw_scores else 0.0
        feedback_cap = score_span * 0.1
        candidates = [
            Candidate(
                item_id=item_id,
                score=score
                + feedback_cap
                * min(max(feedback_by_bucket.get(item_id % 5, 0.0), 0.0), 2.0)
                / 2.0,
                source=source,
                reason=reason,
            )
            for item_id, score in ranked
            if item_id in item_by_id
        ]
        candidates.sort(key=lambda candidate: (-candidate.score, candidate.item_id))
        return candidates[:limit]

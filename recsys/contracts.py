from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DataSummary(BaseModel):
    users: int
    items: int
    interactions: int
    min_timestamp: datetime
    max_timestamp: datetime
    train_interactions: int
    validation_interactions: int
    test_interactions: int
    duplicate_rows: int
    missing_titles: int
    missing_stats: int


class MetricSet(BaseModel):
    recall_at_k: float = Field(ge=0, le=1)
    ndcg_at_k: float = Field(ge=0, le=1)
    coverage_at_k: float = Field(ge=0, le=1)


class ContentRetrieverManifest(BaseModel):
    analyzer: Literal["word", "char_wb"]
    ngram_min: int = Field(ge=1)
    ngram_max: int = Field(ge=1)
    min_df: int = Field(default=2, ge=1)
    max_features: int = Field(default=50_000, ge=1)
    sublinear_tf: bool = True
    history_limit: int = Field(default=10, ge=1)
    candidate_pool: int = Field(default=100, ge=1)
    cold_quota: int = Field(default=0, ge=0)


class ModelManifest(BaseModel):
    model_version: str
    data_version: str
    created_at: datetime
    algorithm: str
    factors: int
    iterations: int
    regularization: float
    alpha: float
    top_k: int
    files: dict[str, str]
    metrics: dict[str, MetricSet]
    serving_policy: str = "als"
    retrievers: list[str] = Field(default_factory=lambda: ["als"])
    rrf_k: int = Field(default=60, gt=0)
    selection_metric: str = "validation.overall.ndcg_at_k"
    content_retriever: ContentRetrieverManifest | None = None


class ArtifactReference(BaseModel):
    model_version: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=240)


class ArtifactPointer(BaseModel):
    schema_version: Literal[2] = 2
    current: ArtifactReference
    previous: ArtifactReference | None = None
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_pointer(cls, value: object) -> object:
        if not isinstance(value, dict) or "current" in value:
            return value
        if "model_version" not in value or "path" not in value:
            return value
        return {
            "schema_version": 2,
            "current": {
                "model_version": value["model_version"],
                "path": value["path"],
            },
            "previous": None,
            "updated_at": value.get("updated_at"),
        }

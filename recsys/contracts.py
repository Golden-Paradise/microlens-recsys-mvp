from datetime import datetime

from pydantic import BaseModel, Field


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

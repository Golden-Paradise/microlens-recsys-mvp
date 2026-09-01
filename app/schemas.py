from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.constants import DashboardWindow, EventType, FeedType, OperationScope


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str


class FeedItemResponse(BaseModel):
    item_id: int
    title: str
    position: int
    source: str
    score: float
    reason: str
    likes: int
    views: int


class FeedResponse(BaseModel):
    request_id: str
    feed_type: FeedType
    model_version: str
    page: int
    page_size: int
    has_more: bool
    fallback_reason: str | None = None
    items: list[FeedItemResponse]


class EventCreate(BaseModel):
    event_id: str = Field(min_length=36, max_length=36)
    request_id: str = Field(min_length=36, max_length=36)
    item_id: int
    event_type: EventType
    client_timestamp: datetime | None = None


class EventResponse(BaseModel):
    event_id: str
    status: str
    profile_version: int


class OperationCreate(BaseModel):
    item_id: int
    scope: OperationScope = OperationScope.ALL
    scope_value: str | None = None
    feed_type: FeedType | None = None
    reason: str = Field(min_length=3, max_length=300)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class DashboardOverview(BaseModel):
    window: DashboardWindow
    window_start: datetime | None
    window_end: datetime
    users: int
    active_users: int
    requests: int
    exposures: int
    clicks: int
    ctr: float
    likes: int
    offline_items: int
    current_model_version: str
    feed_shares: dict[str, float]
    hot_items: list[dict[str, object]]


class DashboardTrendPoint(BaseModel):
    bucket_start: datetime
    requests: int
    exposures: int
    clicks: int
    likes: int
    ctr: float


class DashboardTrends(BaseModel):
    window: DashboardWindow
    window_start: datetime | None
    window_end: datetime
    bucket_minutes: int
    points: list[DashboardTrendPoint]


class RuntimeModelReference(BaseModel):
    model_version: str
    path: str
    serving_policy: str | None = None


class RuntimeValidation(BaseModel):
    status: Literal["ok", "legacy_unverified", "error"]
    checked_at: datetime
    errors: list[str] = Field(default_factory=list)


class ModelRuntimeResponse(BaseModel):
    status: Literal["ready", "recovered", "fallback"]
    current: RuntimeModelReference | None
    previous: RuntimeModelReference | None
    loaded_at: datetime
    validation: RuntimeValidation


class EvaluationMetricSet(BaseModel):
    recall_at_20: float = Field(ge=0, le=1)
    ndcg_at_20: float = Field(ge=0, le=1)
    coverage_at_20: float = Field(ge=0, le=1)


class EvaluationSlices(BaseModel):
    overall: EvaluationMetricSet
    warm: EvaluationMetricSet
    pure_cold: EvaluationMetricSet


class PolicyEvaluation(BaseModel):
    policy: str
    selected: bool
    validation: EvaluationSlices
    test: EvaluationSlices | None = None


class ModelEvaluationResponse(BaseModel):
    model_version: str
    selected_policy: str
    selection_metric: str
    policies: list[PolicyEvaluation]


class RequestTraceSummary(BaseModel):
    request_id: str
    username: str
    feed_type: FeedType
    model_version: str
    created_at: datetime
    feed_build_latency_ms: float = Field(ge=0)
    fallback_reason: str | None = None
    exposures: int = Field(ge=0)
    clicks: int = Field(ge=0)
    likes: int = Field(ge=0)
    not_interested: int = Field(ge=0)


class RequestTracesResponse(BaseModel):
    window: DashboardWindow
    window_start: datetime | None
    window_end: datetime
    items: list[RequestTraceSummary]


class LatencySummary(BaseModel):
    p50: float = Field(ge=0)
    p95: float = Field(ge=0)
    max: float = Field(ge=0)


class ObservabilityGroup(BaseModel):
    key: str
    requests: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    fallback_rate: float = Field(ge=0, le=1)
    latency_ms: LatencySummary


class ObservabilityAlert(BaseModel):
    code: Literal["fallback_rate", "p95_latency"]
    severity: Literal["warning"] = "warning"
    message: str


class ObservabilityResponse(BaseModel):
    window: DashboardWindow
    window_start: datetime | None
    window_end: datetime
    requests: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    fallback_rate: float = Field(ge=0, le=1)
    latency_ms: LatencySummary
    by_feed: list[ObservabilityGroup]
    by_model: list[ObservabilityGroup]
    alerts: list[ObservabilityAlert]

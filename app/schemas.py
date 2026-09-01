from datetime import datetime

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

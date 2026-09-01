from datetime import UTC, datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.constants import (
    EventType,
    FeedType,
    ItemStatus,
    ModelStatus,
    OperationScope,
    OperationType,
    UserRole,
)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=64)
    password_hash: str
    role: UserRole = Field(default=UserRole.USER, index=True)
    source_user_id: int | None = Field(default=None, index=True)
    profile_version: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)


class Item(SQLModel, table=True):
    __tablename__ = "items"

    id: int = Field(primary_key=True)
    title: str
    likes: int = Field(default=0)
    views: int = Field(default=0)
    train_interactions: int = Field(default=0, index=True)
    status: ItemStatus = Field(default=ItemStatus.ONLINE, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class RecommendationRequest(SQLModel, table=True):
    __tablename__ = "recommendation_requests"

    id: str = Field(primary_key=True, max_length=36)
    user_id: int = Field(foreign_key="users.id", index=True)
    feed_type: FeedType = Field(index=True)
    model_version: str
    page: int = Field(default=1)
    page_size: int = Field(default=12)
    fallback_reason: str | None = None
    latency_ms: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class Exposure(SQLModel, table=True):
    __tablename__ = "exposures"
    __table_args__ = (
        UniqueConstraint("request_id", "item_id", name="uq_exposure_request_item"),
        Index("ix_exposures_user_created", "user_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    request_id: str = Field(foreign_key="recommendation_requests.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    item_id: int = Field(foreign_key="items.id", index=True)
    position: int
    source: str = Field(index=True)
    score: float
    reason: str
    created_at: datetime = Field(default_factory=utc_now, index=True)


class Event(SQLModel, table=True):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_created", "user_id", "created_at"),)

    id: int | None = Field(default=None, primary_key=True)
    event_id: str = Field(index=True, unique=True, max_length=36)
    request_id: str = Field(foreign_key="recommendation_requests.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    item_id: int = Field(foreign_key="items.id", index=True)
    position: int
    event_type: EventType = Field(index=True)
    source: str
    client_timestamp: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)


class Operation(SQLModel, table=True):
    __tablename__ = "operations"

    id: int | None = Field(default=None, primary_key=True)
    admin_user_id: int = Field(foreign_key="users.id", index=True)
    item_id: int = Field(foreign_key="items.id", index=True)
    operation_type: OperationType = Field(index=True)
    scope: OperationScope = Field(default=OperationScope.ALL)
    scope_value: str | None = None
    feed_type: FeedType | None = None
    reason: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    active: bool = Field(default=True, index=True)
    before_state: str | None = None
    after_state: str | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ModelVersion(SQLModel, table=True):
    __tablename__ = "model_versions"

    id: str = Field(primary_key=True, max_length=80)
    status: ModelStatus = Field(default=ModelStatus.CANDIDATE, index=True)
    data_version: str
    artifact_path: str
    metrics_json: str
    trained_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None


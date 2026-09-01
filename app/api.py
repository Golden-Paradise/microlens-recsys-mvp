from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import or_
from sqlmodel import select

from app.auth import CurrentAdmin, CurrentUser, SessionDep
from app.constants import DashboardWindow, FeedType, ItemStatus, OperationType
from app.models import Event, Item, Operation, User
from app.schemas import (
    DashboardOverview,
    DashboardTrends,
    EventCreate,
    EventResponse,
    FeedResponse,
    LoginRequest,
    OperationCreate,
    UserResponse,
)
from app.security import verify_password
from app.services import DashboardService, EventService, FeedService, OperationService

router = APIRouter(prefix="/api")


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, username=user.username, role=user.role.value)


@router.post("/auth/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, session: SessionDep) -> UserResponse:
    user = session.exec(select(User).where(User.username == payload.username)).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session.clear()
    request.session["user_id"] = user.id
    return _user_response(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return _user_response(user)


@router.get("/feeds/{feed_type}", response_model=FeedResponse)
def feed(
    feed_type: FeedType,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 12,
) -> FeedResponse:
    service = FeedService(request.app.state.recommendation_engine)
    return service.create_feed(
        session, user=user, feed_type=feed_type, page=page, page_size=page_size
    )


@router.post("/events", response_model=EventResponse)
def create_event(
    payload: EventCreate, user: CurrentUser, session: SessionDep
) -> EventResponse:
    return EventService.create_event(session, user=user, payload=payload)


@router.get("/profile/me")
def profile(user: CurrentUser, session: SessionDep) -> dict[str, object]:
    counts: dict[str, int] = {}
    rows = session.exec(select(Event).where(Event.user_id == user.id)).all()
    for event in rows:
        counts[event.event_type.value] = counts.get(event.event_type.value, 0) + 1
    return {
        "id": user.id,
        "username": user.username,
        "profile_version": user.profile_version,
        "event_counts": counts,
    }


@router.get("/items/{item_id}")
def get_item(item_id: int, user: CurrentUser, session: SessionDep) -> Item:
    item = session.get(Item, item_id)
    if item is None or item.status == ItemStatus.OFFLINE:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/admin/dashboard", response_model=DashboardOverview)
def dashboard(
    request: Request,
    admin: CurrentAdmin,
    session: SessionDep,
    window: DashboardWindow = DashboardWindow.HOUR_24,
) -> DashboardOverview:
    return DashboardService.overview(
        session,
        request.app.state.recommendation_engine.model_version,
        window,
    )


@router.get("/admin/dashboard/trends", response_model=DashboardTrends)
def dashboard_trends(
    admin: CurrentAdmin,
    session: SessionDep,
    window: DashboardWindow = DashboardWindow.HOUR_24,
) -> DashboardTrends:
    return DashboardService.trends(session, window)


@router.get("/admin/feeds/diagnostics")
def feed_diagnostics(
    admin: CurrentAdmin,
    session: SessionDep,
    window: DashboardWindow = DashboardWindow.HOUR_24,
) -> list[dict[str, object]]:
    return DashboardService.feed_diagnostics(session, window)


@router.get("/admin/users/{user_id}/debug")
def user_debug(user_id: int, admin: CurrentAdmin, session: SessionDep) -> dict[str, object]:
    return DashboardService.user_debug(session, user_id)


@router.get("/admin/requests/{request_id}")
def request_trace(
    request_id: str, admin: CurrentAdmin, session: SessionDep
) -> dict[str, object]:
    return DashboardService.request_trace(session, request_id)


@router.get("/admin/models")
def model_versions(admin: CurrentAdmin, session: SessionDep) -> list[object]:
    return DashboardService.models(session)


@router.get("/admin/contents")
def contents(
    admin: CurrentAdmin,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    item_status: Annotated[ItemStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, object]]:
    statement = select(Item)
    if q:
        search_conditions = [Item.title.contains(q)]
        if q.isdigit():
            search_conditions.append(Item.id == int(q))
        statement = statement.where(or_(*search_conditions))
    if item_status:
        statement = statement.where(Item.status == item_status)
    items = list(session.exec(statement.order_by(Item.id).limit(limit)).all())
    active_forced_ids = set(
        session.exec(
            select(Operation.item_id).where(
                Operation.operation_type == OperationType.FORCE,
                Operation.active.is_(True),
            )
        ).all()
    )
    return [
        {
            "id": item.id,
            "title": item.title,
            "status": item.status,
            "likes": item.likes,
            "views": item.views,
            "train_interactions": item.train_interactions,
            "is_forced": item.id in active_forced_ids,
        }
        for item in items
    ]


@router.post("/admin/operations/{operation_type}")
def operate(
    operation_type: OperationType,
    payload: OperationCreate,
    admin: CurrentAdmin,
    session: SessionDep,
) -> dict[str, object]:
    return OperationService.apply(
        session, admin=admin, operation_type=operation_type, payload=payload
    )


@router.get("/admin/operations")
def operation_audit(
    admin: CurrentAdmin,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Operation]:
    return list(
        session.exec(select(Operation).order_by(Operation.created_at.desc()).limit(limit)).all()
    )

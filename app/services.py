import json
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.constants import (
    DashboardWindow,
    EventType,
    FeedType,
    ItemStatus,
    ModelStatus,
    OperationScope,
    OperationType,
)
from app.models import (
    Event,
    Exposure,
    Item,
    ModelVersion,
    Operation,
    RecommendationRequest,
    User,
    utc_now,
)
from app.observability import RequestObservation, aggregate_observability
from app.recommendation import (
    Candidate,
    DeterministicRecommendationEngine,
    RecommendationEngine,
)
from app.schemas import (
    DashboardOverview,
    DashboardTrendPoint,
    DashboardTrends,
    EvaluationMetricSet,
    EvaluationSlices,
    EventCreate,
    EventResponse,
    FeedItemResponse,
    FeedResponse,
    ModelEvaluationResponse,
    ModelRuntimeResponse,
    ObservabilityResponse,
    OperationCreate,
    PolicyEvaluation,
    RequestTracesResponse,
    RequestTraceSummary,
)


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _evaluation_metrics(payload: dict[str, object] | None) -> EvaluationMetricSet:
    values = payload or {}
    return EvaluationMetricSet(
        recall_at_20=float(values.get("recall_at_k", 0.0)),
        ndcg_at_20=float(values.get("ndcg_at_k", 0.0)),
        coverage_at_20=float(values.get("coverage_at_k", 0.0)),
    )


def _evaluation_slices(payload: dict[str, object]) -> EvaluationSlices:
    return EvaluationSlices(
        overall=_evaluation_metrics(payload.get("overall")),
        warm=_evaluation_metrics(payload.get("warm_item") or payload.get("warm")),
        pure_cold=_evaluation_metrics(payload.get("pure_cold")),
    )


class FeedService:
    def __init__(
        self,
        engine: RecommendationEngine,
        fallback_engine: RecommendationEngine | None = None,
    ) -> None:
        self.engine = engine
        self.fallback_engine = fallback_engine or DeterministicRecommendationEngine()

    def create_feed(
        self,
        session: Session,
        *,
        user: User,
        feed_type: FeedType,
        page: int,
        page_size: int,
    ) -> FeedResponse:
        started = time.perf_counter()
        online_items = list(
            session.exec(select(Item).where(Item.status == ItemStatus.ONLINE)).all()
        )
        item_by_id = {item.id: item for item in online_items}
        excluded = self._excluded_item_ids(session, user.id)
        available = [item for item in online_items if item.id not in excluded]
        feedback = self._feedback_by_bucket(session, user.id)
        exposure_counts = self._exposure_counts(session)
        fallback_reason: str | None = None
        model_version = self.engine.model_version

        try:
            candidates = self.engine.recommend(
                user_id=user.source_user_id if user.source_user_id is not None else user.id,
                feed_type=feed_type,
                items=available,
                limit=page_size + 8,
                feedback_by_bucket=feedback,
                exposure_counts=exposure_counts,
            )
            if not candidates and available:
                raise LookupError("empty candidate result")
        except Exception as exc:  # The online path must stay available if a model fails.
            fallback_reason = f"{type(exc).__name__}: {exc}"
            model_version = self.fallback_engine.model_version
            candidates = self.fallback_engine.recommend(
                user_id=user.id,
                feed_type=FeedType.POPULAR,
                items=available,
                limit=page_size + 8,
                feedback_by_bucket=feedback,
                exposure_counts=exposure_counts,
            )

        if page == 1:
            candidates = self._inject_forced_candidates(
                session,
                user=user,
                feed_type=feed_type,
                candidates=candidates,
                item_by_id=item_by_id,
                excluded_by_feedback=self._not_interested_item_ids(session, user.id),
            )
        candidates = self._deduplicate_online(candidates, item_by_id)
        selected = candidates[:page_size]
        has_more = len(candidates) > page_size or len(available) > len(selected)

        request_id = str(uuid4())
        request_row = RecommendationRequest(
            id=request_id,
            user_id=user.id,
            feed_type=feed_type,
            model_version=model_version,
            page=page,
            page_size=page_size,
            fallback_reason=fallback_reason,
            latency_ms=(time.perf_counter() - started) * 1_000,
        )
        session.add(request_row)
        # SQLAlchemy has no ORM relationship here to infer flush order from, so persist
        # the parent trace before its exposure and impression children.
        session.flush()

        response_items: list[FeedItemResponse] = []
        for position, candidate in enumerate(selected, start=1):
            item = item_by_id[candidate.item_id]
            exposure = Exposure(
                request_id=request_id,
                user_id=user.id,
                item_id=item.id,
                position=position,
                source=candidate.source,
                score=candidate.score,
                reason=candidate.reason,
            )
            session.add(exposure)
            session.add(
                Event(
                    event_id=str(uuid4()),
                    request_id=request_id,
                    user_id=user.id,
                    item_id=item.id,
                    position=position,
                    event_type=EventType.IMPRESSION,
                    source=candidate.source,
                )
            )
            response_items.append(
                FeedItemResponse(
                    item_id=item.id,
                    title=item.title,
                    position=position,
                    source=candidate.source,
                    score=candidate.score,
                    reason=candidate.reason,
                    likes=item.likes,
                    views=item.views,
                )
            )

        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not persist recommendation trace",
            ) from exc

        return FeedResponse(
            request_id=request_id,
            feed_type=feed_type,
            model_version=model_version,
            page=page,
            page_size=page_size,
            has_more=has_more,
            fallback_reason=fallback_reason,
            items=response_items,
        )

    @staticmethod
    def _excluded_item_ids(session: Session, user_id: int | None) -> set[int]:
        exposed = set(
            session.exec(select(Exposure.item_id).where(Exposure.user_id == user_id)).all()
        )
        return exposed | FeedService._not_interested_item_ids(session, user_id)

    @staticmethod
    def _not_interested_item_ids(session: Session, user_id: int | None) -> set[int]:
        return set(
            session.exec(
                select(Event.item_id).where(
                    Event.user_id == user_id,
                    Event.event_type == EventType.NOT_INTERESTED,
                )
            ).all()
        )

    @staticmethod
    def _feedback_by_bucket(session: Session, user_id: int | None) -> dict[int, float]:
        rows = session.exec(
            select(Event.item_id, Event.event_type).where(
                Event.user_id == user_id,
                Event.event_type.in_([EventType.CLICK, EventType.LIKE]),
            )
        ).all()
        result: defaultdict[int, float] = defaultdict(float)
        for item_id, event_type in rows:
            result[item_id % 5] += 0.5 if event_type == EventType.CLICK else 1.5
        return dict(result)

    @staticmethod
    def _exposure_counts(session: Session) -> dict[int, int]:
        rows = session.exec(
            select(Exposure.item_id, func.count(Exposure.id)).group_by(Exposure.item_id)
        ).all()
        return {item_id: count for item_id, count in rows}

    @staticmethod
    def _deduplicate_online(
        candidates: list[Candidate], item_by_id: dict[int, Item]
    ) -> list[Candidate]:
        seen: set[int] = set()
        result: list[Candidate] = []
        for candidate in candidates:
            if candidate.item_id in seen or candidate.item_id not in item_by_id:
                continue
            if item_by_id[candidate.item_id].status != ItemStatus.ONLINE:
                continue
            seen.add(candidate.item_id)
            result.append(candidate)
        return result

    @staticmethod
    def _inject_forced_candidates(
        session: Session,
        *,
        user: User,
        feed_type: FeedType,
        candidates: list[Candidate],
        item_by_id: dict[int, Item],
        excluded_by_feedback: set[int],
    ) -> list[Candidate]:
        now = utc_now()
        operations = list(
            session.exec(
                select(Operation)
                .where(
                    Operation.operation_type == OperationType.FORCE,
                    Operation.active.is_(True),
                )
                .order_by(Operation.created_at.desc())
            ).all()
        )
        forced: list[Candidate] = []
        for operation in operations:
            if operation.starts_at and operation.starts_at > now:
                continue
            if operation.ends_at and operation.ends_at <= now:
                continue
            if operation.item_id not in item_by_id or operation.item_id in excluded_by_feedback:
                continue
            if operation.feed_type is not None and operation.feed_type != feed_type:
                continue
            if operation.scope == OperationScope.USER and operation.scope_value not in {
                str(user.id),
                user.username,
            }:
                continue
            if operation.scope == OperationScope.FEED and operation.feed_type != feed_type:
                continue
            forced.append(
                Candidate(
                    item_id=operation.item_id,
                    score=float("inf"),
                    source="forced",
                    reason=f"运营强推：{operation.reason}",
                )
            )
        return forced + candidates


class EventService:
    @staticmethod
    def create_event(
        session: Session, *, user: User, payload: EventCreate
    ) -> EventResponse:
        existing = session.exec(select(Event).where(Event.event_id == payload.event_id)).first()
        if existing is not None:
            if (
                existing.user_id != user.id
                or existing.request_id != payload.request_id
                or existing.item_id != payload.item_id
                or existing.event_type != payload.event_type
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="event_id is already used by another payload",
                )
            return EventResponse(
                event_id=payload.event_id,
                status="duplicate",
                profile_version=user.profile_version,
            )
        if payload.event_type == EventType.IMPRESSION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impressions are recorded by the feed service",
            )

        exposure = session.exec(
            select(Exposure).where(
                Exposure.request_id == payload.request_id,
                Exposure.item_id == payload.item_id,
                Exposure.user_id == user.id,
            )
        ).first()
        if exposure is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No owned exposure matches this request and item",
            )

        session.add(
            Event(
                event_id=payload.event_id,
                request_id=payload.request_id,
                user_id=user.id,
                item_id=payload.item_id,
                position=exposure.position,
                event_type=payload.event_type,
                source=exposure.source,
                client_timestamp=_naive_utc(payload.client_timestamp),
            )
        )
        user.profile_version += 1
        session.add(user)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="Duplicate event") from exc
        session.refresh(user)
        return EventResponse(
            event_id=payload.event_id,
            status="created",
            profile_version=user.profile_version,
        )


class OperationService:
    @staticmethod
    def apply(
        session: Session,
        *,
        admin: User,
        operation_type: OperationType,
        payload: OperationCreate,
    ) -> dict[str, object]:
        item = session.get(Item, payload.item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        starts_at = _naive_utc(payload.starts_at)
        ends_at = _naive_utc(payload.ends_at)
        if starts_at and ends_at and starts_at >= ends_at:
            raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
        if operation_type == OperationType.FORCE:
            if item.status == ItemStatus.OFFLINE:
                raise HTTPException(status_code=409, detail="Offline item cannot be forced")
            if payload.scope == OperationScope.USER and not payload.scope_value:
                raise HTTPException(status_code=422, detail="USER scope requires scope_value")
            if payload.scope == OperationScope.FEED and payload.feed_type is None:
                raise HTTPException(status_code=422, detail="FEED scope requires feed_type")

        before = {"status": item.status.value}
        if operation_type == OperationType.OFFLINE:
            item.status = ItemStatus.OFFLINE
            item.updated_at = utc_now()
            session.add(item)
        elif operation_type == OperationType.RESTORE:
            item.status = ItemStatus.ONLINE
            item.updated_at = utc_now()
            session.add(item)

        operation = Operation(
            admin_user_id=admin.id,
            item_id=item.id,
            operation_type=operation_type,
            scope=payload.scope,
            scope_value=payload.scope_value,
            feed_type=payload.feed_type,
            reason=payload.reason,
            starts_at=starts_at,
            ends_at=ends_at,
            before_state=json.dumps(before, ensure_ascii=False),
            after_state=json.dumps({"status": item.status.value}, ensure_ascii=False),
        )
        session.add(operation)
        session.commit()
        session.refresh(operation)
        return {
            "operation_id": operation.id,
            "operation_type": operation.operation_type,
            "item_id": operation.item_id,
            "item_status": item.status,
            "active": operation.active,
        }


class DashboardService:
    _WINDOW_DURATION = {
        DashboardWindow.HOUR_1: timedelta(hours=1),
        DashboardWindow.HOUR_6: timedelta(hours=6),
        DashboardWindow.HOUR_24: timedelta(hours=24),
        DashboardWindow.ALL: None,
    }
    _BUCKET_MINUTES = {
        DashboardWindow.HOUR_1: 5,
        DashboardWindow.HOUR_6: 30,
        DashboardWindow.HOUR_24: 60,
        DashboardWindow.ALL: 1_440,
    }

    @staticmethod
    def _window_bounds(
        window: DashboardWindow, *, window_end: datetime | None = None
    ) -> tuple[datetime | None, datetime]:
        end = window_end or utc_now()
        duration = DashboardService._WINDOW_DURATION[window]
        return (end - duration if duration is not None else None), end

    @staticmethod
    def _time_conditions(
        column: object, window_start: datetime | None, window_end: datetime
    ) -> list[object]:
        conditions = [column < window_end]
        if window_start is not None:
            conditions.append(column >= window_start)
        return conditions

    @staticmethod
    def overview(
        session: Session,
        current_model_version: str,
        window: DashboardWindow = DashboardWindow.HOUR_24,
    ) -> DashboardOverview:
        window_start, window_end = DashboardService._window_bounds(window)
        request_conditions = DashboardService._time_conditions(
            RecommendationRequest.created_at, window_start, window_end
        )
        exposure_conditions = DashboardService._time_conditions(
            Exposure.created_at, window_start, window_end
        )
        event_conditions = DashboardService._time_conditions(
            Event.created_at, window_start, window_end
        )

        users = session.exec(select(func.count(User.id)).where(User.role == "user")).one()
        active_users = session.exec(
            select(func.count(func.distinct(RecommendationRequest.user_id)))
            .join(User, User.id == RecommendationRequest.user_id)
            .where(
                User.role == "user",
                *request_conditions
            )
        ).one()
        requests = session.exec(
            select(func.count(RecommendationRequest.id)).where(*request_conditions)
        ).one()
        exposures = session.exec(
            select(func.count(Exposure.id)).where(*exposure_conditions)
        ).one()
        clicks = session.exec(
            select(func.count(Event.id)).where(
                Event.event_type == EventType.CLICK, *event_conditions
            )
        ).one()
        likes = session.exec(
            select(func.count(Event.id)).where(
                Event.event_type == EventType.LIKE, *event_conditions
            )
        ).one()
        offline_items = session.exec(
            select(func.count(Item.id)).where(Item.status == ItemStatus.OFFLINE)
        ).one()
        feed_rows = session.exec(
            select(RecommendationRequest.feed_type, func.count(RecommendationRequest.id))
            .where(*request_conditions)
            .group_by(RecommendationRequest.feed_type)
        ).all()
        feed_counts = {feed_type.value: count for feed_type, count in feed_rows}
        feed_shares = {
            feed_type.value: feed_counts.get(feed_type.value, 0) / requests if requests else 0.0
            for feed_type in FeedType
        }
        hot_rows = session.exec(
            select(Event.item_id, func.count(Event.id).label("behavior_count"))
            .where(
                Event.event_type.in_([EventType.CLICK, EventType.LIKE]),
                *event_conditions,
            )
            .group_by(Event.item_id)
            .order_by(func.count(Event.id).desc(), Event.item_id)
            .limit(10)
        ).all()
        hot_items = []
        for item_id, behavior_count in hot_rows:
            item = session.get(Item, item_id)
            if item is not None:
                hot_items.append(
                    {
                        "item_id": item.id,
                        "title": item.title,
                        "behavior_count": behavior_count,
                    }
                )
        return DashboardOverview(
            window=window,
            window_start=_aware_utc(window_start),
            window_end=_aware_utc(window_end),
            users=users,
            active_users=active_users,
            requests=requests,
            exposures=exposures,
            clicks=clicks,
            ctr=clicks / exposures if exposures else 0.0,
            likes=likes,
            offline_items=offline_items,
            current_model_version=current_model_version,
            feed_shares=feed_shares,
            hot_items=hot_items,
        )

    @staticmethod
    def feed_diagnostics(
        session: Session,
        window: DashboardWindow = DashboardWindow.HOUR_24,
    ) -> list[dict[str, object]]:
        window_start, window_end = DashboardService._window_bounds(window)
        request_conditions = DashboardService._time_conditions(
            RecommendationRequest.created_at, window_start, window_end
        )
        exposure_conditions = DashboardService._time_conditions(
            Exposure.created_at, window_start, window_end
        )
        event_conditions = DashboardService._time_conditions(
            Event.created_at, window_start, window_end
        )
        result = []
        for feed_type in FeedType:
            request_ids = list(
                session.exec(
                    select(RecommendationRequest.id).where(
                        RecommendationRequest.feed_type == feed_type,
                        *request_conditions,
                    )
                ).all()
            )
            requests = len(request_ids)
            if request_ids:
                exposures = session.exec(
                    select(func.count(Exposure.id)).where(
                        Exposure.request_id.in_(request_ids), *exposure_conditions
                    )
                ).one()
                clicks = session.exec(
                    select(func.count(Event.id)).where(
                        Event.request_id.in_(request_ids),
                        Event.event_type == EventType.CLICK,
                        *event_conditions,
                    )
                ).one()
            else:
                exposures = clicks = 0
            result.append(
                {
                    "feed_type": feed_type,
                    "requests": requests,
                    "exposures": exposures,
                    "clicks": clicks,
                    "ctr": clicks / exposures if exposures else 0.0,
                }
            )
        return result

    @staticmethod
    def trends(
        session: Session,
        window: DashboardWindow = DashboardWindow.HOUR_24,
    ) -> DashboardTrends:
        window_start, window_end = DashboardService._window_bounds(window)
        request_times = list(
            session.exec(
                select(RecommendationRequest.created_at).where(
                    *DashboardService._time_conditions(
                        RecommendationRequest.created_at, window_start, window_end
                    )
                )
            ).all()
        )
        exposure_times = list(
            session.exec(
                select(Exposure.created_at).where(
                    *DashboardService._time_conditions(
                        Exposure.created_at, window_start, window_end
                    )
                )
            ).all()
        )
        event_rows = list(
            session.exec(
                select(Event.created_at, Event.event_type).where(
                    Event.event_type.in_([EventType.CLICK, EventType.LIKE]),
                    *DashboardService._time_conditions(
                        Event.created_at, window_start, window_end
                    ),
                )
            ).all()
        )

        bucket_minutes = DashboardService._BUCKET_MINUTES[window]
        bucket_delta = timedelta(minutes=bucket_minutes)
        if window_start is not None:
            bucket_anchor = window_start
            bucket_count = max(
                1,
                int((window_end - bucket_anchor).total_seconds() // bucket_delta.total_seconds()),
            )
        else:
            timestamps = request_times + exposure_times + [row[0] for row in event_rows]
            earliest = min(timestamps, default=window_end)
            bucket_anchor = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
            bucket_count = max(
                1,
                int((window_end - bucket_anchor) // bucket_delta) + 1,
            )

        buckets = [
            {"requests": 0, "exposures": 0, "clicks": 0, "likes": 0}
            for _ in range(bucket_count)
        ]

        def bucket_index(timestamp: datetime) -> int | None:
            index = int((timestamp - bucket_anchor) // bucket_delta)
            return index if 0 <= index < bucket_count else None

        for timestamp in request_times:
            if (index := bucket_index(timestamp)) is not None:
                buckets[index]["requests"] += 1
        for timestamp in exposure_times:
            if (index := bucket_index(timestamp)) is not None:
                buckets[index]["exposures"] += 1
        for timestamp, event_type in event_rows:
            if (index := bucket_index(timestamp)) is None:
                continue
            if event_type == EventType.CLICK:
                buckets[index]["clicks"] += 1
            else:
                buckets[index]["likes"] += 1

        points = []
        for index, bucket in enumerate(buckets):
            exposures = bucket["exposures"]
            points.append(
                DashboardTrendPoint(
                    bucket_start=_aware_utc(bucket_anchor + index * bucket_delta),
                    requests=bucket["requests"],
                    exposures=exposures,
                    clicks=bucket["clicks"],
                    likes=bucket["likes"],
                    ctr=bucket["clicks"] / exposures if exposures else 0.0,
                )
            )
        return DashboardTrends(
            window=window,
            window_start=_aware_utc(window_start),
            window_end=_aware_utc(window_end),
            bucket_minutes=bucket_minutes,
            points=points,
        )

    @staticmethod
    def request_traces(
        session: Session,
        window: DashboardWindow = DashboardWindow.HOUR_24,
        *,
        feed_type: FeedType | None = None,
        limit: int = 10,
    ) -> RequestTracesResponse:
        window_start, window_end = DashboardService._window_bounds(window)
        conditions = DashboardService._time_conditions(
            RecommendationRequest.created_at, window_start, window_end
        )
        if feed_type is not None:
            conditions.append(RecommendationRequest.feed_type == feed_type)
        rows = list(
            session.exec(
                select(RecommendationRequest, User.username)
                .join(User, User.id == RecommendationRequest.user_id)
                .where(*conditions)
                .order_by(RecommendationRequest.created_at.desc())
                .limit(limit)
            ).all()
        )
        request_ids = [request.id for request, _ in rows]
        exposure_counts: dict[str, int] = {}
        event_counts: dict[tuple[str, EventType], int] = {}
        if request_ids:
            exposure_counts = {
                request_id: count
                for request_id, count in session.exec(
                    select(Exposure.request_id, func.count(Exposure.id))
                    .where(Exposure.request_id.in_(request_ids))
                    .group_by(Exposure.request_id)
                ).all()
            }
            event_counts = {
                (request_id, event_type): count
                for request_id, event_type, count in session.exec(
                    select(Event.request_id, Event.event_type, func.count(Event.id))
                    .where(
                        Event.request_id.in_(request_ids),
                        Event.event_type.in_(
                            [EventType.CLICK, EventType.LIKE, EventType.NOT_INTERESTED]
                        ),
                    )
                    .group_by(Event.request_id, Event.event_type)
                ).all()
            }
        return RequestTracesResponse(
            window=window,
            window_start=_aware_utc(window_start),
            window_end=_aware_utc(window_end),
            items=[
                RequestTraceSummary(
                    request_id=request.id,
                    username=username,
                    feed_type=request.feed_type,
                    model_version=request.model_version,
                    created_at=_aware_utc(request.created_at),
                    feed_build_latency_ms=request.latency_ms,
                    fallback_reason=request.fallback_reason,
                    exposures=exposure_counts.get(request.id, 0),
                    clicks=event_counts.get((request.id, EventType.CLICK), 0),
                    likes=event_counts.get((request.id, EventType.LIKE), 0),
                    not_interested=event_counts.get(
                        (request.id, EventType.NOT_INTERESTED), 0
                    ),
                )
                for request, username in rows
            ],
        )

    @staticmethod
    def observability(
        session: Session,
        window: DashboardWindow = DashboardWindow.HOUR_24,
    ) -> ObservabilityResponse:
        window_start, window_end = DashboardService._window_bounds(window)
        rows = list(
            session.exec(
                select(RecommendationRequest).where(
                    *DashboardService._time_conditions(
                        RecommendationRequest.created_at, window_start, window_end
                    )
                )
            ).all()
        )
        return aggregate_observability(
            (
                RequestObservation(
                    feed_type=request.feed_type,
                    model_version=request.model_version,
                    feed_build_latency_ms=request.latency_ms,
                    fallback_reason=request.fallback_reason,
                )
                for request in rows
            ),
            window=window,
            window_start=_aware_utc(window_start),
            window_end=_aware_utc(window_end),
        )

    @staticmethod
    def model_evaluation(
        artifact_root: Path,
        runtime: ModelRuntimeResponse,
    ) -> ModelEvaluationResponse:
        if runtime.current is None:
            raise HTTPException(status_code=404, detail="No active model artifact")
        root = artifact_root.resolve()
        artifact = (root / runtime.current.path).resolve()
        if artifact.parent != root:
            raise HTTPException(status_code=404, detail="Active model artifact is invalid")
        try:
            metrics = json.loads((artifact / "metrics.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation artifact is unavailable"
            ) from exc
        selection = metrics.get("selection", {})
        selected_candidate = str(
            selection.get("selected_candidate") or selection.get("selected_policy") or ""
        )
        validation = metrics.get("validation", {})
        test = metrics.get("test", {})
        policies = []
        for policy, validation_payload in validation.items():
            if policy in {"random", "popularity"} or policy.startswith("als_"):
                continue
            test_payload = test.get(policy)
            policies.append(
                PolicyEvaluation(
                    policy=policy,
                    selected=policy == selected_candidate,
                    validation=_evaluation_slices(validation_payload),
                    test=(
                        _evaluation_slices(test_payload)
                        if isinstance(test_payload, dict)
                        else None
                    ),
                )
            )
        if not policies:
            raise HTTPException(status_code=404, detail="Evaluation policies are unavailable")
        return ModelEvaluationResponse(
            model_version=runtime.current.model_version,
            selected_policy=selected_candidate,
            selection_metric=str(selection.get("metric") or "validation.overall.ndcg_at_20"),
            policies=policies,
        )

    @staticmethod
    def user_debug(session: Session, user_id: int) -> dict[str, object]:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        events = list(
            session.exec(
                select(Event)
                .where(Event.user_id == user_id)
                .order_by(Event.created_at.desc())
                .limit(30)
            ).all()
        )
        requests = list(
            session.exec(
                select(RecommendationRequest)
                .where(RecommendationRequest.user_id == user_id)
                .order_by(RecommendationRequest.created_at.desc())
                .limit(10)
            ).all()
        )
        counts = Counter(event.event_type.value for event in events)
        latest_exposures = []
        if requests:
            latest_exposures = list(
                session.exec(
                    select(Exposure)
                    .where(Exposure.request_id == requests[0].id)
                    .order_by(Exposure.position)
                ).all()
            )
        return {
            "user": {
                "id": user.id,
                "username": user.username,
                "profile_version": user.profile_version,
            },
            "event_counts": counts,
            "recent_requests": requests,
            "recent_events": events,
            "latest_exposures": latest_exposures,
        }

    @staticmethod
    def request_trace(session: Session, request_id: str) -> dict[str, object]:
        request = session.get(RecommendationRequest, request_id)
        if request is None:
            raise HTTPException(status_code=404, detail="Request not found")
        exposures = list(
            session.exec(
                select(Exposure)
                .where(Exposure.request_id == request_id)
                .order_by(Exposure.position)
            ).all()
        )
        events = list(
            session.exec(
                select(Event)
                .where(Event.request_id == request_id)
                .order_by(Event.created_at)
            ).all()
        )
        return {"request": request, "exposures": exposures, "events": events}

    @staticmethod
    def models(session: Session) -> list[ModelVersion]:
        return list(
            session.exec(
                select(ModelVersion).order_by(
                    (ModelVersion.status == ModelStatus.PUBLISHED).desc(),
                    ModelVersion.trained_at.desc(),
                )
            ).all()
        )

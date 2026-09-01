from collections.abc import Sequence

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.engine import Engine
from sqlmodel import Session, select
from starlette.requests import Request

from app.constants import UserRole
from app.models import Event, Exposure, Item, ModelVersion, Operation, RecommendationRequest, User
from app.security import verify_password


class ApplicationAdminAuth(AuthenticationBackend):
    """Authenticate SQLAdmin separately with the application's admin accounts."""

    def __init__(self, secret_key: str, engine: Engine) -> None:
        super().__init__(
            secret_key,
            session_cookie="microlens_admin_session",
            same_site="lax",
        )
        self.engine = engine

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == username)).first()
            if (
                user is None
                or user.role != UserRole.ADMIN
                or not verify_password(password, user.password_hash)
            ):
                return False
            request.session["admin_user_id"] = user.id
            return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        user_id = request.session.get("admin_user_id")
        if not isinstance(user_id, int):
            return False
        with Session(self.engine) as session:
            user = session.get(User, user_id)
            return user is not None and user.role == UserRole.ADMIN


class ReadOnlyModelView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    page_size = 50
    page_size_options = [25, 50, 100]


class ItemAdmin(ReadOnlyModelView, model=Item):
    name = "内容"
    name_plural = "内容"
    icon = "fa-solid fa-film"
    column_list = [
        Item.id,
        Item.title,
        Item.status,
        Item.train_interactions,
        Item.likes,
        Item.views,
        Item.updated_at,
    ]
    column_searchable_list = [Item.title]
    column_sortable_list = [Item.id, Item.status, Item.train_interactions, Item.updated_at]


class RequestAdmin(ReadOnlyModelView, model=RecommendationRequest):
    name = "推荐请求"
    name_plural = "推荐请求"
    icon = "fa-solid fa-code-branch"
    column_list = [
        RecommendationRequest.id,
        RecommendationRequest.user_id,
        RecommendationRequest.feed_type,
        RecommendationRequest.model_version,
        RecommendationRequest.page,
        RecommendationRequest.latency_ms,
        RecommendationRequest.fallback_reason,
        RecommendationRequest.created_at,
    ]


class ExposureAdmin(ReadOnlyModelView, model=Exposure):
    name = "曝光"
    name_plural = "曝光"
    icon = "fa-solid fa-eye"
    column_list = [
        Exposure.id,
        Exposure.request_id,
        Exposure.user_id,
        Exposure.item_id,
        Exposure.position,
        Exposure.source,
        Exposure.score,
        Exposure.created_at,
    ]


class EventAdmin(ReadOnlyModelView, model=Event):
    name = "行为事件"
    name_plural = "行为事件"
    icon = "fa-solid fa-bolt"
    column_list = [
        Event.id,
        Event.event_id,
        Event.user_id,
        Event.item_id,
        Event.event_type,
        Event.source,
        Event.created_at,
    ]


class OperationAdmin(ReadOnlyModelView, model=Operation):
    name = "运营审计"
    name_plural = "运营审计"
    icon = "fa-solid fa-clipboard-list"
    column_list = [
        Operation.id,
        Operation.admin_user_id,
        Operation.item_id,
        Operation.operation_type,
        Operation.scope,
        Operation.reason,
        Operation.active,
        Operation.starts_at,
        Operation.ends_at,
        Operation.created_at,
    ]


class ModelVersionAdmin(ReadOnlyModelView, model=ModelVersion):
    name = "模型版本"
    name_plural = "模型版本"
    icon = "fa-solid fa-cube"
    column_list = [
        ModelVersion.id,
        ModelVersion.status,
        ModelVersion.data_version,
        ModelVersion.metrics_json,
        ModelVersion.trained_at,
        ModelVersion.published_at,
    ]


READ_ONLY_VIEWS: Sequence[type[ReadOnlyModelView]] = (
    ItemAdmin,
    RequestAdmin,
    ExposureAdmin,
    EventAdmin,
    OperationAdmin,
    ModelVersionAdmin,
)


def configure_read_only_admin(
    app: FastAPI,
    engine: Engine,
    *,
    authentication_backend: AuthenticationBackend | None = None,
    secret_key: str | None = None,
) -> Admin:
    """Register an authenticated, database-level diagnostics console."""
    if authentication_backend is None:
        secret = secret_key or getattr(getattr(app.state, "settings", None), "secret_key", None)
        if not secret:
            raise ValueError("secret_key is required when no authentication backend is provided")
        authentication_backend = ApplicationAdminAuth(secret, engine)
    admin = Admin(
        app,
        engine,
        title="MicroLens 数据审计",
        base_url="/db-admin",
        authentication_backend=authentication_backend,
    )
    for view in READ_ONLY_VIEWS:
        admin.add_view(view)
    return admin

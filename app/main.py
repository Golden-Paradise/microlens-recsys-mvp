from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.admin import configure_read_only_admin
from app.api import router as api_router
from app.config import Settings
from app.database import Database
from app.model_manager import ModelManager
from app.recommendation import (
    ALSRecommendationEngine,
    RecommendationEngine,
)
from app.seed import seed_demo_data
from app.services import DashboardService
from app.web import register_web
from recsys.model import ModelBundle


def create_app(
    settings: Settings | None = None,
    recommendation_engine: RecommendationEngine | None = None,
) -> FastAPI:
    settings = settings or Settings()
    model_bundle: ModelBundle | None = None
    model_manager: ModelManager | None = None
    if recommendation_engine is None:
        model_manager = ModelManager(settings.artifact_dir)
        recommendation_engine = model_manager.snapshot()
    if isinstance(recommendation_engine, ALSRecommendationEngine):
        model_bundle = recommendation_engine.bundle

    database = Database(settings.database_url)
    database.create_all()
    if settings.seed_demo_data:
        with database.session() as session:
            seed_demo_data(
                session,
                settings.demo_password,
                processed_dir=settings.processed_dir,
                artifact_dir=settings.artifact_dir,
                model_bundle=model_bundle,
                seed_official_catalog=settings.seed_official_catalog,
            )
            if model_manager is not None:
                DashboardService.sync_model_projection(
                    session,
                    settings.artifact_dir,
                    model_manager.runtime(),
                )

    application = FastAPI(title=settings.name)
    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="microlens_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    application.state.settings = settings
    application.state.db = database
    application.state.recommendation_engine = recommendation_engine
    application.state.model_manager = model_manager
    application.include_router(api_router)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    register_web(application)
    configure_read_only_admin(application, database.engine)
    return application


app = create_app()

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.config import Settings
from app.database import Database
from app.recommendation import (
    ALSRecommendationEngine,
    DeterministicRecommendationEngine,
    RecommendationEngine,
)
from app.seed import seed_demo_data
from recsys.model import ModelBundle, load_model_bundle


def create_app(
    settings: Settings | None = None,
    recommendation_engine: RecommendationEngine | None = None,
) -> FastAPI:
    settings = settings or Settings()
    model_bundle: ModelBundle | None = None
    if recommendation_engine is None:
        try:
            model_bundle = load_model_bundle(settings.artifact_dir)
            recommendation_engine = ALSRecommendationEngine(model_bundle)
        except (FileNotFoundError, OSError, ValueError, KeyError):
            recommendation_engine = DeterministicRecommendationEngine()

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
    application.include_router(api_router)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()

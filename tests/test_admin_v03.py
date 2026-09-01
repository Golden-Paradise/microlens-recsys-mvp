import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model_manager import (
    ArtifactNotFoundError,
    ArtifactValidationError,
    ModelActivationError,
)
from app.recommendation import DeterministicRecommendationEngine
from app.schemas import ModelRuntimeResponse
from app.seed import DEMO_PASSWORD
from app.services import DashboardService


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        secret_key="test-secret-key-with-enough-entropy",
        database_url="sqlite://",
        artifact_dir=tmp_path / "artifacts",
        cookie_secure=False,
        seed_demo_data=True,
        seed_official_catalog=False,
    )
    return TestClient(
        create_app(
            settings=settings,
            recommendation_engine=DeterministicRecommendationEngine(),
        )
    )


def _login(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200


def _runtime() -> ModelRuntimeResponse:
    return ModelRuntimeResponse.model_validate(
        {
            "status": "ready",
            "current": {
                "model_version": "content-v1",
                "path": "content-v1",
                "serving_policy": "bm25_content",
            },
            "previous": None,
            "loaded_at": "2026-09-02T01:00:00Z",
            "validation": {
                "status": "ok",
                "checked_at": "2026-09-02T01:00:00Z",
                "errors": [],
            },
        }
    )


class FakeManager:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self.publish_error = publish_error

    def snapshot(self) -> DeterministicRecommendationEngine:
        return DeterministicRecommendationEngine()

    def runtime(self) -> ModelRuntimeResponse:
        return _runtime()

    def publish(self, version: str) -> ModelRuntimeResponse:
        if self.publish_error is not None:
            raise self.publish_error
        return _runtime()

    def rollback(self) -> ModelRuntimeResponse:
        if self.publish_error is not None:
            raise self.publish_error
        return _runtime()


def test_recent_request_traces_and_observability_use_real_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client, "alice")
        feed = client.get("/api/feeds/personalized?page_size=4").json()
        first_item = feed["items"][0]["item_id"]
        for event_type in ["click", "like"]:
            response = client.post(
                "/api/events",
                json={
                    "event_id": str(uuid4()),
                    "request_id": feed["request_id"],
                    "item_id": first_item,
                    "event_type": event_type,
                },
            )
            assert response.status_code == 200
        client.post("/api/auth/logout")
        _login(client, "admin")

        canonical = client.get("/api/admin/request-traces?window=24h")
        alias = client.get("/api/admin/requests?window=24h")
        assert canonical.status_code == alias.status_code == 200
        assert canonical.json()["window"] == alias.json()["window"] == "24h"
        assert canonical.json()["items"] == alias.json()["items"]
        trace = canonical.json()["items"][0]
        assert trace["request_id"] == feed["request_id"]
        assert trace["username"] == "alice"
        assert trace["exposures"] == 4
        assert trace["clicks"] == trace["likes"] == 1
        assert trace["not_interested"] == 0
        assert trace["feed_build_latency_ms"] >= 0

        observability = client.get("/api/admin/observability?window=24h")
        assert observability.status_code == 200
        assert observability.json()["requests"] == 1
        assert observability.json()["alerts"] == []
        assert client.get("/api/admin/request-traces?window=invalid").status_code == 422
        assert client.get("/api/admin/observability?window=invalid").status_code == 422


def test_new_admin_endpoints_reject_regular_users_before_runtime_lookup(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        _login(client, "alice")
        for path in [
            "/api/admin/request-traces",
            "/api/admin/observability",
            "/api/admin/models/runtime",
            "/api/admin/models/current/evaluation",
        ]:
            assert client.get(path).status_code == 403
        assert client.post("/api/admin/models/demo/publish").status_code == 403
        assert client.post("/api/admin/models/rollback").status_code == 403


def test_model_evaluation_adapts_slices_and_keeps_unrun_test_null(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifacts" / "content-v1"
    artifact.mkdir(parents=True)
    metric = {"recall_at_k": 0.1, "ndcg_at_k": 0.05, "coverage_at_k": 0.9}
    (artifact / "metrics.json").write_text(
        json.dumps(
            {
                "selection": {
                    "metric": "validation.overall.ndcg_at_20",
                    "selected_policy": "bm25_content",
                    "selected_candidate": "bm25_content_word_q1",
                },
                "validation": {
                    "bm25": {
                        "overall": metric,
                        "warm_item": metric,
                        "pure_cold": {
                            "recall_at_k": 0.0,
                            "ndcg_at_k": 0.0,
                            "coverage_at_k": 0.0,
                        },
                    },
                    "bm25_content_word_q1": {
                        "overall": metric,
                        "warm_item": metric,
                        "pure_cold": metric,
                    },
                },
                "test": {"bm25": {"overall": metric, "warm_item": metric}},
            }
        ),
        encoding="utf-8",
    )
    with _client(tmp_path) as client:
        client.app.state.model_manager = FakeManager()
        _login(client, "admin")
        response = client.get("/api/admin/models/current/evaluation")

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["selected_policy"] == "bm25_content_word_q1"
        selected = next(policy for policy in payload["policies"] if policy["selected"])
        assert selected["validation"]["pure_cold"]["recall_at_20"] == 0.1
        assert selected["test"] is None


def test_model_activation_errors_map_to_stable_http_statuses(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client, "admin")
        client.app.state.model_manager = FakeManager(
            publish_error=ArtifactNotFoundError("Model version directory was not found")
        )
        assert client.post("/api/admin/models/missing/publish").status_code == 404
        client.app.state.model_manager = FakeManager(
            publish_error=ArtifactValidationError("Manifest files are missing")
        )
        assert client.post("/api/admin/models/corrupt/publish").status_code == 409
        client.app.state.model_manager = FakeManager(
            publish_error=ModelActivationError("No previous model version")
        )
        assert client.post("/api/admin/models/rollback").status_code == 409


def test_projection_failure_reports_warning_after_successful_switch(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_projection(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(DashboardService, "sync_model_projection", fail_projection)
    with _client(tmp_path) as client:
        _login(client, "admin")
        client.app.state.model_manager = FakeManager()

        response = client.post("/api/admin/models/content-v1/publish")

        assert response.status_code == 200
        assert response.json()["current"]["model_version"] == "content-v1"
        assert "dashboard projection is stale" in response.json()["projection_warning"]


def _write_projection_manifest(artifact_root: Path, version: str) -> None:
    artifact = artifact_root / version
    artifact.mkdir(parents=True)
    (artifact / "manifest.json").write_text(
        json.dumps(
            {
                "model_version": version,
                "data_version": "fixture-v1",
                "created_at": "2026-09-02T01:00:00Z",
                "algorithm": "fixture",
                "factors": 2,
                "iterations": 1,
                "regularization": 0.01,
                "alpha": 1.0,
                "top_k": 20,
                "files": {},
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )


def test_model_registry_projects_artifacts_and_hides_builtin_fallback(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    _write_projection_manifest(artifact_root, "content-v1")
    _write_projection_manifest(artifact_root, "candidate-v2")
    with _client(tmp_path) as client:
        client.app.state.model_manager = FakeManager()
        _login(client, "admin")

        response = client.get("/api/admin/models")

        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()}
        assert set(rows) == {"content-v1", "candidate-v2"}
        assert rows["content-v1"]["status"] == "published"
        assert rows["candidate-v2"]["status"] == "candidate"


def test_startup_deterministic_fallback_is_visible_in_request_observability(
    tmp_path: Path,
) -> None:
    settings = Settings(
        secret_key="test-secret-key-with-enough-entropy",
        database_url="sqlite://",
        artifact_dir=tmp_path / "missing-artifacts",
        cookie_secure=False,
        seed_demo_data=True,
        seed_official_catalog=False,
    )
    with TestClient(create_app(settings=settings)) as client:
        _login(client, "alice")
        feed = client.get("/api/feeds/personalized?page_size=4")
        assert feed.status_code == 200
        assert "ModelManager startup fallback" in feed.json()["fallback_reason"]
        client.post("/api/auth/logout")
        _login(client, "admin")
        observability = client.get("/api/admin/observability?window=24h").json()
        assert observability["requests"] == 1
        assert observability["fallback_count"] == 1
        assert observability["fallback_rate"] == 1.0

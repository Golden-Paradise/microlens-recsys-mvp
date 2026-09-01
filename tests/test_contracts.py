import json
from pathlib import Path

from app.constants import EventType, FeedType, ItemStatus
from app.schemas import (
    FeedResponse,
    ModelEvaluationResponse,
    ModelRuntimeResponse,
    ObservabilityResponse,
    RequestTracesResponse,
)
from recsys.contracts import ArtifactPointer, ModelManifest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v03_admin_contracts.json"


def test_public_enums_are_stable() -> None:
    assert {item.value for item in FeedType} == {"personalized", "popular", "explore"}
    assert {item.value for item in EventType} == {
        "impression",
        "click",
        "like",
        "not_interested",
    }
    assert {item.value for item in ItemStatus} == {"online", "offline"}


def test_feed_response_contract_has_required_trace_fields() -> None:
    fields = FeedResponse.model_fields
    assert {"request_id", "feed_type", "model_version", "items"} <= set(fields)


def test_v01_manifest_defaults_to_als_serving() -> None:
    manifest = ModelManifest.model_validate(
        {
            "model_version": "als-f2-demo",
            "data_version": "demo",
            "created_at": "2026-09-01T00:00:00Z",
            "algorithm": "implicit.als.AlternatingLeastSquares",
            "factors": 2,
            "iterations": 2,
            "regularization": 0.05,
            "alpha": 10.0,
            "top_k": 20,
            "files": {},
            "metrics": {},
        }
    )

    assert manifest.serving_policy == "als"
    assert manifest.retrievers == ["als"]
    assert manifest.rrf_k == 60
    assert manifest.content_retriever is None


def test_legacy_pointer_upgrades_to_v2_contract() -> None:
    pointer = ArtifactPointer.model_validate(
        {"model_version": "hybrid-bm25-demo", "path": "hybrid-bm25-demo"}
    )

    assert pointer.schema_version == 2
    assert pointer.current.model_version == "hybrid-bm25-demo"
    assert pointer.current.path == "hybrid-bm25-demo"
    assert pointer.previous is None


def test_v03_admin_json_fixtures_match_frozen_contracts() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    ModelRuntimeResponse.model_validate(fixture["runtime"])
    ModelEvaluationResponse.model_validate(fixture["evaluation"])
    RequestTracesResponse.model_validate(fixture["request_traces"])
    ObservabilityResponse.model_validate(fixture["observability"])

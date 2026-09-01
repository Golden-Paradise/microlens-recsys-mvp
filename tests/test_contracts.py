from app.constants import EventType, FeedType, ItemStatus
from app.schemas import FeedResponse
from recsys.contracts import ModelManifest


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

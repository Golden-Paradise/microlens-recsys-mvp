from app.constants import EventType, FeedType, ItemStatus
from app.schemas import FeedResponse


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


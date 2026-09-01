from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import Settings
from app.constants import EventType, FeedType
from app.database import Database
from app.main import create_app
from app.models import Event, Exposure, RecommendationRequest, User
from app.recommendation import DeterministicRecommendationEngine
from app.seed import DEMO_PASSWORD


def make_client(engine: object | None = None) -> TestClient:
    settings = Settings(
        secret_key="test-secret-key-with-enough-entropy",
        database_url="sqlite://",
        cookie_secure=False,
        seed_demo_data=True,
        seed_official_catalog=False,
    )
    return TestClient(
        create_app(
            settings=settings,
            recommendation_engine=engine or DeterministicRecommendationEngine(),
        )
    )


def login(client: TestClient, username: str) -> dict[str, object]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def behavior_payload(feed: dict[str, object], event_type: str = "click") -> dict[str, object]:
    item = feed["items"][0]
    return {
        "event_id": str(uuid4()),
        "request_id": feed["request_id"],
        "item_id": item["item_id"],
        "event_type": event_type,
    }


def test_auth_personalization_pagination_and_unique_trace() -> None:
    with make_client() as alice:
        assert alice.get("/api/auth/me").status_code == 401
        assert alice.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong-pass"}
        ).status_code == 401
        login(alice, "alice")
        assert alice.get("/api/auth/me").json()["username"] == "alice"

        first = alice.get("/api/feeds/personalized?page=1&page_size=6").json()
        second = alice.get("/api/feeds/personalized?page=2&page_size=6").json()
        assert first["request_id"] != second["request_id"]
        assert len(first["items"]) == 6
        assert len({item["item_id"] for item in first["items"]}) == 6
        assert {item["item_id"] for item in first["items"]}.isdisjoint(
            {item["item_id"] for item in second["items"]}
        )

        assert alice.post("/api/auth/logout").status_code == 204
        assert alice.get("/api/auth/me").status_code == 401

    with make_client() as bob_client, make_client() as alice_client:
        login(alice_client, "alice")
        login(bob_client, "bob")
        alice_ids = [
            row["item_id"]
            for row in alice_client.get("/api/feeds/personalized?page_size=8").json()[
                "items"
            ]
        ]
        bob_ids = [
            row["item_id"]
            for row in bob_client.get("/api/feeds/personalized?page_size=8").json()["items"]
        ]
        assert alice_ids != bob_ids


def test_session_cookie_is_http_only_and_tampering_is_rejected() -> None:
    with make_client() as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": DEMO_PASSWORD},
        )
        cookie_header = response.headers["set-cookie"].lower()
        assert "httponly" in cookie_header
        assert "samesite=lax" in cookie_header
        signed_value = client.cookies.get("microlens_session")

    with make_client() as attacker:
        attacker.cookies.set("microlens_session", f"{signed_value}tampered")
        assert attacker.get("/api/auth/me").status_code == 401


def test_file_sqlite_uses_wal_and_foreign_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "online.db"
    database = Database(f"sqlite:///{database_path.as_posix()}")
    database.create_all()
    with database.engine.connect() as connection:
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
    assert journal_mode.lower() == "wal"
    assert foreign_keys == 1


def test_event_is_idempotent_owned_and_updates_profile() -> None:
    with make_client() as client:
        alice = login(client, "alice")
        feed = client.get("/api/feeds/popular?page_size=3").json()
        payload = behavior_payload(feed)

        created = client.post("/api/events", json=payload)
        assert created.status_code == 200
        assert created.json() == {
            "event_id": payload["event_id"],
            "status": "created",
            "profile_version": 1,
        }
        duplicate = client.post("/api/events", json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json()["status"] == "duplicate"
        assert duplicate.json()["profile_version"] == 1

        conflicting = payload | {"item_id": feed["items"][1]["item_id"]}
        assert client.post("/api/events", json=conflicting).status_code == 409
        impression = behavior_payload(feed, "impression")
        assert client.post("/api/events", json=impression).status_code == 400
        assert client.get("/api/profile/me").json()["profile_version"] == 1

        client.post("/api/auth/logout")
        login(client, "bob")
        foreign = behavior_payload(feed) | {"event_id": str(uuid4())}
        assert client.post("/api/events", json=foreign).status_code == 404

        client.post("/api/auth/logout")
        login(client, "admin")
        debug = client.get(f"/api/admin/users/{alice['id']}/debug")
        assert debug.status_code == 200
        assert debug.json()["user"]["profile_version"] == 1


def test_dashboard_diagnostics_and_request_trace_use_real_events() -> None:
    with make_client() as client:
        login(client, "alice")
        feed = client.get("/api/feeds/explore?page_size=4").json()
        click = client.post("/api/events", json=behavior_payload(feed, "click"))
        assert click.status_code == 200
        like = behavior_payload(feed, "like")
        like["item_id"] = feed["items"][1]["item_id"]
        assert client.post("/api/events", json=like).status_code == 200
        assert client.get("/api/admin/dashboard").status_code == 403

        client.post("/api/auth/logout")
        login(client, "admin")
        overview = client.get("/api/admin/dashboard").json()
        assert overview["window"] == "24h"
        assert overview["window_start"] is not None
        assert overview["window_end"] is not None
        assert overview["users"] == 3
        assert overview["active_users"] == 1
        assert overview["requests"] == 1
        assert overview["exposures"] == 4
        assert overview["clicks"] == 1
        assert overview["likes"] == 1
        assert overview["ctr"] == pytest.approx(0.25)
        assert overview["feed_shares"] == {
            "personalized": 0.0,
            "popular": 0.0,
            "explore": 1.0,
        }
        assert overview["hot_items"][0]["behavior_count"] == 1

        diagnostics = client.get("/api/admin/feeds/diagnostics").json()
        explore = next(row for row in diagnostics if row["feed_type"] == "explore")
        assert {key: explore[key] for key in ("requests", "exposures", "clicks")} == {
            "requests": 1,
            "exposures": 4,
            "clicks": 1,
        }
        trace = client.get(f"/api/admin/requests/{feed['request_id']}").json()
        assert trace["request"]["id"] == feed["request_id"]
        assert len(trace["exposures"]) == 4
        assert len(trace["events"]) == 6  # 4 impressions plus click and like
        models = client.get("/api/admin/models").json()
        assert models[0]["id"] == "deterministic-v1"


def test_dashboard_windows_trends_and_diagnostics_share_utc_bounds() -> None:
    with make_client() as client:
        login(client, "alice")
        current_feed = client.get("/api/feeds/explore?page_size=4").json()
        assert client.post(
            "/api/events", json=behavior_payload(current_feed, "click")
        ).status_code == 200
        current_like = behavior_payload(current_feed, "like")
        current_like["item_id"] = current_feed["items"][1]["item_id"]
        assert client.post("/api/events", json=current_like).status_code == 200

        two_hours_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        old_request_id = str(uuid4())
        with Session(client.app.state.db.engine) as session:
            alice = session.exec(select(User).where(User.username == "alice")).one()
            session.add(
                RecommendationRequest(
                    id=old_request_id,
                    user_id=alice.id,
                    feed_type=FeedType.EXPLORE,
                    model_version="deterministic-v1",
                    page=1,
                    page_size=1,
                    created_at=two_hours_ago,
                )
            )
            session.flush()
            session.add(
                Exposure(
                    request_id=old_request_id,
                    user_id=alice.id,
                    item_id=1,
                    position=1,
                    source="explore",
                    score=0.5,
                    reason="historical fixture",
                    created_at=two_hours_ago,
                )
            )
            session.add(
                Event(
                    event_id=str(uuid4()),
                    request_id=old_request_id,
                    user_id=alice.id,
                    item_id=1,
                    position=1,
                    event_type=EventType.CLICK,
                    source="explore",
                    created_at=two_hours_ago,
                )
            )
            session.commit()

        assert client.get("/api/admin/dashboard/trends?window=1h").status_code == 403
        assert client.get("/api/admin/feeds/diagnostics?window=1h").status_code == 403
        client.post("/api/auth/logout")
        login(client, "admin")

        overview_1h = client.get("/api/admin/dashboard?window=1h").json()
        overview_6h = client.get("/api/admin/dashboard?window=6h").json()
        overview_all = client.get("/api/admin/dashboard?window=all").json()
        assert (overview_1h["requests"], overview_1h["exposures"], overview_1h["clicks"]) == (
            1,
            4,
            1,
        )
        assert (overview_6h["requests"], overview_6h["exposures"], overview_6h["clicks"]) == (
            2,
            5,
            2,
        )
        assert overview_1h["likes"] == overview_6h["likes"] == 1
        assert overview_all["window_start"] is None
        for global_key in ("users", "offline_items", "current_model_version"):
            assert overview_1h[global_key] == overview_6h[global_key] == overview_all[global_key]

        diagnostics_1h = client.get("/api/admin/feeds/diagnostics?window=1h").json()
        diagnostics_6h = client.get("/api/admin/feeds/diagnostics?window=6h").json()
        explore_1h = next(row for row in diagnostics_1h if row["feed_type"] == "explore")
        explore_6h = next(row for row in diagnostics_6h if row["feed_type"] == "explore")
        assert (explore_1h["requests"], explore_1h["exposures"], explore_1h["clicks"]) == (
            1,
            4,
            1,
        )
        assert (explore_6h["requests"], explore_6h["exposures"], explore_6h["clicks"]) == (
            2,
            5,
            2,
        )

        expected = {"1h": (5, 12, 1, 4, 1), "6h": (30, 12, 2, 5, 2)}
        for window, (minutes, point_count, requests, exposures, clicks) in expected.items():
            trend = client.get(f"/api/admin/dashboard/trends?window={window}").json()
            assert trend["bucket_minutes"] == minutes
            assert len(trend["points"]) == point_count
            assert sum(point["requests"] for point in trend["points"]) == requests
            assert sum(point["exposures"] for point in trend["points"]) == exposures
            assert sum(point["clicks"] for point in trend["points"]) == clicks
            assert sum(point["likes"] for point in trend["points"]) == 1
            assert any(
                point["requests"] == point["exposures"] == point["clicks"] == 0
                for point in trend["points"]
            )

        trend_24h = client.get("/api/admin/dashboard/trends?window=24h").json()
        assert trend_24h["bucket_minutes"] == 60
        assert len(trend_24h["points"]) == 24
        trend_all = client.get("/api/admin/dashboard/trends?window=all").json()
        assert trend_all["window_start"] is None
        assert trend_all["bucket_minutes"] == 1_440
        assert sum(point["requests"] for point in trend_all["points"]) == 2
        assert client.get("/api/admin/dashboard?window=invalid").status_code == 422
        assert client.get("/api/admin/dashboard/trends?window=invalid").status_code == 422


def test_force_offline_restore_precedence_and_audit() -> None:
    with make_client() as client:
        login(client, "admin")
        force = client.post(
            "/api/admin/operations/force",
            json={"item_id": 40, "reason": "测试活动强推", "scope": "all"},
        )
        assert force.status_code == 200, force.text

        client.post("/api/auth/logout")
        login(client, "alice")
        forced_feed = client.get("/api/feeds/personalized?page_size=5").json()
        assert forced_feed["items"][0]["item_id"] == 40
        assert forced_feed["items"][0]["source"] == "forced"

        client.post("/api/auth/logout")
        login(client, "admin")
        offline = client.post(
            "/api/admin/operations/offline",
            json={"item_id": 40, "reason": "内容合规下线"},
        )
        assert offline.status_code == 200

        client.post("/api/auth/logout")
        login(client, "bob")
        assert client.get("/api/items/40").status_code == 404
        bob_feed = client.get("/api/feeds/popular?page_size=40").json()
        assert 40 not in {row["item_id"] for row in bob_feed["items"]}

        client.post("/api/auth/logout")
        login(client, "admin")
        restore = client.post(
            "/api/admin/operations/restore",
            json={"item_id": 40, "reason": "复核通过恢复"},
        )
        assert restore.status_code == 200
        contents = client.get("/api/admin/contents?q=40").json()
        assert contents[0]["status"] == "online"
        audit = client.get("/api/admin/operations").json()
        assert [row["operation_type"] for row in audit[:3]] == [
            "restore",
            "offline",
            "force",
        ]

        client.post("/api/auth/logout")
        login(client, "carol")
        restored_feed = client.get("/api/feeds/explore?page_size=5").json()
        assert restored_feed["items"][0]["item_id"] == 40


def test_force_scope_and_activation_window_are_enforced() -> None:
    with make_client() as client:
        login(client, "admin")
        user_scoped = client.post(
            "/api/admin/operations/force",
            json={
                "item_id": 40,
                "reason": "仅 Alice 可见",
                "scope": "user",
                "scope_value": "alice",
            },
        )
        assert user_scoped.status_code == 200
        future = client.post(
            "/api/admin/operations/force",
            json={
                "item_id": 39,
                "reason": "明日活动",
                "scope": "all",
                "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "ends_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
        assert future.status_code == 200

        client.post("/api/auth/logout")
        login(client, "bob")
        bob_feed = client.get("/api/feeds/explore?page_size=10").json()
        assert all(item["source"] != "forced" for item in bob_feed["items"])

        client.post("/api/auth/logout")
        login(client, "alice")
        alice_feed = client.get("/api/feeds/explore?page_size=10").json()
        assert alice_feed["items"][0]["item_id"] == 40
        assert alice_feed["items"][0]["source"] == "forced"
        item_39 = next(
            (item for item in alice_feed["items"] if item["item_id"] == 39), None
        )
        assert item_39 is None or item_39["source"] != "forced"


class FailingRecommendationEngine:
    model_version = "broken-v1"

    def recommend(self, **_: object) -> list[object]:
        raise RuntimeError("artifact is unavailable")


def test_model_failure_falls_back_to_deterministic_popular() -> None:
    with make_client(FailingRecommendationEngine()) as client:
        login(client, "alice")
        response = client.get("/api/feeds/personalized?page_size=5")
        assert response.status_code == 200
        feed = response.json()
        assert feed["model_version"] == "deterministic-v1"
        assert "RuntimeError" in feed["fallback_reason"]
        assert {item["source"] for item in feed["items"]} == {"popular"}

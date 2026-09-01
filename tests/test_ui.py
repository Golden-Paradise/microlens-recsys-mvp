from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin import READ_ONLY_VIEWS, configure_read_only_admin
from app.database import Database
from app.web import STATIC_DIR, TEMPLATE_DIR, register_web


@pytest.fixture
def web_client() -> TestClient:
    application = FastAPI()
    register_web(application)
    return TestClient(application)


@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/login", "登录推荐系统"),
        ("/feed", "内容推荐"),
        ("/profile", "我的画像"),
        ("/admin/dashboard", "运营看板"),
        ("/admin/contents", "内容运营"),
    ],
)
def test_key_pages_render(web_client: TestClient, path: str, marker: str) -> None:
    response = web_client.get(path)
    assert response.status_code == 200
    assert marker in response.text
    assert "/static/app.css" in response.text
    assert "/static/app.js" in response.text


def test_root_redirects_to_feed_and_assets_are_local(web_client: TestClient) -> None:
    response = web_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/feed"

    assert web_client.get("/static/app.css").status_code == 200
    assert web_client.get("/static/app.js").status_code == 200
    assert web_client.get("/static/placeholder-cover.svg").status_code == 200

    base_template = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    assert "https://" not in base_template
    assert "http://" not in base_template


def test_feed_template_contains_trace_feedback_and_empty_states() -> None:
    feed = (TEMPLATE_DIR / "feed.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert {"personalized", "popular", "explore"} <= {
        value.split('"', 1)[0] for value in feed.split('data-feed="')[1:]
    }
    assert "request-id" in feed
    assert "feed-empty" in feed
    assert "button.dataset.event = eventType" in script
    assert '"not_interested"' in script
    assert "load-more" in feed


def test_dashboard_and_operations_have_required_controls() -> None:
    dashboard = (TEMPLATE_DIR / "admin_dashboard.html").read_text(encoding="utf-8")
    contents = (TEMPLATE_DIR / "admin_contents.html").read_text(encoding="utf-8")
    assert all(
        marker in dashboard
        for marker in (
            "业务概览",
            "信息流诊断",
            "信息流占比",
            "热门内容",
            "用户调试",
            "模型运行",
            "request-trace-form",
        )
    )
    assert all(
        marker in contents
        for marker in ("强推范围", "操作原因", "生效时间", "失效时间", "数据审计")
    )


def test_sqladmin_views_are_read_only_and_authenticated() -> None:
    for view in READ_ONLY_VIEWS:
        assert view.can_create is False
        assert view.can_edit is False
        assert view.can_delete is False

    application = FastAPI()
    database = Database("sqlite://")
    database.create_all()
    admin = configure_read_only_admin(
        application,
        database.engine,
        secret_key="test-secret-key-with-enough-entropy",
    )
    assert admin.authentication_backend is not None
    assert len(admin.views) == len(READ_ONLY_VIEWS)
    with TestClient(application) as client:
        response = client.get("/db-admin/", follow_redirects=False)
        assert response.status_code in {302, 307}
        assert "/db-admin/login" in response.headers["location"]


def test_static_paths_resolve_inside_app_directory() -> None:
    app_directory = Path(__file__).parents[1] / "app"
    assert STATIC_DIR == app_directory / "static"
    assert TEMPLATE_DIR == app_directory / "templates"

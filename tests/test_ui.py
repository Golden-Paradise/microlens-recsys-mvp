import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin import READ_ONLY_VIEWS, configure_read_only_admin
from app.database import Database
from app.web import STATIC_DIR, TEMPLATE_DIR, register_web

V03_CONTRACT_PATH = Path(__file__).parent / "fixtures" / "v03_admin_contracts.json"


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
            "dashboard-window-control",
            "trend-metric-control",
            "dashboard-trend-svg",
            "trend-tooltip",
            "trend-empty",
            "trend-error",
        )
    )
    assert all(
        marker in contents
        for marker in ("强推范围", "操作原因", "生效时间", "失效时间", "数据审计")
    )


def test_dashboard_window_and_trend_contract_is_wired_to_api() -> None:
    dashboard = (TEMPLATE_DIR / "admin_dashboard.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert {"1h", "6h", "24h", "all"} <= {
        value.split('"', 1)[0] for value in dashboard.split('data-window="')[1:]
    }
    assert {"requests", "exposures", "clicks", "likes", "ctr"} <= {
        value.split('"', 1)[0] for value in dashboard.split('data-trend-metric="')[1:]
    }
    assert 'data-window="24h"' in dashboard
    assert 'data-window="24h">24小时' in dashboard
    assert '/api/admin/dashboard?${query}' in script
    assert '/api/admin/feeds/diagnostics?${query}' in script
    assert '/api/admin/dashboard/trends?${query}' in script
    assert "document.createElementNS" in script
    assert "renderTrendChart" in script
    assert "Promise.allSettled" in script
    assert ".trend-stage" in styles
    assert "height: 320px" in styles
    assert "height: 260px" in styles


def test_v03_admin_reliability_contract_is_wired_to_isolated_regions() -> None:
    fixture = json.loads(V03_CONTRACT_PATH.read_text(encoding="utf-8"))
    dashboard = (TEMPLATE_DIR / "admin_dashboard.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert all(
        marker in dashboard
        for marker in (
            "model-runtime",
            "publish-model-button",
            "rollback-model-button",
            "model-operation-status",
            "model-decision-table",
            "observability-health",
            "observability-by-feed",
            "observability-by-model",
            "request-timeline",
            "request-trace-result",
        )
    )
    assert all(
        path in script
        for path in (
            "/api/admin/models/runtime",
            "/api/admin/models/current/evaluation",
            "/api/admin/request-traces",
            "/api/admin/observability",
            "/api/admin/models/rollback",
            "/publish",
        )
    )
    assert all(
        state in script
        for state in (
            "loading",
            "empty",
            "error",
            "ready",
            "legacy",
            "recovered",
            "fallback",
            "publishing",
            "published",
            "publish_failed",
            "rolling_back",
            "rolled_back",
            "rollback_failed",
        )
    )
    assert fixture["runtime"]["status"] in {"ready", "recovered", "fallback"}
    assert fixture["evaluation"]["policies"]
    assert fixture["request_traces"]["items"]
    assert "latency_ms" in fixture["observability"]
    assert all(
        key in script
        for key in (
            "selected_policy",
            "selection_metric",
            "pure_cold",
            "feed_build_latency_ms",
            "fallback_reason",
            "latency_ms",
            "alerts",
        )
    )
    assert "Promise.allSettled" in script
    assert "request-timeline-button" in script
    assert "loadRequestTrace" in script
    assert "renderRequestTraceDetail" in script
    assert "未正式测试" in script
    assert "样本不足，暂不判断告警" in script
    assert "count / exposureCount" in script


def test_v03_dashboard_is_two_column_and_stacks_for_390px() -> None:
    styles = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert ".reliability-grid" in styles
    assert ".request-detail-grid" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in styles
    assert "grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr)" in styles
    assert "@media (max-width: 780px)" in styles
    assert "@media (max-width: 480px)" in styles
    assert "grid-template-columns: 1fr" in styles
    assert "min-width: 0" in styles
    assert "box-shadow: var(--shadow)" not in styles.split(".ops-panel {", 1)[1].split("}", 1)[0]


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

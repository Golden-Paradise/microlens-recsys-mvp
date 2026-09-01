import hashlib
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATE_DIR = APP_DIR / "templates"


def _static_version() -> str:
    digest = hashlib.sha256()
    for asset_name in ("app.css", "app.js"):
        digest.update((STATIC_DIR / asset_name).read_bytes())
    return digest.hexdigest()[:12]


STATIC_VERSION = _static_version()

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(include_in_schema=False)


def page_context(request: Request, *, title: str, page: str) -> dict[str, object]:
    return {
        "request": request,
        "title": title,
        "page": page,
        "static_version": STATIC_VERSION,
    }


@router.get("/", response_class=RedirectResponse)
def index() -> RedirectResponse:
    return RedirectResponse(url="/feed", status_code=302)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=page_context(request, title="登录", page="login"),
    )


@router.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="feed.html",
        context=page_context(request, title="推荐流", page="feed"),
    )


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context=page_context(request, title="我的画像", page="profile"),
    )


@router.get("/admin/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context=page_context(request, title="运营看板", page="dashboard"),
    )


@router.get("/admin/contents", response_class=HTMLResponse)
def contents_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin_contents.html",
        context=page_context(request, title="内容运营", page="contents"),
    )


def register_web(app: FastAPI) -> None:
    """Attach local assets and presentation routes to the application."""
    if not any(getattr(route, "path", None) == "/static" for route in app.routes):
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)


mount_web = register_web

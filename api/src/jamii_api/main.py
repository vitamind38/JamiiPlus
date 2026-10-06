import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from jamii_api import __version__
from jamii_api.config import get_settings
from jamii_api.deps import LoginRequired
from jamii_api.routers import channels, health, mobile
from jamii_api.web import admin, issues, pages, review

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; "
        "script-src 'self'; frame-ancestors 'none'; form-action 'self'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
}


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if settings.sentry_dsn:
        import sentry_sdk

        # send_default_pii=False keeps phone numbers and report text out of crash reports.
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            release=__version__,
            send_default_pii=False,
            traces_sample_rate=0.0,
        )

    app = FastAPI(
        title="Jamii Pulse API",
        version=__version__,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="jp_session",
        max_age=settings.session_hours * 3600,
        same_site="lax",
        https_only=settings.environment != "local",
    )
    app.middleware("http")(health.metrics_middleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(LoginRequired)
    async def to_login(request: Request, _: LoginRequired):
        nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(nxt)}", 303)

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    for r in (health.router, mobile.router, channels.router, pages.router, review.router, issues.router, admin.router):
        app.include_router(r)
    return app


app = create_app()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from slovech.api.routes import router
from slovech.core.config import Settings, get_settings
from slovech.core.logging import configure_logging
from slovech.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from slovech.core.storage import Repository


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        app.state.repository.initialize()
        yield

    app = FastAPI(
        title="Slovech",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )
    app.state.settings = settings
    app.state.repository = Repository(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logging.getLogger(__name__).error("Unhandled request error type=%s", type(exc).__name__)
        return JSONResponse(
            {"detail": "Внутренняя ошибка", "request_id": getattr(request.state, "request_id", "")},
            500,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return app


app = create_app()

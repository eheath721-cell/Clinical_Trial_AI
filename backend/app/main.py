"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.accounts.router import router as accounts_router
from app.modules.documents.router import router as documents_router
from app.modules.enrollment.router import router as enrollment_router
from app.modules.profiles.router import router as profiles_router
from app.modules.trials.router import router as trials_router
from app.modules.trials.sources import get_repository

log = logging.getLogger("trialcompass.http")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title=f"{settings.app_name} API", version="0.1.0",
                  docs_url="/api/docs" if settings.environment != "production" else None,
                  openapi_url="/api/openapi.json" if settings.environment != "production" else None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["content-type", "x-csrf-token"])

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        # log the route TEMPLATE (e.g. /api/profiles/{profile_id}) - never query strings or bodies
        path = getattr(route, "path", "unmatched")
        log.info("request", extra={"event": "http", "request_id": rid, "path": f"{request.method} {path}",
                                   "status": response.status_code,
                                   "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
        response.headers["X-Request-ID"] = rid
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.error("unhandled_error", extra={"event": "error", "path": request.url.path}, exc_info=exc)
        return JSONResponse({"detail": "Something went wrong. Please try again."}, status_code=500)

    for r in (accounts_router, profiles_router, documents_router, trials_router, enrollment_router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/config")
    def public_config():
        s = get_settings()
        return {"app_name": s.app_name, "environment": s.environment, "synthetic_data_only": not s.allow_real_phi,
                "llm_available": s.llm_available, "trial_source": get_repository().status().__dict__}

    return app


app = create_app()

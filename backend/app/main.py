"""TeloraFooty backend application entrypoint.

Run with:
    cd backend
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import analysis, clips, events, games, health, jobs, videos
from app.config import settings
from app.core.errors import AppError, error_response
from app.core.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    logger.info("Storage ready at %s", settings.storage_path)
    # Seed demo games on first boot if none exist.
    if settings.enable_seed:
        try:
            from app.services.seed_service import seed_demo_games

            seed_demo_games()
        except Exception as exc:  # seeding must never block startup
            logger.warning("Demo seeding skipped: %s", exc)
    yield


app = FastAPI(title="TeloraFooty Backend", version="0.1.0", lifespan=lifespan)

# The Next.js frontend runs on a separate origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.info("AppError on %s: %s (%s)", request.url.path, exc.message, exc.code)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(exc.message, exc.code),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_response("Internal server error.", "INTERNAL_ERROR"),
    )


# API routes
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(videos.router, prefix="/api/videos", tags=["videos"])
app.include_router(games.router, prefix="/api/games", tags=["games"])
app.include_router(events.router, prefix="/api/games", tags=["events"])
app.include_router(clips.router, prefix="/api/clips", tags=["clips"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])

# Static media serving: /media/uploads/... and /media/clips/...
settings.ensure_dirs()
app.mount("/media", StaticFiles(directory=str(settings.storage_path)), name="media")

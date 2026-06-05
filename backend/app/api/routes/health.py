from __future__ import annotations

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness check used by the frontend and demo checklist."""
    return {"status": "ok", "service": settings.service_name}

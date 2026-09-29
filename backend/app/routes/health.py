"""GET /api/health - quick check that the API and the database are working."""

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import DbSession

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: DbSession) -> dict:
    db.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "status": "ok",
        "database": "ok",
        "llm_model": settings.llm_model,
        "llm_key_set": bool(settings.gemini_api_key),
    }

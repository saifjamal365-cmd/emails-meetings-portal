"""Connect / disconnect Google (Gmail + Calendar + Meet) with OAuth.

Flow: portal -> GET /api/auth/google/start -> Google login page -> Google calls
GET /api/auth/google/callback -> token saved (encrypted) -> back to the Settings page.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.db import DbSession
from app.services import google_client

router = APIRouter(prefix="/auth/google", tags=["auth"])


def _back_to_settings(**params: str) -> RedirectResponse:
    url = f"{get_settings().frontend_origin}/settings"
    return RedirectResponse(f"{url}?{urlencode(params)}" if params else url)


@router.get("/status")
def status(db: DbSession) -> dict:
    account = google_client.account(db)
    return {
        "configured": google_client.is_configured(),
        "connected": account is not None,
        "account": account[0] if account else None,
        # Not empty = the login is from an older version; click Connect again to allow more.
        "missing_scopes": google_client.missing_scopes(db),
    }


@router.get("/start")
def start() -> RedirectResponse:
    if not google_client.is_configured():
        raise HTTPException(
            400, "Google is not set up. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env."
        )
    return RedirectResponse(google_client.login_url())


@router.get("/callback")
def callback(db: DbSession, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    if error or not code:
        return _back_to_settings(google_error=error or "No code from Google.")
    try:
        account = google_client.finish_login(db, state, code)
    except Exception as e:
        return _back_to_settings(google_error=str(e))
    return _back_to_settings(google_connected=account)


@router.post("/disconnect")
def disconnect(db: DbSession) -> dict:
    google_client.disconnect(db)
    return {"connected": False}

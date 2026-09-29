"""Portal login: one owner, one password (PORTAL_PASSWORD in .env).

After login, a signed cookie keeps the user logged in (SESSION_DAYS). Every /api call except
the ones in PUBLIC_PATHS needs that cookie (see require_login in main.py).
"""

import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Paths anyone can call. The Google callback is safe: it only works with the one-time
# "state" made by /auth/google/start, which needs a login.
PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/me",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/google/callback",
}

MAX_FAILS = 5  # wrong passwords allowed ...
FAIL_WINDOW = 15 * 60  # ... in 15 minutes, per IP address
_fails: dict[str, deque[float]] = defaultdict(deque)


def is_logged_in(request: Request) -> bool:
    return not get_settings().login_required or request.session.get("user") == "owner"


class LoginBody(BaseModel):
    password: str


def _recent_fails(ip: str) -> deque[float]:
    fails = _fails[ip]
    while fails and fails[0] < time.monotonic() - FAIL_WINDOW:
        fails.popleft()
    return fails


@router.get("/me")
def me(request: Request) -> dict:
    return {"login_required": get_settings().login_required, "logged_in": is_logged_in(request)}


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict:
    settings = get_settings()
    if not settings.login_required:
        return {"logged_in": True}
    ip = request.client.host if request.client else "unknown"
    fails = _recent_fails(ip)
    if len(fails) >= MAX_FAILS:
        raise HTTPException(429, "Too many wrong passwords. Wait 15 minutes and try again.")
    if not hmac.compare_digest(body.password.encode(), settings.portal_password.encode()):
        fails.append(time.monotonic())
        raise HTTPException(401, "Wrong password.")
    fails.clear()
    request.session.clear()
    request.session["user"] = "owner"
    return {"logged_in": True}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"logged_in": False}

"""First-run setup: the portal password and the keys are typed on the Setup page, not in .env.

GET  /api/setup/status  which values are set (never the values themselves)
POST /api/setup         save the values in backend/.env and use them at once (no restart)

Before a portal password exists, the portal has no login (like before), so only this computer
may call it (the server listens on 127.0.0.1). After that, only the logged-in owner can.
"""

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import BACKEND_DIR, get_settings
from app.routes.auth import is_logged_in
from app.services import llm_client

router = APIRouter(prefix="/setup", tags=["setup"])

ENV_FILE = BACKEND_DIR / ".env"
EXAMPLE_FILE = BACKEND_DIR / ".env.example"

# Setup page field -> line in .env
FIELDS = {
    "portal_password": "PORTAL_PASSWORD",
    "gemini_api_key": "GEMINI_API_KEY",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
}
MIN_PASSWORD = 8
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


class SetupBody(BaseModel):
    # Empty = keep the saved value.
    portal_password: str = ""
    gemini_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""


def status() -> dict:
    s = get_settings()
    is_set = {field: bool(getattr(s, field)) for field in FIELDS}
    return {
        # The portal works without Google (emails can wait), but not without these two.
        "needs_setup": not (is_set["portal_password"] and is_set["gemini_api_key"]),
        "is_set": is_set,
        "redirect_uri": s.google_redirect_uri,
    }


@router.get("/status")
def get_status() -> dict:
    return status()


def _quote(value: str) -> str:
    """A .env value in single quotes: spaces, # and = stay part of the value."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def write_env(values: dict[str, str]) -> None:
    """Set these lines in .env and keep every other line (start from .env.example)."""
    if ENV_FILE.exists():
        text = ENV_FILE.read_text(encoding="utf-8")
    elif EXAMPLE_FILE.exists():
        text = EXAMPLE_FILE.read_text(encoding="utf-8")
    else:
        text = ""
    lines = text.splitlines()
    for name, value in values.items():
        line = f"{name}={_quote(value)}"
        pattern = re.compile(rf"^\s*{name}\s*=")
        for i, old in enumerate(lines):
            if pattern.match(old):
                lines[i] = line
                break
        else:
            lines.append(line)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check_request(request: Request) -> None:
    if not get_settings().login_required:
        # No password yet = no login: only this computer may set the first one.
        if (request.client.host if request.client else "") not in LOCAL_HOSTS:
            raise HTTPException(403, "The first setup can only be done on this computer.")
    elif not is_logged_in(request):
        raise HTTPException(401, "Please log in.")
    # Another website open in the browser must not be able to change the keys.
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Not allowed from another website.")


@router.post("")
def save(body: SetupBody, request: Request) -> dict:
    _check_request(request)
    settings = get_settings()
    values = {field: getattr(body, field).strip() for field in FIELDS}
    if any("\n" in v or "\r" in v for v in values.values()):
        raise HTTPException(400, "A value cannot have more than one line.")
    if not values["portal_password"] and not settings.portal_password:
        raise HTTPException(400, "Choose a portal password.")
    if values["portal_password"] and len(values["portal_password"]) < MIN_PASSWORD:
        raise HTTPException(400, f"The password needs at least {MIN_PASSWORD} characters.")

    changed = {field: v for field, v in values.items() if v}
    write_env({FIELDS[field]: v for field, v in changed.items()})
    for field, value in changed.items():  # use them now, without a restart
        setattr(settings, field, value)
    if "gemini_api_key" in changed:
        llm_client.reset_client()
    if "portal_password" in changed:
        request.session.clear()
        request.session["user"] = "owner"  # the person who chose it stays logged in
    return status()

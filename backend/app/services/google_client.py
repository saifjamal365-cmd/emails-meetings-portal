"""Google login (OAuth), shared by Gmail, Calendar and Meet.

One login gives the portal these permissions. The token is saved encrypted in the
oauth_tokens table (see services/crypto.py).
"""

import json
import os
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import OAuthToken
from app.services.crypto import decrypt, encrypt

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    # Gmail: read emails + change labels (mark read, archive), and send replies.
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    # Meetings: find finished meetings in the calendar, read Meet transcripts.
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/meetings.space.readonly",
]

if get_settings().google_redirect_uri.startswith("http://localhost"):
    # Allow OAuth over http on localhost only (Google needs https everywhere else).
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


class GoogleNotConnected(Exception):
    """Google is not connected yet, or the saved login no longer works."""


# state -> PKCE code verifier, kept between /start and /callback (one user, local app).
_pending_logins: dict[str, str] = {}


def is_configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


def _flow(state: str | None = None, code_verifier: str | None = None) -> Flow:
    s = get_settings()
    client_config = {
        "web": {
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [s.google_redirect_uri],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=s.google_redirect_uri,
        state=state,
        code_verifier=code_verifier,
    )


def login_url() -> str:
    """The Google page where the user allows the portal to use Gmail, Calendar and Meet."""
    flow = _flow()
    url, state = flow.authorization_url(prompt="consent", include_granted_scopes="true")
    _pending_logins[state] = flow.code_verifier or ""
    return url


def _row(db: Session) -> OAuthToken | None:
    return db.scalar(select(OAuthToken).where(OAuthToken.provider == "google"))


def finish_login(db: Session, state: str, code: str) -> str:
    """Exchange the code from Google for a token, save it encrypted. Returns the account email."""
    verifier = _pending_logins.pop(state, None)
    if verifier is None:
        raise GoogleNotConnected("Login expired or not started here. Please click Connect again.")
    flow = _flow(state=state, code_verifier=verifier)
    token = flow.fetch_token(code=code)
    creds = flow.credentials

    oauth2 = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    info = oauth2.userinfo().get().execute()

    row = _row(db)
    if row is None:
        row = OAuthToken(provider="google", token_encrypted="")
        db.add(row)
    row.account_email = info.get("email", "")
    row.account_name = info.get("name", "")
    # What the user really allowed (they can untick permissions on the Google page).
    granted = token.get("scope", "")
    row.scopes = granted.split() if isinstance(granted, str) else list(granted)
    row.token_encrypted = encrypt(creds.to_json())
    row.connected_at = datetime.now()
    db.commit()
    return row.account_email


def account(db: Session) -> tuple[str, str] | None:
    """(email, name) of the connected Google account, or None."""
    row = _row(db)
    return (row.account_email, row.account_name) if row else None


def missing_scopes(db: Session) -> list[str]:
    """Permissions this version needs that the saved login does not have (-> reconnect)."""
    row = _row(db)
    if row is None:
        return []
    granted = set(row.scopes or [])
    return [s for s in SCOPES if s.startswith("https://") and s not in granted]


def disconnect(db: Session) -> None:
    row = _row(db)
    if row:
        db.delete(row)
        db.commit()


def credentials(db: Session) -> Credentials:
    row = _row(db)
    if row is None:
        raise GoogleNotConnected("Google is not connected. Open Settings and click Connect Google.")
    creds = Credentials.from_authorized_user_info(json.loads(decrypt(row.token_encrypted)))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:  # revoked or expired refresh token
                raise GoogleNotConnected(
                    "Google login expired. Please connect Google again."
                ) from e
            row.token_encrypted = encrypt(creds.to_json())
            db.commit()
        else:
            raise GoogleNotConnected("Google login expired. Please connect Google again.")
    return creds


def service(db: Session, name: str, version: str):
    """A Google API client, e.g. service(db, "gmail", "v1")."""
    return build(name, version, credentials=credentials(db), cache_discovery=False)

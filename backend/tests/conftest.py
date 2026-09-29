"""Test setup: a separate temporary database, no background jobs, no real API keys."""

import os
import tempfile
from pathlib import Path

# Must be set before the app is imported (settings are read once).
_tmp = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["EMAIL_SYNC_MINUTES"] = "0"
os.environ["MEETING_SYNC_MINUTES"] = "0"
os.environ["RECORDER_CHECK_SECONDS"] = "0"
os.environ["KEEP_RECORDINGS"] = "false"
os.environ["MORNING_PLAN_HOUR"] = "-1"
os.environ["EVENING_SUMMARY_HOUR"] = "-1"
os.environ["GEMINI_API_KEY"] = ""
os.environ["LLM_MIN_SECONDS_BETWEEN_CALLS"] = "0"
os.environ["PORTAL_PASSWORD"] = ""  # login is tested in test_security.py
os.environ["DATA_DIR"] = _tmp.as_posix()
os.environ["TOKEN_ENCRYPTION_KEY"] = "q9R1bm8m2m0qVJ8yZ3k3o1x6kQ8Yb2cQy7m4w9nY5aU="

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts with empty tables."""
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

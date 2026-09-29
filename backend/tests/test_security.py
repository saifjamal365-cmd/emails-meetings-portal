"""Login, security headers, "Delete my data", notifications and serving the built portal."""

from datetime import datetime

import pytest

from app import main
from app.agents import email_agent
from app.config import get_settings
from app.models import Email, Notification, Task
from app.routes import auth
from app.services import mail_client


@pytest.fixture
def password(monkeypatch):
    """Turn the login on for one test."""
    monkeypatch.setattr(get_settings(), "portal_password", "correct horse")
    auth._fails.clear()
    yield "correct horse"
    auth._fails.clear()


# ---- Login ---------------------------------------------------------------------------


def test_api_needs_login_when_a_password_is_set(client, password) -> None:
    assert client.get("/api/emails").status_code == 401
    assert client.get("/api/health").status_code == 200  # public
    assert client.get("/api/auth/me").json() == {"login_required": True, "logged_in": False}

    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": password}).status_code == 200

    assert client.get("/api/emails").status_code == 200  # the cookie works
    assert client.get("/api/auth/me").json()["logged_in"] is True

    client.post("/api/auth/logout")
    assert client.get("/api/emails").status_code == 401


def test_too_many_wrong_passwords_are_blocked(client, password) -> None:
    for _ in range(auth.MAX_FAILS):
        assert client.post("/api/auth/login", json={"password": "guess"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": password})
    assert r.status_code == 429  # blocked, even with the right password


def test_no_password_means_no_login_in_development(client) -> None:
    assert client.get("/api/auth/me").json() == {"login_required": False, "logged_in": True}
    assert client.get("/api/emails").status_code == 200


def test_google_callback_is_public_but_needs_a_real_login_state(client, password) -> None:
    r = client.get("/api/auth/google/callback?state=made-up&code=x", follow_redirects=False)
    assert r.status_code == 307
    assert "google_error" in r.headers["location"]


def test_security_headers(client) -> None:
    headers = client.get("/api/health").headers
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


# ---- Delete my data ------------------------------------------------------------------


def test_delete_my_data(client, db) -> None:
    db.add(Task(title="Something"))
    db.add(Notification(kind="plan", title="Plan ready"))
    db.commit()

    assert client.request("DELETE", "/api/data", json={"confirm": "yes"}).status_code == 400
    r = client.request("DELETE", "/api/data", json={"confirm": "DELETE"})

    assert r.status_code == 200
    assert r.json()["deleted"]["tasks"] == 1
    assert db.query(Task).count() == 0
    assert client.get("/api/settings").status_code == 200  # settings are kept


# ---- Notifications -------------------------------------------------------------------


def test_sync_with_new_high_emails_makes_one_notification(client, db, monkeypatch) -> None:
    from tests.test_email_agent import fake_llm

    fetched = [
        mail_client.FetchedEmail(
            provider_id=f"g{i}",
            thread_id="t",
            message_id_header="",
            sender=f"c{i}@client.com",
            sender_name="Client",
            subject="Order",
            body="Hi",
            received_at=datetime.now(),
        )
        for i in range(2)
    ]
    monkeypatch.setattr(mail_client, "fetch_unread", lambda db, max_results: fetched)
    monkeypatch.setattr(email_agent, "ask_json", fake_llm())

    email_agent.sync(db)
    email_agent.sync(db)  # nothing new the second time

    body = client.get("/api/notifications").json()
    assert body["unread"] == 1
    assert body["items"][0]["title"] == "2 new High emails"
    assert body["items"][0]["link"] == "/high"

    client.post("/api/notifications/read-all")
    assert client.get("/api/notifications").json()["unread"] == 0


def test_same_unread_problem_is_not_repeated(db) -> None:
    from app.services.notify import notify

    notify(db, "problem", "Google login expired")
    notify(db, "problem", "Google login expired")
    db.commit()
    assert db.query(Notification).count() == 1


# ---- Serving the built portal --------------------------------------------------------


def test_portal_files_and_page_fallback(client, tmp_path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>portal</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("do not show")
    monkeypatch.setattr(main, "FRONTEND_DIST", dist)

    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/meetings").text == "<html>portal</html>"  # React shows the page
    assert "do not show" not in client.get("/..%2Fsecret.txt").text  # no files outside dist
    assert client.get("/api/not-a-route").status_code == 404


def test_unknown_email_still_404_with_login_off(client, db) -> None:
    db.add(
        Email(
            provider_id="x",
            sender="a@b.com",
            sender_domain="b.com",
            subject="s",
            body="",
            received_at=datetime.now(),
        )
    )
    db.commit()
    assert client.get("/api/emails/999").status_code == 404

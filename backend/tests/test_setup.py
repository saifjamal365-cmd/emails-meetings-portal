"""The Setup page: the password and keys are saved in .env and work at once."""

import pytest

from app.config import Settings, get_settings
from app.routes import auth, setup
from app.services import llm_client


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temporary .env, and the settings put back after the test."""
    monkeypatch.setattr(setup, "ENV_FILE", tmp_path / ".env")
    example = tmp_path / ".env.example"
    example.write_text(
        "# keys\nGEMINI_API_KEY=\nPORTAL_PASSWORD=\nFRONTEND_ORIGIN=http://localhost:8000\n"
    )
    monkeypatch.setattr(setup, "EXAMPLE_FILE", example)
    for field, name in setup.FIELDS.items():
        monkeypatch.setattr(get_settings(), field, "")
        monkeypatch.delenv(name, raising=False)  # so Settings(_env_file=...) reads the file
    auth._fails.clear()
    yield tmp_path / ".env"
    auth._fails.clear()


def test_first_run_needs_setup(client, env) -> None:
    body = client.get("/api/setup/status").json()
    assert body["needs_setup"] is True
    assert body["is_set"] == dict.fromkeys(setup.FIELDS, False)
    assert body["redirect_uri"].endswith("/api/auth/google/callback")


def test_saving_writes_env_and_works_without_a_restart(client, env, monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "_client", object())  # a client made with the old key
    response = client.post(
        "/api/setup",
        json={
            "portal_password": "my password 1",
            "gemini_api_key": "gem-key",
            "google_client_id": "id-1",
        },
    )
    assert response.status_code == 200
    assert response.json()["needs_setup"] is False
    assert response.json()["is_set"]["google_client_secret"] is False

    settings = get_settings()
    assert (settings.portal_password, settings.gemini_api_key) == ("my password 1", "gem-key")
    assert llm_client._client is None  # the next call uses the new key

    text = env.read_text(encoding="utf-8")
    assert "# keys" in text and "FRONTEND_ORIGIN=http://localhost:8000" in text  # kept
    assert text.count("GEMINI_API_KEY=") == 1 and "GOOGLE_CLIENT_ID='id-1'" in text

    # The person who chose the password stays logged in.
    assert client.get("/api/auth/me").json() == {"login_required": True, "logged_in": True}


def test_values_with_quotes_and_spaces_survive_the_env_file(client, env) -> None:
    password = 'it\'s a #pass = \\ with "quotes" وكلمة'
    assert client.post("/api/setup", json={"portal_password": password}).status_code == 200
    assert Settings(_env_file=env).portal_password == password


def test_empty_fields_keep_the_saved_values(client, env) -> None:
    client.post("/api/setup", json={"portal_password": "first-pass", "gemini_api_key": "key-1"})
    client.post("/api/setup", json={"gemini_api_key": "key-2"})
    saved = Settings(_env_file=env)
    assert (saved.portal_password, saved.gemini_api_key) == ("first-pass", "key-2")


def test_bad_values_are_refused(client, env) -> None:
    assert client.post("/api/setup", json={"gemini_api_key": "k"}).status_code == 400  # no password
    assert client.post("/api/setup", json={"portal_password": "short"}).status_code == 400
    two_lines = {"portal_password": "long enough", "gemini_api_key": "a\nEVIL=1"}
    assert client.post("/api/setup", json=two_lines).status_code == 400
    assert not env.exists()


def test_after_setup_only_the_owner_can_change_the_keys(client, env) -> None:
    client.post("/api/setup", json={"portal_password": "owner-pass"})
    client.post("/api/auth/logout")
    assert client.post("/api/setup", json={"gemini_api_key": "stolen"}).status_code == 401
    assert get_settings().gemini_api_key == ""

    client.post("/api/auth/login", json={"password": "owner-pass"})
    assert client.post("/api/setup", json={"gemini_api_key": "mine"}).status_code == 200


def test_another_website_cannot_save(client, env) -> None:
    response = client.post(
        "/api/setup",
        json={"portal_password": "evil-pass"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert get_settings().portal_password == ""

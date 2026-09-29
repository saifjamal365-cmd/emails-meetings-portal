"""Basic API tests. The LLM call is replaced with a fake, so no API key is needed."""

from app.routes import llm
from app.services.llm_client import LLMError, LLMResult


def test_health(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_llm_test_returns_reply(client, monkeypatch) -> None:
    fake = LLMResult(text="Hello! مرحبا!", model="fake-model", input_tokens=5, output_tokens=4)
    monkeypatch.setattr(llm, "ask", lambda *args, **kwargs: fake)
    response = client.post("/api/llm/test", json={"message": "hi"})
    assert response.status_code == 200
    assert response.json()["reply"] == "Hello! مرحبا!"


def test_llm_test_shows_clear_error(client, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise LLMError("GEMINI_API_KEY is not set. Add it to backend/.env.")

    monkeypatch.setattr(llm, "ask", fail)
    response = client.post("/api/llm/test", json={})
    assert response.status_code == 502
    assert "GEMINI_API_KEY" in response.json()["detail"]

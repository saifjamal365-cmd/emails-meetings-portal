"""The Gemini client, with a fake Google client (no API key, no internet)."""

from types import SimpleNamespace

import pytest
from google.genai import errors

from app.agents.meeting_agent import MeetingOutput
from app.services import llm_client
from app.services.llm_client import LLMError, ask, ask_json, json_schema


class FakeModels:
    def __init__(self, text=None, error=None, finish="STOP"):
        self.text, self.error, self.finish, self.calls = text, error, finish, []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return SimpleNamespace(
            text=self.text,
            candidates=[SimpleNamespace(finish_reason=self.finish)],
            usage_metadata=SimpleNamespace(
                prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5
            ),
        )


@pytest.fixture
def fake(monkeypatch):
    def use(**kwargs) -> FakeModels:
        models = FakeModels(**kwargs)
        monkeypatch.setattr(llm_client, "_client", SimpleNamespace(models=models))
        return models

    return use


def test_schema_has_no_refs_and_keeps_enums() -> None:
    schema = json_schema(MeetingOutput)
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text
    item = schema["properties"]["action_items"]["items"]
    assert set(item["properties"]) == {"task", "owner", "owner_is_me", "due"}
    assert schema["properties"]["detected_language"]["enum"] == ["ar", "en", "mixed"]


def test_ask_returns_text_and_tokens(fake) -> None:
    models = fake(text="مرحبا")
    result = ask("hi", system="Be short.")
    assert result.text == "مرحبا"
    assert (result.input_tokens, result.output_tokens) == (100, 25)
    assert models.calls[0]["config"].system_instruction == "Be short."


def test_ask_json_parses_and_sends_the_schema(fake) -> None:
    models = fake(
        text='{"overview": "ok", "detected_language": "en", "action_items": [], '
        '"decisions": [], "risks": [], "blockers": [], "keywords": ["ACME"]}'
    )
    result = ask_json("summarize", MeetingOutput)
    assert result.data.keywords == ["ACME"]
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert "properties" in config.response_json_schema


def test_bad_json_gives_a_clear_error(fake) -> None:
    fake(text='{"overview": "missing fields"}')
    with pytest.raises(LLMError, match="valid JSON"):
        ask_json("summarize", MeetingOutput)


def test_free_limit_reached(fake, monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "_used_up_today", {})
    fake(
        error=errors.ClientError(
            429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
        )
    )
    with pytest.raises(LLMError, match="free Gemini limit"):
        ask("hi")


def test_blocked_or_empty_answer(fake) -> None:
    fake(text=None, finish="SAFETY")
    with pytest.raises(LLMError, match="no answer"):
        ask("hi")


def test_cut_answer(fake) -> None:
    fake(text="half an answ", finish="MAX_TOKENS")
    with pytest.raises(LLMError, match="too long"):
        ask("hi")


def test_missing_key(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "_client", None)
    with pytest.raises(LLMError, match="GEMINI_API_KEY is not set"):
        ask("hi")


class BusyThenOk(FakeModels):
    """The main model is full (503), the backup answers."""

    def generate_content(self, model, contents, config):
        if model == "gemini-3.1-flash-lite":
            self.calls.append({"model": model})
            raise errors.ServerError(
                503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}}
            )
        return super().generate_content(model, contents, config)


def test_busy_model_uses_the_backup(monkeypatch) -> None:
    models = BusyThenOk(text="hi")
    monkeypatch.setattr(llm_client, "_client", SimpleNamespace(models=models))
    result = ask("hi")
    assert [c["model"] for c in models.calls] == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
    assert result.model == "gemini-3.5-flash-lite"


def test_all_models_busy(fake) -> None:
    fake(
        error=errors.ServerError(
            503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}}
        )
    )
    with pytest.raises(LLMError, match="busy"):
        ask("hi")


class DailyLimitOnMain(FakeModels):
    """The main model used its free daily limit (429 PerDay)."""

    def generate_content(self, model, contents, config):
        if model == "gemini-3.1-flash-lite":
            self.calls.append({"model": model})
            raise errors.ClientError(
                429,
                {
                    "error": {
                        "message": "quota",
                        "details": [
                            {
                                "violations": [
                                    {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                                ]
                            }
                        ],
                    }
                },
            )
        return super().generate_content(model, contents, config)


def test_daily_limit_moves_to_backup_and_skips_the_model_today(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "_used_up_today", {})
    models = DailyLimitOnMain(text="hi")
    monkeypatch.setattr(llm_client, "_client", SimpleNamespace(models=models))

    assert ask("one").model == "gemini-3.5-flash-lite"
    assert ask("two").model == "gemini-3.5-flash-lite"

    tried = [c["model"] for c in models.calls]
    assert tried.count("gemini-3.1-flash-lite") == 1  # not tried again today

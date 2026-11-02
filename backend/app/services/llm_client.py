"""All LLM calls go through this file, so model, errors, limits and logging live in one place.

The LLM is Google Gemini (free tier, key from https://aistudio.google.com/apikey).
Free tier limits: calls are spaced out (LLM_MIN_SECONDS_BETWEEN_CALLS) so the agents stay
under the requests-per-minute limit. If the daily limit is reached, the agents stop and try
again at the next check. Free models are often busy (503): then the call goes to the backup
models (LLM_FALLBACK_MODELS).
"""

import copy
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.config import get_settings

Effort = Literal["low", "medium", "high"]  # kept for the callers; Gemini decides by itself


class LLMError(Exception):
    """A clear, user-facing error from the LLM layer."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class LLMJsonResult[T: BaseModel]:
    data: T
    model: str
    input_tokens: int
    output_tokens: int


_client: genai.Client | None = None
_rate_lock = threading.Lock()
_last_call = 0.0


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set. Add it to backend/.env.")
        # Free models are often busy for a few seconds (503): try again after 2, 4 and 8 seconds.
        # 429 (limit reached) is not retried here - _call() moves to the next model instead.
        # A time limit stops a call from hanging for minutes.
        retry = types.HttpRetryOptions(
            attempts=4, initial_delay=2, max_delay=10, http_status_codes=[408, 500, 502, 503, 504]
        )
        options = types.HttpOptions(timeout=120_000, retry_options=retry)
        _client = genai.Client(api_key=settings.gemini_api_key, http_options=options)
    return _client


def reset_client() -> None:
    """Forget the client, so the next call uses the new key (saved on the Setup page)."""
    global _client
    _client = None


def _wait_for_rate_limit() -> None:
    """Keep a small gap between calls (the free tier allows only a few calls per minute)."""
    global _last_call
    gap = get_settings().llm_min_seconds_between_calls
    with _rate_lock:
        wait = _last_call + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


# model -> the day its free daily limit was reached (skip it until tomorrow)
_used_up_today: dict[str, date] = {}


class _Busy(Exception):
    """The model is overloaded or too slow right now (503 / 504 / timeout)."""


class _LimitReached(Exception):
    """The model's free limit is reached (429)."""


def _generate(model: str, prompt: str, config: types.GenerateContentConfig) -> Any:
    _wait_for_rate_limit()
    try:
        return _get_client().models.generate_content(model=model, contents=prompt, config=config)
    except errors.ClientError as e:
        if e.code == 429:
            # The quota name ("...PerDay...FreeTier") is in the error details, not the message.
            if "PerDay" in f"{e} {e.details}":
                _used_up_today[model] = date.today()
            raise _LimitReached(model) from e
        if e.code in (401, 403) or "API key" in str(e):
            raise LLMError("The Gemini API key is not valid.") from e
        raise LLMError(f"Gemini API error ({e.code}): {e.message}") from e
    except errors.ServerError as e:
        raise _Busy(model) from e
    except errors.APIError as e:
        raise LLMError(f"Gemini API error: {e}") from e
    except httpx.TimeoutException as e:
        raise _Busy(model) from e
    except (OSError, httpx.HTTPError) as e:  # network problems
        raise LLMError("Cannot reach the Gemini API. Check the internet connection.") from e


def _models(preferred: str | None = None) -> list[str]:
    """The preferred model (if any), the main model, then the backups.

    Each free model has its own daily limit, so trying them in turn gives more free calls.
    """
    settings = get_settings()
    names = [preferred or "", settings.llm_model, *settings.llm_fallback_models.split(",")]
    result = []
    for name in (n.strip() for n in names):
        if name and name not in result and _used_up_today.get(name) != date.today():
            result.append(name)
    return result


def _call(
    prompt: str, config: types.GenerateContentConfig, model: str | None = None
) -> tuple[Any, str]:
    """Call the main model; if it is busy or its free limit is reached, the next backup model.

    Returns (response, the model that answered).
    """
    response, used, busy = None, "", False
    for name in _models(model):
        try:
            response, used = _generate(name, prompt, config), name
            break
        except _Busy:
            busy = True
        except _LimitReached:
            pass
    if response is None:
        if busy:
            raise LLMError(
                "The free Gemini models are busy right now (high demand). Try again soon."
            )
        raise LLMError(
            "The free Gemini limit is reached for now. The agents try again at the next check."
        )

    candidate = response.candidates[0] if response.candidates else None
    reason = str(candidate.finish_reason) if candidate and candidate.finish_reason else ""
    if "MAX_TOKENS" in reason:
        raise LLMError("The LLM answer was too long and was cut. Try again.")
    if not response.text:
        raise LLMError("Gemini gave no answer (it may have been blocked by a safety filter).")
    return response, used


MIN_OUTPUT_TOKENS = 8192  # Gemini's thinking uses output tokens too; small limits cut answers


def _config(system: str | None, max_tokens: int | None) -> dict:
    return {
        "system_instruction": system,
        "max_output_tokens": max(max_tokens or get_settings().llm_max_tokens, MIN_OUTPUT_TOKENS),
    }


def _usage(response: Any) -> tuple[int, int]:
    usage = response.usage_metadata
    if usage is None:
        return 0, 0
    output = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    return usage.prompt_token_count or 0, output


def ask(
    prompt: str,
    system: str | None = None,
    max_tokens: int | None = None,
    effort: Effort | None = None,
) -> LLMResult:
    """Send one message to Gemini and return the text answer."""
    response, model = _call(prompt, types.GenerateContentConfig(**_config(system, max_tokens)))
    tokens_in, tokens_out = _usage(response)
    return LLMResult(
        text=response.text,
        model=model,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
    )


def json_schema(model: type[BaseModel]) -> dict:
    """The Pydantic model as plain JSON Schema, with nested models written inline (no $ref)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: inline(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    return inline(schema)


def ask_json[T: BaseModel](
    prompt: str,
    schema: type[T],
    system: str | None = None,
    max_tokens: int | None = None,
    effort: Effort | None = None,
    model: str | None = None,
) -> LLMJsonResult[T]:
    """Send one message and get back a validated object of type `schema` (structured output).

    `model` = try this model first (then the normal chain).
    """
    config = types.GenerateContentConfig(
        **_config(system, max_tokens),
        response_mime_type="application/json",
        response_json_schema=json_schema(schema),
    )
    response, used = _call(prompt, config, model)
    try:
        data = schema.model_validate_json(response.text)
    except ValidationError as e:
        raise LLMError("Gemini did not return valid JSON. Try again.") from e
    tokens_in, tokens_out = _usage(response)
    return LLMJsonResult(
        data=data,
        model=used,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
    )

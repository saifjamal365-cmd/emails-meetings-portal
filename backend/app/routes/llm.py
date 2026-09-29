"""POST /api/llm/test - Phase 1 goal: the portal shows a reply from the LLM."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import DbSession
from app.models import ActivityLog
from app.services.llm_client import LLMError, ask

router = APIRouter(prefix="/llm", tags=["llm"])


class TestRequest(BaseModel):
    message: str = Field(default="Say hello in English and in Arabic, in one short line each.")


class TestResponse(BaseModel):
    reply: str
    model: str
    input_tokens: int
    output_tokens: int


@router.post("/test", response_model=TestResponse)
def llm_test(body: TestRequest, db: DbSession) -> TestResponse:
    try:
        result = ask(body.message, max_tokens=1000)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    db.add(
        ActivityLog(
            agent="system",
            action="llm_test",
            details={
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
    )
    db.commit()
    return TestResponse(
        reply=result.text,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )

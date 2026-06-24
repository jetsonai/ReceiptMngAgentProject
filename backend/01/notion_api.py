from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from env_loader import load_project_env
from env_healthcheck import check_notion, check_openai
from notion_config import load_runtime_config
from notion_constants import STATUS_PENDING
from notion_record_agent import ExpenseRecord, record_expense_to_notion

load_project_env()

app = FastAPI(title="Notion Record Health API", version="1.0.0")


class KeyHealthResponse(BaseModel):
    ok: bool
    env_path: str | None = None
    openai: dict[str, Any]
    notion: dict[str, Any]


class NotionWriteResponse(BaseModel):
    ok: bool
    skipped: bool = False
    page_id: str | None = None
    page_url: str | None = None
    title: str = ""
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


def _sample_record() -> ExpenseRecord:
    return ExpenseRecord(
        id="EXP-TEST-0001",
        user_id="api-test",
        amount=12500,
        category="식비",
        payment_method="신용카드",
        merchant="편의점",
        memo="FastAPI 테스트 기록",
        source="api",
        budget_status="미평가",
        notion_sync_status=STATUS_PENDING,
        addr="서울시 강남구",
        tell="02-000-0000",
    )


@app.get("/health/keys", response_model=KeyHealthResponse)
def health_keys() -> KeyHealthResponse:
    config = load_runtime_config()
    env_path = load_project_env()

    openai_result: dict[str, Any]
    notion_result: dict[str, Any]

    if config.openai_api_key:
        ok, message = check_openai(config.openai_api_key)
        openai_result = {"present": True, "ok": ok, "message": message}
    else:
        openai_result = {"present": False, "ok": False, "message": "OPENAI_API_KEY가 없습니다."}

    if config.notion_token:
        ok, message = check_notion(config.notion_token)
        notion_result = {"present": True, "ok": ok, "message": message}
    else:
        notion_result = {"present": False, "ok": False, "message": "NOTION_TOKEN이 없습니다."}

    return KeyHealthResponse(
        ok=bool(openai_result["ok"]) and bool(notion_result["ok"]),
        env_path=str(env_path) if env_path else None,
        openai=openai_result,
        notion=notion_result,
    )


@app.post("/notion/test-record", response_model=NotionWriteResponse)
def notion_test_record(record: ExpenseRecord | None = None) -> NotionWriteResponse:
    config = load_runtime_config()
    if not config.notion_database_id:
        raise HTTPException(
            status_code=400,
            detail="NOTION_DATABASE_URL 또는 NOTION_DATABASE_ID가 없어 실제 Notion 기록을 할 수 없습니다.",
        )

    result = record_expense_to_notion(record or _sample_record())
    return NotionWriteResponse(**result.model_dump())

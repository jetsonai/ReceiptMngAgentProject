from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from env_loader import load_project_env
from env_healthcheck import check_notion, check_openai
from notion_config import load_runtime_config
from notion_constants import PAYMENT_METHOD_CARD, STATUS_PENDING
from notion_record_agent import ExpenseRecord, record_expense_to_notion

load_project_env()

app = FastAPI(title="Notion Record Health API", version="1.0.0")


class KeyHealthResponse(BaseModel):
    # /health/keys 응답: 키 존재 여부와 실제 API 인증 결과를 함께 반환한다.
    ok: bool
    env_path: str | None = None
    openai: dict[str, Any]
    notion: dict[str, Any]


class NotionWriteResponse(BaseModel):
    # /notion/test-record 응답: Notion 생성 결과와 실제 전송 payload를 확인용으로 반환한다.
    ok: bool
    skipped: bool = False
    page_id: str | None = None
    page_url: str | None = None
    title: str = ""
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


def _sample_record() -> ExpenseRecord:
    # Swagger 데모에서 요청 본문 없이 바로 실행할 수 있는 샘플 지출 데이터.
    return ExpenseRecord(
        id="EXP-TEST-0001",
        user_id="api-test",
        amount=12500,
        category="식비",
        payment_method=PAYMENT_METHOD_CARD,
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
    # OpenAI/Notion 키가 있는지와 실제 인증되는지를 한 번에 점검한다.
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
    # 요청 body가 있으면 그 값으로, 없으면 샘플 값으로 Notion 기록을 테스트한다.
    config = load_runtime_config()
    if not config.notion_database_id:
        raise HTTPException(
            status_code=400,
            detail="NOTION_DATABASE_URL 또는 NOTION_DATABASE_ID가 없어 실제 Notion 기록을 할 수 없습니다.",
        )

    result = record_expense_to_notion(record or _sample_record())
    return NotionWriteResponse(**result.model_dump())

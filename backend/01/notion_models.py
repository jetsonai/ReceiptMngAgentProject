from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional, TypedDict

from pydantic import BaseModel, Field


class ExpenseRecord(BaseModel):
    # 앞 단계(OCR/분석/예산평가)에서 넘어오는 지출 1건의 표준 입력 모델.
    id: str
    user_id: str
    spent_at: date = Field(default_factory=date.today)
    amount: float = Field(ge=0)
    category: str
    payment_method: str = "미확인"
    merchant: str = ""
    memo: str = ""
    source: str = ""
    budget_status: str = "미평가"
    notion_sync_status: str = "대기"
    addr: str = ""
    tell: str = ""
    reg_date: datetime = Field(default_factory=datetime.now)


class NotionWriteResult(BaseModel):
    # Notion 기록 결과를 API, CLI, LangGraph가 같은 형태로 다루기 위한 모델.
    ok: bool
    skipped: bool = False
    page_id: Optional[str] = None
    page_url: Optional[str] = None
    title: str = ""
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class NotionGraphState(TypedDict, total=False):
    # LangGraph 노드들이 record -> payload -> result 순서로 채워 넣는 공유 상태.
    record: ExpenseRecord
    title: str
    body: str
    payload: dict[str, Any]
    result: NotionWriteResult

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional, TypedDict

from pydantic import BaseModel, Field


class ExpenseRecord(BaseModel):
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
    ok: bool
    skipped: bool = False
    page_id: Optional[str] = None
    page_url: Optional[str] = None
    title: str = ""
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class NotionGraphState(TypedDict, total=False):
    record: ExpenseRecord
    title: str
    body: str
    payload: dict[str, Any]
    result: NotionWriteResult

from __future__ import annotations

from notion_config import load_runtime_config
from notion_constants import (
    PROPERTY_ADDRESS,
    PROPERTY_AMOUNT,
    PROPERTY_BUDGET_STATUS,
    PROPERTY_CATEGORY,
    PROPERTY_MERCHANT,
    PROPERTY_NOTION_SYNC_STATUS,
    PROPERTY_OCR_SUMMARY,
    PROPERTY_PAYMENT_METHOD,
    PROPERTY_RECORD_ID,
    PROPERTY_REG_DATE,
    PROPERTY_SOURCE,
    PROPERTY_SPENT_AT,
    PROPERTY_PHONE,
    PROPERTY_OCR_TEXT,
    CATEGORY_ETC,
    CATEGORY_OPTIONS,
    PAYMENT_METHOD_CARD,
    PAYMENT_METHOD_CASH_RECEIPT,
)
from notion_models import NotionGraphState
from notion_text import build_notion_body, build_title


def normalize_payment_method(value: str) -> str:
    # 기존 입력값이 들어와도 Notion DB의 새 select 옵션명으로 맞춘다.
    cleaned_value = value.strip()
    payment_method_map = {
        "카드": PAYMENT_METHOD_CARD,
        "신용카드": PAYMENT_METHOD_CARD,
        "신영카드": PAYMENT_METHOD_CARD,
        "현금": PAYMENT_METHOD_CASH_RECEIPT,
        "현금영수증": PAYMENT_METHOD_CASH_RECEIPT,
        "기타": PAYMENT_METHOD_CASH_RECEIPT,
        "미확인": PAYMENT_METHOD_CASH_RECEIPT,
        "": PAYMENT_METHOD_CASH_RECEIPT,
    }
    return payment_method_map.get(cleaned_value, cleaned_value)


def normalize_category(value: str) -> str:
    # Notion DB에 없는 예전 카테고리명은 기타로 모아 select 오류를 피한다.
    cleaned_value = value.strip()
    return cleaned_value if cleaned_value in CATEGORY_OPTIONS else CATEGORY_ETC


def build_notion_payload(state: NotionGraphState) -> NotionGraphState:
    # LangGraph의 prepare 단계: ExpenseRecord를 Notion pages API payload로 변환한다.
    record = state["record"]
    config = load_runtime_config()
    title = build_title(record)
    body = build_notion_body(record)
    payment_method = normalize_payment_method(record.payment_method)
    category = normalize_category(record.category)
    payload = {
        # database_id는 write 단계에서 최종 보정하지만, dry-run에서도 구조가 보이게 넣어둔다.
        "parent": {"database_id": config.notion_database_id or ""},
        "properties": {
            # 아래 property key는 Notion DB의 실제 속성명과 정확히 일치해야 한다.
            PROPERTY_RECORD_ID: {"title": [{"text": {"content": record.id}}]},
            PROPERTY_SPENT_AT: {"date": {"start": record.spent_at.isoformat()}},
            PROPERTY_MERCHANT: {"rich_text": [{"text": {"content": record.merchant}}]},
            PROPERTY_AMOUNT: {"number": record.amount},
            PROPERTY_PAYMENT_METHOD: {"select": {"name": payment_method}},
            PROPERTY_CATEGORY: {"select": {"name": category}},
            PROPERTY_SOURCE: {"rich_text": [{"text": {"content": record.source}}]},
            PROPERTY_BUDGET_STATUS: {"multi_select": [{"name": record.budget_status}]},
            PROPERTY_NOTION_SYNC_STATUS: {"multi_select": [{"name": record.notion_sync_status}]},
            PROPERTY_ADDRESS: {"rich_text": [{"text": {"content": record.addr}}]},
            PROPERTY_PHONE: {"rich_text": [{"text": {"content": record.tell}}]},
            PROPERTY_REG_DATE: {"rich_text": [{"text": {"content": record.reg_date.isoformat()}}]},
            PROPERTY_OCR_TEXT: {
                "rich_text": [{"text": {"content": f"{record.category} / {record.amount:,.0f}원 / {record.merchant or '미기재'} / {record.memo or '메모 없음'}"}}]
            },
            PROPERTY_OCR_SUMMARY: {"rich_text": [{"text": {"content": record.memo or '메모 없음'}}]},
        },
        "children": [
            # 페이지 본문에는 사람이 읽기 쉬운 요약 문장을 paragraph block으로 저장한다.
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": body}}],
                },
            }
        ],
    }
    return {**state, "title": title, "body": body, "payload": payload}

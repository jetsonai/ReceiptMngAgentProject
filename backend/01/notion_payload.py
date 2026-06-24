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
)
from notion_models import NotionGraphState
from notion_text import build_notion_body, build_title


def build_notion_payload(state: NotionGraphState) -> NotionGraphState:
    record = state["record"]
    config = load_runtime_config()
    title = build_title(record)
    body = build_notion_body(record)
    payload = {
        "parent": {"database_id": config.notion_database_id or ""},
        "properties": {
            PROPERTY_RECORD_ID: {"title": [{"text": {"content": record.id}}]},
            PROPERTY_SPENT_AT: {"date": {"start": record.spent_at.isoformat()}},
            PROPERTY_MERCHANT: {"rich_text": [{"text": {"content": record.merchant}}]},
            PROPERTY_AMOUNT: {"number": record.amount},
            PROPERTY_PAYMENT_METHOD: {"select": {"name": record.payment_method}},
            PROPERTY_CATEGORY: {"select": {"name": record.category}},
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

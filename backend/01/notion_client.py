from __future__ import annotations

from copy import deepcopy

import httpx

from notion_config import load_runtime_config
from notion_constants import PROPERTY_NOTION_SYNC_STATUS, STATUS_SUCCESS
from notion_models import NotionGraphState, NotionWriteResult


def parse_notion_response(response: httpx.Response, title: str, payload: dict) -> NotionWriteResult:
    if response.is_error:
        return NotionWriteResult(
            ok=False,
            title=title,
            message=f"Notion 페이지 생성 실패({response.status_code}): {response.text.strip()}",
            payload=payload,
        )

    data = response.json()
    return NotionWriteResult(
        ok=True,
        page_id=data.get("id"),
        page_url=data.get("url"),
        title=title,
        message="Notion 페이지 생성 완료",
        payload=payload,
    )


def write_to_notion(state: NotionGraphState) -> NotionGraphState:
    config = load_runtime_config()
    title = state["title"]
    payload = deepcopy(state["payload"])
    payload["properties"][PROPERTY_NOTION_SYNC_STATUS] = {"multi_select": [{"name": STATUS_SUCCESS}]}

    if not config.notion_token or not config.notion_database_id:
        result = NotionWriteResult(
            ok=True,
            skipped=True,
            title=title,
            message="NOTION_TOKEN 또는 NOTION_DATABASE_URL/ID가 없어 dry-run으로 종료했습니다.",
            payload=payload,
        )
        return {**state, "result": result}

    payload["parent"] = {"database_id": config.notion_database_id}
    headers = {
        "Authorization": f"Bearer {config.notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": config.notion_version,
    }

    with httpx.Client(timeout=30) as client:
        response = client.post("https://api.notion.com/v1/pages", json=payload, headers=headers)

    result = parse_notion_response(response, title, payload)
    return {**state, "result": result}

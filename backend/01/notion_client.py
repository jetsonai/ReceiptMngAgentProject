from __future__ import annotations

from copy import deepcopy

import httpx

from notion_config import load_runtime_config
from notion_constants import PROPERTY_NOTION_SYNC_STATUS, STATUS_SUCCESS
from notion_models import NotionGraphState, NotionWriteResult


def parse_notion_response(response: httpx.Response, title: str, payload: dict) -> NotionWriteResult:
    # Notion API 응답을 서비스에서 쓰기 쉬운 공통 결과 모델로 변환한다.
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
    # LangGraph의 write 단계: payload를 실제 Notion pages API로 전송한다.
    config = load_runtime_config()
    title = state["title"]
    payload = deepcopy(state["payload"])
    # 생성 시도 직전에는 동기화 상태를 성공으로 바꿔 Notion DB에 저장한다.
    payload["properties"][PROPERTY_NOTION_SYNC_STATUS] = {"multi_select": [{"name": STATUS_SUCCESS}]}

    if not config.notion_token or not config.notion_database_id:
        # 키가 없을 때도 payload를 확인할 수 있도록 실제 호출 없이 성공 형태로 반환한다.
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
        # Notion API는 bearer token과 고정 버전 헤더가 필요하다.
        "Authorization": f"Bearer {config.notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": config.notion_version,
    }

    with httpx.Client(timeout=30) as client:
        response = client.post("https://api.notion.com/v1/pages", json=payload, headers=headers)

    result = parse_notion_response(response, title, payload)
    return {**state, "result": result}

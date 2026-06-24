from __future__ import annotations

from langgraph.graph import END, StateGraph

from env_loader import load_project_env
from notion_client import write_to_notion
from notion_models import ExpenseRecord, NotionGraphState, NotionWriteResult
from notion_payload import build_notion_payload

load_project_env()
from notion_constants import STATUS_PENDING


def build_graph():
    graph = StateGraph(NotionGraphState)
    graph.add_node("prepare", build_notion_payload)
    graph.add_node("write", write_to_notion)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "write")
    graph.add_edge("write", END)
    return graph.compile()


notion_graph = build_graph()


def record_expense_to_notion(record: ExpenseRecord) -> NotionWriteResult:
    # 외부 팀이 바로 호출할 수 있는 단일 진입점.
    state: NotionGraphState = {"record": record}
    final_state: NotionGraphState = notion_graph.invoke(state)
    return final_state["result"]


if __name__ == "__main__":
    sample = ExpenseRecord(
        id="EXP-20260622-0001",
        user_id="demo-user",
        amount=12500,
        category="식비",
        payment_method="카드",
        merchant="편의점",
        memo="편의점 간식 지출이 많음",
        source="image_upload",
        budget_status="예산 초과",
        notion_sync_status=STATUS_PENDING,
        addr="서울시 강남구",
        tell="02-123-4567",
    )
    result = record_expense_to_notion(sample)
    print(result.model_dump())

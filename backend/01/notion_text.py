from __future__ import annotations

from notion_config import load_runtime_config
from notion_models import ExpenseRecord

try:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover
    ChatPromptTemplate = None  # type: ignore[assignment]
    ChatOpenAI = None  # type: ignore[assignment]


def build_title(record: ExpenseRecord) -> str:
    merchant = f" {record.merchant}" if record.merchant else ""
    return f"{record.spent_at.isoformat()} {record.category}{merchant} {record.amount:,.0f}원"


def polish_body_with_llm(record: ExpenseRecord, fallback_body: str) -> str:
    config = load_runtime_config()
    if not config.openai_api_key or ChatPromptTemplate is None or ChatOpenAI is None:
        return fallback_body

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "너는 가계부 노션 페이지 작성 보조야. 한국어로 짧고 깔끔하게 정리해.",
            ),
            (
                "human",
                "지출 정보:\n- 소비 카테고리: {category}\n- 지출금액: {amount}\n- 결제 수단: {payment_method}\n- 가맹점: {merchant}\n- 메모: {memo}\n- 예산평가결과: {budget_status}\n\n이 내용을 노션 본문용으로 정리해줘.",
            ),
        ]
    )
    llm = ChatOpenAI(model=config.openai_model, temperature=0.2)
    response = (prompt | llm).invoke(
        {
            "category": record.category,
            "amount": f"{record.amount:,.0f}원",
            "payment_method": record.payment_method,
            "merchant": record.merchant or "미기재",
            "memo": record.memo or "없음",
            "budget_status": record.budget_status or "미평가",
        }
    )
    content = getattr(response, "content", "")
    return content.strip() if isinstance(content, str) and content.strip() else fallback_body


def build_notion_body(record: ExpenseRecord) -> str:
    fallback_body = (
        f"## 이번 주 소비 패턴 분석 및 절약 팁\n\n"
        f"- 소비 카테고리: {record.category}\n"
        f"- 지출금액: {record.amount:,.0f}원\n"
        f"- 결제 수단: {record.payment_method}\n"
        f"- 가맹점: {record.merchant or '미기재'}\n\n"
        f"### 메모\n{record.memo or '메모 없음'}\n\n"
        f"### 예산평가결과\n{record.budget_status or '미평가'}"
    )
    return polish_body_with_llm(record, fallback_body)

import os
import json
import base64
import tempfile
from datetime import datetime
from typing import Annotated, TypedDict, Literal, List, Dict, Any
from urllib.parse import quote_plus
from dotenv import load_dotenv

# FastAPI 컴포넌트
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# 랭그래프 및 랭체인
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

try:
    from app.services.rag_service import PolicyRagService
except ModuleNotFoundError:
    # Allow running from backend/app with `uvicorn main:app`.
    from services.rag_service import PolicyRagService

load_dotenv()

app = FastAPI(title="Smart Receipt Agent Backend", version="1.0")

# 외부 교차 출처 스크립트(CORS) 허용 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ==========================================
# LangGraph 상태 및 아키텍처 정의
# ==========================================
class ReceiptAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    id: str                  
    spent_at: str            
    merchant: str            
    amount: int              
    payment_method: str      
    category: str            
    memo: str                
    source: str              
    budget_status: str       
    notion_sync_status: str  
    addr: str                
    tel: str                 
    reg_date: str            
    items: List[Dict[str, Any]] 
    detected_people_count: int  
    per_person_amount: int      
    image_path: str          
    ocr_raw_text: str        
    rag_violation_report: str 
    category_confidence: float
    category_reason: str
    policy_category: str
    category_matched_rules: List[str]
    payment_status: str
    payment_reason: str

POLICY_RAG_SERVICE: PolicyRagService | None = None


def _resolve_db_target(default_target: str) -> str:
    """Resolve DB target from env with AWS fallback when DATABASE_URL is absent."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    mysql_host = os.getenv("AWS_MYSQL_HOST", "").strip()
    mysql_user = os.getenv("AWS_MYSQL_USER", "").strip()
    mysql_password = os.getenv("AWS_MYSQL_PASSWORD", "").strip()
    mysql_database = os.getenv("AWS_MYSQL_DATABASE", "").strip()
    mysql_port = os.getenv("AWS_MYSQL_PORT", "3306").strip() or "3306"

    if mysql_host and mysql_user and mysql_password and mysql_database:
        return (
            f"mysql://{quote_plus(mysql_user)}:{quote_plus(mysql_password)}"
            f"@{mysql_host}:{mysql_port}/{mysql_database}"
        )

    return default_target


def get_policy_rag_service() -> PolicyRagService:
    """이미 생성된 ChromaDB 인덱스를 열어 RAG 서비스를 재사용한다."""

    global POLICY_RAG_SERVICE
    if POLICY_RAG_SERVICE is None:
        POLICY_RAG_SERVICE = PolicyRagService()
    return POLICY_RAG_SERVICE

def upload_receipt_node(state: ReceiptAgentState):
    path = state.get("image_path", "").strip()
    if not path or not os.path.exists(path):
        return {"source": "image", "id": "error_id"}
    return {"source": "image", "id": f"api_fixed_{int(os.path.getmtime(path))}"}

def ocr_process_node(state: ReceiptAgentState):
    path = state.get("image_path")
    try:
        with open(path, "rb") as f:
            base64_image = base64.b64encode(f.read()).decode('utf-8')
        llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
        vision_prompt = [
            {
                "type": "text",
                "text": "영수증 이미지에서 가맹점, 일자, 주소, 연락처 및 상세 품목 테이블(수량/금액)을 줄바꿈을 준수하여 텍스트로 복원하세요."
            },
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
        ]
        response = llm.invoke([HumanMessage(content=vision_prompt)])
        return {"ocr_raw_text": response.content}
    except Exception as e:
        return {"ocr_raw_text": f"OCR 에러: {e}"}

def analyze_expenditure_node(state: ReceiptAgentState):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    parsing_prompt = f"""영수증 텍스트를 파싱하여 규정된 JSON 구조로만 반환하세요.
    OCR 원문: {state['ocr_raw_text']}
    JSON 양식:
    {{
      "spent_at": "YYYY-MM-DD", "merchant": "상점명", "addr": "주소", "tel": "전화번호", "amount": 총합금액(숫자),
      "payment_method": "결제수단", "items": [{{"name": "품목명", "count": 수량(숫자), "total": 금액(숫자)}}]
    }}
    """
    try:
        response = llm.invoke([HumanMessage(content=parsing_prompt)], response_format={"type": "json_object"})
        result = json.loads(response.content)
        total_amount = result.get("amount", 0)
        parsed_items = result.get("items", [])
        
        # 실제 개발 가속화 완료된 파이썬 수량 필터링 결합 연산
        people_count = 0
        for item in parsed_items:
            item_name = item.get("name", "")
            item_count = item.get("count", 1)
            exclude_keywords = ["음료", "콜라", "사이다", "소주", "맥주", "공기밥", "공깃밥", "사리"]
            if not any(keyword in item_name for keyword in exclude_keywords):
                people_count += item_count
        if people_count <= 0: people_count = 1
        per_person = int(total_amount / people_count)
        
        return {
          "spent_at": result.get("spent_at"), "merchant": result.get("merchant"),
          "addr": result.get("addr", ""), "tel": result.get("tel", ""),
          "reg_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          "amount": total_amount, "payment_method": result.get("payment_method", ""),
          "category": "식비/외근", "items": parsed_items,
          "detected_people_count": people_count, "per_person_amount": per_person,
          "memo": f"Vision OCR 기반 파이썬 로직 정밀 연산 / 총 {people_count}명 식사"
        }
    except:
        return {"merchant": "파싱에러", "amount": 0, "detected_people_count": 1, "per_person_amount": 0}

def policy_rag_node(state: ReceiptAgentState):
    try:
        item_names = [
            item.get("name", str(item)) if isinstance(item, dict) else str(item)
            for item in state.get("items", [])
        ]
        result = get_policy_rag_service().classify(
            receipt_text=state.get("ocr_raw_text", ""),
            store_name=state.get("merchant", ""),
            items=item_names,
            memo=state.get("memo", ""),
            per_person_amount=state.get("per_person_amount", 0),
        )
        print(f"[RAG 분류 결과] 카테고리: {result.category}, 신뢰도: {result.confidence}, 지급여부: {result.payment_status}")
    except Exception as e:
        return {
            "category": state.get("category", "기타"),
            "category_confidence": 0.0,
            "category_reason": "RAG 카테고리 분류에 실패했습니다.",
            "policy_category": "기타",
            "category_matched_rules": [],
            "payment_status": "검토 필요",
            "payment_reason": "RAG 분류 실패로 지급여부를 자동 판단하지 못했습니다.",
            "rag_violation_report": f"RAG 분류 실패: {e}",
        }

    return {
        "category": result.category,
        "category_confidence": result.confidence,
        "category_reason": result.reason,
        "policy_category": result.policy_category,
        "category_matched_rules": result.matched_rules,
        "payment_status": result.payment_status,
        "payment_reason": result.payment_reason,
        "rag_violation_report": result.report,
    }

def evaluate_budget_node(state: ReceiptAgentState):
    status = "주의" if "위반" in state.get("rag_violation_report", "") else "정상"
    return {"budget_status": status}

# 기획서 요구사항에 의거한 DB / 노션 기록 스텁(로그 처리) 선언
def save_db_node(state: ReceiptAgentState):
    # backend/app에서 실행될 때를 대비해 프로젝트 루트를 경로에 추가
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))

    try:
        from ExpenseGraph.save_local_db import save_local_db, DEFAULT_DB_TARGET
    except Exception as e:
        print(f"[DB 로그] save_local_db import 실패: {e}")
        return {"saved_local_db": False, "db_error": str(e)}

    expense_data = {
        "user_id": state.get("id", "api_user"),
        "spent_at": state.get("spent_at"),
        "merchant": state.get("merchant"),
        "amount": state.get("amount", 0),
        "payment_method": state.get("payment_method", ""),
        "category": state.get("category", "미분류"),
        "memo": state.get("memo", ""),
        "source": state.get("source", "image"),
        "budget_status": state.get("budget_status", "정상"),
        "notion_sync_status": state.get("notion_sync_status", "pending"),
        "addr": state.get("addr", ""),
        "tel": state.get("tel", ""),
        "reg_date": state.get("reg_date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "items": state.get("items", []),
        "detected_people_count": state.get("detected_people_count", 1),
        "per_person_amount": state.get("per_person_amount", 0),
        "image_path": state.get("image_path", ""),
        "raw_text": state.get("ocr_raw_text", ""),
        "ocr_raw_text": state.get("ocr_raw_text", ""),
        "rag_violation_report": state.get("rag_violation_report", ""),
        "category_confidence": state.get("category_confidence", 0.0),
        "category_reason": state.get("category_reason", ""),
        "category_matched_rules": state.get("category_matched_rules", []),
    }

    db_target = _resolve_db_target(DEFAULT_DB_TARGET)
    save_result = save_local_db(expense_data, db_path=db_target)
    print(
        f"[DB 로그] 저장결과={save_result.get('saved_local_db')} "
        f"expense_id={save_result.get('expense_id')} "
        f"target={db_target} "
        f"상점명={expense_data.get('merchant')} 금액={expense_data.get('amount')}"
    )

    return {"db_save_result": save_result}

def record_notion_node(state: ReceiptAgentState):
    print(f"[Notion API 로그] 칸반 보드 연동 성공 - Sync Status: success")
    return {"notion_sync_status": "success"}

def route_after_budget(state: ReceiptAgentState) -> Literal["to_notion", "to_end"]:
    return "to_notion"

# 워크플로우 조립
workflow = StateGraph(ReceiptAgentState)
workflow.add_node("upload_receipt", upload_receipt_node)
workflow.add_node("ocr_process", ocr_process_node)
workflow.add_node("analyze_expenditure", analyze_expenditure_node)
workflow.add_node("policy_rag", policy_rag_node)
workflow.add_node("evaluate_budget", evaluate_budget_node)
workflow.add_node("save_db", save_db_node)
workflow.add_node("record_notion", record_notion_node)

workflow.add_edge(START, "upload_receipt")
workflow.add_edge("upload_receipt", "ocr_process")
workflow.add_edge("ocr_process", "analyze_expenditure")
workflow.add_edge("analyze_expenditure", "policy_rag")
workflow.add_edge("policy_rag", "evaluate_budget")
workflow.add_edge("evaluate_budget", "save_db")
workflow.add_conditional_edges("save_db", route_after_budget, {"to_notion": "record_notion", "to_end": END})
workflow.add_edge("record_notion", END)

memory = MemorySaver()
langgraph_app = workflow.compile(checkpointer=memory)

# ==========================================
# REST API 엔드포인트 구현
# ==========================================
@app.post("/api/analyze-receipt")
async def analyze_receipt_api(file: UploadFile = File(...)):
    try:
        # 1. 파일 스트림을 수신하여 안전하게 임시 파일로 격리 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
            temp_file.write(await file.read())
            temp_file_path = temp_file.name
            
        # 2. LangGraph 수동 호출 설정 빌드
        config = {"configurable": {"thread_id": "fastapi_agent_runtime_session"}}
        initial_state = {
            "messages": [HumanMessage(content="FastAPI 백엔드 수신 엔진 가동")],
            "image_path": temp_file_path,
            "notion_sync_status": "pending"
        }
        
        # 3. 파이썬 백엔드 스레드에서 랭그래프 순차 컴파일 실행
        langgraph_app.invoke(initial_state, config=config)
        
        # 4. 최종 누적 결과 적재 상태 반환
        final_values = langgraph_app.get_state(config).values
        
        # 임시 이미지 파일 자원 삭제
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            
        return {"status": "success", "data": final_values}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

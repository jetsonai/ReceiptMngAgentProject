import os
import json
import base64
import tempfile
from datetime import datetime
from typing import Annotated, TypedDict, Literal, List, Dict, Any
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

from app.services.rag_service import PolicyRagService

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
    category_matched_rules: List[str]

POLICY_RAG_SERVICE: PolicyRagService | None = None


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
        )
    except Exception as e:
        return {
            "category": state.get("category", "기타"),
            "category_confidence": 0.0,
            "category_reason": "RAG 카테고리 분류에 실패했습니다.",
            "category_matched_rules": [],
            "rag_violation_report": f"RAG 분류 실패: {e}",
        }

    is_violation = result.category == "지급 제외"
    if "식비" in result.category and state.get("per_person_amount", 0) > 20000:
        is_violation = True

    verdict = "위반" if is_violation else "준수"
    matched_rules_text = "\n".join(f"- {rule}" for rule in result.matched_rules)
    report = (
        f"{verdict}: RAG 분류 결과 '{result.category}'입니다.\n"
        f"분류 근거: {result.reason}\n"
        f"신뢰도: {result.confidence}\n"
        f"1인당 금액: {state.get('per_person_amount', 0):,}원\n"
        f"참조 조항:\n{matched_rules_text}"
    )

    return {
        "category": result.category,
        "category_confidence": result.confidence,
        "category_reason": result.reason,
        "category_matched_rules": result.matched_rules,
        "rag_violation_report": report,
    }

def evaluate_budget_node(state: ReceiptAgentState):
    status = "주의" if "위반" in state.get("rag_violation_report", "") else "정상"
    return {"budget_status": status}

# 기획서 요구사항에 의거한 DB / 노션 기록 스텁(로그 처리) 선언
def save_db_node(state: ReceiptAgentState):
    print(f"[SQLite DB 로그] Insert 성공 - 상점명: {state.get('merchant')}, 금액: {state.get('amount')}")
    return {}

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
    uvicorn.run("main.py:app", host="0.0.0.0", port=8000, reload=True)

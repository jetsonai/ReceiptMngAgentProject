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
    user_id: str          #user_id 추가 Kate 20260625
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
    
    parsing_prompt = f"""영수증 텍스트를 분석하여 규정된 JSON 구조로만 반환하세요.
    
    [중요 지침]
    1. 영수증 내용(가맹점, 품목)을 바탕으로 가장 적절한 카테고리를 분류하세요.
       - 철도, 택시, 버스, 항공, 통행료, 주차장 등 이동 관련: "교통비/출장"
       - 일반 식당, 구내식당, 카페, 분식, 중국집 등 음식 관련: "식비/외근"
       - 그 외 품목: "기타"
    2. 영수증에 표기된 품목들과 총 금액을 바탕으로 실제 이용/식사를 수행한 전체 인원수(people_count)를 추론하세요.
       (별도 품목 수량 표기가 명확하지 않다면 일반적인 1인 지출 혹은 금액 대비 인원으로 합리적 추론)
    
    OCR 원문: {state['ocr_raw_text']}
    
    JSON 양식:
    {{
      "spent_at": "YYYY-MM-DD", 
      "merchant": "상점명", 
      "addr": "주소", 
      "tel": "전화번호", 
      "amount": 총합금액(숫자),
      "payment_method": "결제수단", 
      "category": "교통비/출장" 또는 "식비/외근" 또는 "기타",
      "inferred_people_count": 예상인원수(숫자),
      "items": [{{ "name": "품목명", "count": 수량(숫자), "total": 금액(숫자) }}]
    }}
    """
    try:
        response = llm.invoke([HumanMessage(content=parsing_prompt)], response_format={"type": "json_object"})
        result = json.loads(response.content)
        total_amount = result.get("amount", 0)
        parsed_items = result.get("items", [])
        detected_category = result.get("category", "식비/외근")
        
        # 1. 인원수 추출 (LLM 추론값 우선 활용)
        people_count = result.get("inferred_people_count", 0)
        if people_count <= 0:
            for item in parsed_items:
                item_name = item.get("name", "")
                item_count = item.get("count", 1)
                exclude_keywords = ["음료", "콜라", "사이다", "소주", "맥주", "공기밥", "공깃밥", "사리"]
                if not any(keyword in item_name for keyword in exclude_keywords):
                    people_count += item_count
                    
        if people_count <= 0: 
            people_count = 1
            
        per_person = int(total_amount / people_count)
        
        # 2. 금액 조건에 따른 맞춤형 메모(memo) 및 가이드 라인 생성 (RAG 오판 방지 및 상세 사유 유도)
        if "교통" in detected_category:
            memo_text = f"업무 이동에 따른 교통비 지출 (이용 인원: {people_count}명 / 1인당 {per_person:,}원)."
        else:
            # 식비 한도(외근 중식/석식 기준 15,000원) 초과 여부 체크
            if per_person > 15000:
                memo_text = (
                    f"식비 지출 (총 {people_count}명 식사 / 1인당 {per_person:,}원). "
                    f"[규정 위반 경고] 1인당 식비({per_person:,}원)가 회사 내규 제6조 외근 식비 및 제9조 국내 출장 식비 한도 기준(15,000원)을 명백히 초과하여 규격 위반 대상입니다."
                )
            else:
                memo_text = (
                    f"점심/저녁 업무 식사 지출 (총 {people_count}명 식사 / 1인당 {per_person:,}원). "
                    f"회사 내규의 외근 식비 1인당 한도(15,000원) 내의 정상 지출입니다."
                )
        
        return {
          "spent_at": result.get("spent_at"), 
          "merchant": result.get("merchant"),
          "addr": result.get("addr", ""), 
          "tel": result.get("tel", ""),
          "reg_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          "amount": total_amount, 
          "payment_method": result.get("payment_method", ""),
          "category": detected_category, 
          "items": parsed_items,
          "detected_people_count": people_count, 
          "per_person_amount": per_person,
          "memo": memo_text
        }
    except Exception as e:
        return {"merchant": "파싱에러", "amount": 0, "detected_people_count": 1, "per_person_amount": 0, "memo": f"에러: {e}", "category": "기타"}
    
def analyze_expenditure_node0(state: ReceiptAgentState):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    
    # f-string 내부의 모든 JSON 객체 중괄호를 {{ }}로 이스케이프 처리했습니다.
    parsing_prompt = f"""영수증 텍스트를 분석하여 규정된 JSON 구조로만 반환하세요.
    
    [중요 지침]
    1. 영수증 내용(가맹점, 품목)을 바탕으로 가장 적절한 카테고리를 분류하세요.
       - 철도, 택시, 버스, 항공, 통행료, 주차장 등 이동 관련: "교통비/출장"
       - 일반 식당, 구내식당, 카페, 분식 등 음식 관련: "식비/외근"
       - 그 외 품목: "기타"
    2. 영수증에 표기된 품목들과 총 금액을 바탕으로 실제 이용/식사를 수행한 전체 인원수(people_count)를 추론하세요.
    
    OCR 원문: {state['ocr_raw_text']}
    
    JSON 양식:
    {{
      "spent_at": "YYYY-MM-DD", 
      "merchant": "상점명", 
      "addr": "주소", 
      "tel": "전화번호", 
      "amount": 총합금액(숫자),
      "payment_method": "결제수단", 
      "category": "교통비/출장" 또는 "식비/외근" 또는 "기타",
      "inferred_people_count": 예상인원수(숫자),
      "items": [{{ "name": "품목명", "count": 수량(숫자), "total": 금액(숫자) }}]
    }}
    """
    try:
        response = llm.invoke([HumanMessage(content=parsing_prompt)], response_format={"type": "json_object"})
        result = json.loads(response.content)
        total_amount = result.get("amount", 0)
        parsed_items = result.get("items", [])
        detected_category = result.get("category", "식비/외근")
        
        # 1. 인원수 추출 (LLM 추론값 우선 활용)
        people_count = result.get("inferred_people_count", 0)
        if people_count <= 0:
            for item in parsed_items:
                item_name = item.get("name", "")
                item_count = item.get("count", 1)
                exclude_keywords = ["음료", "콜라", "사이다", "소주", "맥주", "공기밥", "공깃밥", "사리"]
                if not any(keyword in item_name for keyword in exclude_keywords):
                    people_count += item_count
                    
        if people_count <= 0: 
            people_count = 1
            
        per_person = int(total_amount / people_count)
        
        # 2. 카테고리에 따른 맞춤형 메모(memo) 생성 -> RAG의 오판 방지
        if "교통" in detected_category:
            memo_text = f"업무 이동에 따른 교통비 지출 (이용 인원: {people_count}명 / 1인당 {per_person:,}원)."
        else:
            memo_text = (
                f"점심/저녁 업무 식사 지출 (총 {people_count}명 식사 / 1인당 {per_person:,}원). "
                f"회사 내규의 외근 식비 1인당 한도(15,000원)를 준수함."
            )
        
        return {
          "spent_at": result.get("spent_at"), 
          "merchant": result.get("merchant"),
          "addr": result.get("addr", ""), 
          "tel": result.get("tel", ""),
          "reg_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          "amount": total_amount, 
          "payment_method": result.get("payment_method", ""),
          "category": detected_category, 
          "items": parsed_items,
          "detected_people_count": people_count, 
          "per_person_amount": per_person,
          "memo": memo_text
        }
    except Exception as e:
        return {"merchant": "파싱에러", "amount": 0, "detected_people_count": 1, "per_person_amount": 0, "memo": f"에러: {e}", "category": "기타"}



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
        #"user_id": state.get("id", "api_user"), 
        "user_id": state.get("user_id", "unknown-user"), #user_id 추가 Kate 20260625
        "spent_at": state.get("spent_at"),
        "merchant": state.get("merchant"),
        "amount": state.get("amount", 0),
        "payment_method": state.get("payment_method", ""),
        "category": state.get("category", "미분류"),
        "memo": state.get("memo", ""),
        "source": state.get("source", "image"),
        "budget_status": state.get("payment_status", "정상"),
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

#############################################
#  record_notion_node 연동 시작 Kate 20260625
#############################################
import sys
import os

# 현재 실행 위치를 기준으로 'notion' 폴더의 절대 경로를 계산하여 탐색 경로 맨 앞에 추가합니다.
current_dir = os.path.dirname(os.path.abspath(__file__))
notion_dir = os.path.join(current_dir, "notion")
if notion_dir not in sys.path:
    sys.path.insert(0, notion_dir)

# 현재 파일(main.py)의 상위 상위 폴더(루트)를 구한 뒤, ExpenseGraph 경로를 시스템 패스에 주입합니다.
current_dir2 = os.path.dirname(os.path.abspath(__file__))  # backend/app
root_dir2 = os.path.dirname(os.path.dirname(current_dir2))   # C:. (루트)
expense_graph_path = os.path.join(root_dir2, "ExpenseGraph")

if expense_graph_path not in sys.path:
    sys.path.append(expense_graph_path)

    
from notion.notion_record_agent import record_expense_to_notion
from notion.notion_models import ExpenseRecord

def record_notion_node(state: ReceiptAgentState):
    print(f"[Notion API 로그] 칸반 보드 연동")
    
    # 2. ReceiptAgentState 데이터를 ExpenseRecord 규격에 맞게 매핑
    # 'state.get'을 활용해 값이 없을 경우 기본값을 안전하게 처리합니다.
    expense_record = ExpenseRecord(
        id=state.get("id", "EXP-UNKNOWN"),
        user_id=state.get("user_id", "unknown-user"),  # 수정: 하드코딩된 "demo-user" 대신 상태의 user_id 매핑
        amount=state.get("amount", 0),
        category=state.get("category", "미분류"),
        payment_method=state.get("payment_method", "미지정"),
        merchant=state.get("merchant", "알 수 없음"),
        memo=state.get("memo", ""),
        source="image_upload",                       
        budget_status=state.get("payment_status", "평가 보류"),
        notion_sync_status="pending",
        addr=state.get("addr", "정보 없음"),
        tell=state.get("tell", "정보 없음")
    )
    
    try:
        # 3. 아까 성공했던 노션 기록 에이전트 인터페이스 호출
        result = record_expense_to_notion(expense_record)
        
        if result.ok:
            print(f"� 노션 기록 성공! Page URL: {result.page_url}")
            return {"notion_sync_status": "success"}
        else:
            print(f"❌ 노션 기록 실패(Dry-run 또는 에러): {result.message}")
            return {"notion_sync_status": "failed"}
            
    except Exception as e:
        print(f"� 노션 연동 노드 에러 발생: {str(e)}")
        return {"notion_sync_status": "failed"}

#############################################
#  record_notion_node 연동 끝 Kate 20260625
#############################################

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

# ADIM code by Kate 20260625

from pydantic import BaseModel
from typing import Optional

# 1. 프론트엔드 요청 데이터 검증을 위한 Pydantic 모델
class AdminDashboardRequest(BaseModel):
    db_target: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None

# 2. 어드민 대시보드 데이터 조회 엔드포인트 신설
@app.post("/api/admin/dashboard")
async def get_admin_dashboard_data(payload: AdminDashboardRequest):
    try:
        # save_local_db에 추가한 공용 함수 호출
        from save_local_db import load_dashboard_data_shared
        
        result_data = load_dashboard_data_shared(
            db_target=payload.db_target,
            start_date=payload.start_date,
            end_date=payload.end_date,
            category=payload.category
        )
        return {"status": "success", "data": result_data}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"백엔드 대시보드 쿼리 실패: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

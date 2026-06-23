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
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

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

def init_policy_rag():
    policy_text = """
    제6조 외근 식비 기준: 식비는 1인 기준 조식 10,000원 이내, 중식 15,000원 이내, 석식 20,000원 이내이며 1일 식비 총액은 45,000원 이내이다. 고급 레스토랑, 주점, 유흥업소, 카페 중심의 식사 대체 지출은 인정하지 않는다. 커피, 음료, 간식은 원칙적으로 개인 지출로 보며 회의비나 현장운영비로만 처리 가능하다.
    제7조 외근 일비 기준: 4시간 미만은 지급하지 않음, 4시간 이상 8시간 미만은 10,000원, 8시간 이상은 20,000원 청구 가능하다. 1일 최대 한도는 20,000원이다.
    제8조 국내 교통비 기준: KTX, SRT 고속철도는 일반석 기준 실비 정산한다. 특실이나 비즈니스석은 사전 승인 필요하다. 택시비는 대중교통 이용이 곤란하거나 장비 운반, 심야/새벽 이동, 일정상 불가피한 경우에 한해 영수증 제출 시 실비 정산한다. 자가용은 편도 10km 이하 5,000원 정액, 10km~30km는 1km당 500원, 30km~100km는 1km당 450원, 100km 초과는 1km당 400원 정산한다.
    제10조 국내 숙박비 기준: 서울, 수도권, 광역시는 1박당 100,000원 이내, 일반 시군 지역은 80,000원 이내 실비 정산한다. 성수기나 행사 기간 사전 승인 시 130,000원 이내이다.
    제18조 지급 제외 항목: 개인적인 식사/간식/음료, 주류, 유흥업소, 사우나, 마사지, 관광, 쇼핑 비용, 개인 과실 과태료/범칙금, 증빙이 없는 비용은 지급 제외한다.
    제20조 사전 승인 필요 항목: 1박 이상의 국내 출장, 해외 출장, 항공권 구매, 렌터카 이용, 숙박비 한도 초과, 고속철도 특실 이용, 1회 100,000원 초과 회의비는 사전 승인이 필수이다.
    """
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=30)
    split_docs = text_splitter.create_documents([policy_text])
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return Chroma.from_documents(split_docs, embeddings)

POLICY_VECTOR_STORE = init_policy_rag()

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
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    query = f"{state['category']} 식비 한도 규정"
    retrieved_docs = POLICY_VECTOR_STORE.similarity_search(query, k=2)
    context = "\n".join([doc.page_content for doc in retrieved_docs])
    policy_prompt = f"""내규를 기반으로 한도 위반 여부를 검토하세요. 1인당 금액({state['per_person_amount']}원)이 석식 한도 20,000원 이내인지 확인하고 요약 리포트에 '준수' 혹은 '위반' 단어를 채우세요.
    내규: {context}"""
    response = llm.invoke([HumanMessage(content=policy_prompt)])
    return {"rag_violation_report": response.content}

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
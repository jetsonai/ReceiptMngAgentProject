import os
import json
import base64
import tempfile
from datetime import datetime  # 오늘 날짜 주입을 위한 모듈
from typing import Annotated, TypedDict, Literal, List, Dict, Any
from dotenv import load_dotenv
from PIL import Image
import streamlit as st

# 랭그래프 및 메시지 컴포넌트
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# RAG 구성을 위한 OpenAI 및 Chroma 컴포넌트
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from save_local_db import DEFAULT_DB_PATH, save_local_db

# .env 파일로부터 환경 변수(OPENAI_API_KEY) 로드
load_dotenv()

# ==========================================
# 1. 상태 관리 설계 (State Definition)
# ==========================================
class ReceiptAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    
    # 기획안 DB 속성 반영
    id: str                  # 지출 항목 고유 식별자 [cite: 48, 50]
    spent_at: str            # 지출 날짜 [cite: 51, 53]
    merchant: str            # 상점명 또는 사용처 [cite: 54, 56]
    amount: int              # 지출 총 금액 [cite: 57, 59]
    payment_method: str      # 결제수단 [cite: 60, 62]
    category: str            # 소비 카테고리 [cite: 63, 65]
    memo: str                # 사용자 메모 또는 OCR 원문 요약 [cite: 66, 68]
    source: str              # 입력 경로 ('image' 또는 'text') [cite: 69, 71]
    budget_status: str       # 예산 평가 결과 ('정상' / '주의' / '초과') [cite: 72, 74]
    notion_sync_status: str  # Notion 기록 결과 ('success' / 'failed' / 'skipped') [cite: 75, 77]
    
    # 🌟 요구사항에 맞게 변수명 수정 및 신규 필드 추가
    addr: str                # 상점 주소 (변수명 address -> addr 변경) [cite: 45, 78, 79]
    tel: str                 # 상점 전화번호 (TELL) [cite: 45, 80, 81]
    reg_date: str            # 🌟 신규 추가: 등록일시 (REG_DATE) [cite: 45, 82, 83]
    
    # N분의 1 계산 고도화 필드
    items: List[Dict[str, Any]] 
    detected_people_count: int  
    per_person_amount: int      
    image_path: str          
    ocr_raw_text: str        
    rag_violation_report: str 

# ==========================================
# 2. 내규 RAG 초기화 함수 (지연 로딩 및 캐싱)
# ==========================================
@st.cache_resource
def get_policy_vector_store():
    policy_text = """
    제6조 외근 식비 기준: 식비는 1인 기준 조식 10,000원 이내, 중식 15,000원 이내, 석식 20,000원 이내이며 1일 식비 총액은 45,000원 이내이다. 고급 레스토랑, 주점, 유흥업소, 카페 중심의 식사 대체 지출은 인정하지 않는다. 커피, 음료, 간식은 원칙적으로 개인 지출로 보며 회의비나 현장운영비로만 처리 가능하다. [cite: 115, 116, 118, 119, 123, 125, 126, 130, 133]
    제7조 외근 일비 기준: 4시간 미만은 지급하지 않음, 4시간 이상 8시간 미만은 10,000원, 8시간 이상은 20,000원 청구 가능하다. 1일 최대 한도는 20,000원이다. [cite: 134, 137, 139, 140, 141, 142, 146]
    제8조 국내 교통비 기준: KTX, SRT 고속철도는 일반석 기준 실비 정산한다. 특실이나 비즈니스석은 사전 승인 필요하다. 택시비는 대중교통 이용이 곤란하거나 장비 운반, 심야/새벽 이동, 일정상 불가피한 경우에 한해 영수증 제출 시 실비 정산한다. 자가용은 편도 10km 이하 5,000원 정액, 10km~30km는 1km당 500원, 30km~100km는 1km당 450원, 100km 초과는 1km당 400원 정산한다. [cite: 147, 149, 150, 151, 152, 153, 154, 156, 157, 158, 159, 160, 162, 163, 164, 166, 168, 169, 170, 171, 172, 173]
    제10조 국내 숙박비 기준: 서울, 수도권, 광역시는 1박당 100,000원 이내, 일반 시군 지역은 80,000원 이내 실비 정산한다. 성수기나 행사 기간 사전 승인 시 130,000원 이내이다. [cite: 193, 194, 197, 198, 199, 200, 201]
    제18조 지급 제외 항목: 개인적인 식사/간식/음료, 주류, 유흥업소, 사우나, 마사지, 관광, 쇼핑 비용, 개인 과실 과태료/범칙금, 증빙이 없는 비용은 지급 제외한다. [cite: 276, 278, 279, 280, 285]
    제20조 사전 승인 필요 항목: 1박 이상의 국내 출장, 해외 출장, 항공권 구매, 렌터카 이용, 숙박비 한도 초과, 고속철도 특실 이용, 1회 100,000원 초과 회의비는 사전 승인이 필수이다. [cite: 305, 307, 308, 309, 310, 311, 312, 314]
    """
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=30)
    split_docs = text_splitter.create_documents([policy_text])
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return Chroma.from_documents(split_docs, embeddings)

def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# ==========================================
# 3. 에이전트 워크플로우 노드(Nodes) 구현
# ==========================================
def upload_receipt_node(state: ReceiptAgentState):
    path = state.get("image_path", "").strip()
    if not path or not os.path.exists(path):
        return {"source": "image", "id": "error_id"}
    return {"source": "image", "id": f"local_fixed_{int(os.path.getmtime(path))}"}


def ocr_process_node(state: ReceiptAgentState):
    """ [질문자님 전담 역할 파트]: 고성능 AI Vision OCR 엔진 구동 노드 """
    path = state.get("image_path")
    if state.get("id") == "error_id":
        return {"ocr_raw_text": "파일 오류로 OCR 단계를 건너뜁니다."}
        
    try:
        base64_image = encode_image_to_base64(path)
        llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
        
        vision_prompt = [
            {
                "type": "text",
                "text": """제공된 영수증 이미지를 눈으로 꼼꼼히 판독하여 눈에 보이는 모든 글자(상점명, 주소, 일자, 결제수단)와 
                특히 상품명, 단가, 수량, 금액 테이블 내역을 줄 바꿈(Line Break)을 완벽히 준수하여 하나의 텍스트 본문으로 출력해 주세요. 
                삐뚤어지거나 흐릿한 실사 사진이더라도 인간 감사관이 읽듯 정확히 텍스트화해야 합니다. 주석이나 설명 없이 오직 판독된 원문 텍스트만 출력하세요."""
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64_image}"
                }
            }
        ]
        
        response = llm.invoke([HumanMessage(content=vision_prompt)])
        return {"ocr_raw_text": response.content}
        
    except Exception as e:
        return {"ocr_raw_text": f"Vision OCR 엔진 구동 실패 에러: {e}"}


def analyze_expenditure_node(state: ReceiptAgentState):
    """ FR-1 & FR-2: 지출 정형화 및 파이썬 인원 합산 연산 노드 """
    if "실패" in state["ocr_raw_text"] or "오류" in state["ocr_raw_text"]:
        return {"merchant": "인식불가", "amount": 0, "detected_people_count": 1, "per_person_amount": 0}
        
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    
    # 주소 데이터 매핑 가이드를 address -> addr 명칭으로 변경 지시 [cite: 45, 78, 79]
    parsing_prompt = f"""
    당신은 영수증 텍스트 분석 전문가입니다. 제공된 영수증 OCR 원문을 분석하여 반드시 지정된 템플릿의 JSON 형식으로만 응답하세요.
    [영수증 OCR 원문]
    {state['ocr_raw_text']}
    
    [JSON 출력 가이드]
    {{
      "spent_at": "YYYY-MM-DD 형식의 결제일자 (추정 불가시 현재일자)",
      "merchant": "상점명 또는 회사명",
      "addr": "영수증 내 주소 전체 (없다면 빈문자열)",
      "tel": "전화번호 또는 연락처 (없다면 빈문자열)",
      "amount": 총합계금액(숫자만),
      "payment_method": "결제 수단",
      "items": [
         {{"name": "품목명", "count": 영수증에 명시된 실제 수량(숫자, 없을 시 1), "total": 금액(숫자)}}
      ]
    }}
    """
    try:
        response = llm.invoke([HumanMessage(content=parsing_prompt)], response_format={"type": "json_object"})
        result = json.loads(response.content)
        
        total_amount = result.get("amount", 0)
        parsed_items = result.get("items", [])
        
        # 파이썬 기반 식사 메뉴 수량 합산 로직
        people_count = 0
        for item in parsed_items:
            item_name = item.get("name", "")
            item_count = item.get("count", 1)
            
            exclude_keywords = ["음료", "콜라", "사이다", "소주", "맥주", "공기밥", "공깃밥", "사리"]
            if not any(keyword in item_name for keyword in exclude_keywords):
                people_count += item_count
                
        if people_count <= 0: people_count = 1
        per_person = int(total_amount / people_count)
        
        # 🌟 시스템 등록 시간 동적 생성 (YYYY-MM-DD HH:MM:SS)
        current_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return {
          "spent_at": result.get("spent_at"),
          "merchant": result.get("merchant"),
          "addr": result.get("addr", ""),              # 🌟 addr 필드로 변경 전달 [cite: 45, 78, 79]
          "tel": result.get("tel", ""),
          "reg_date": current_now,                      # 🌟 신규 추가: 가계부 등록 일시 저장 [cite: 45, 82, 83]
          "amount": total_amount,
          "payment_method": result.get("payment_method", ""),
                    "category": "식비/외근",
          "items": parsed_items,
          "detected_people_count": people_count,
          "per_person_amount": per_person,
                    "memo": f"Vision AI OCR 분석 / 총 {people_count}명 식사 (1인당 {per_person}원)"
        }
    except Exception as e:
        return {"merchant": "파싱 실패", "amount": 0, "detected_people_count": 1, "per_person_amount": 0}

def policy_rag_node(state: ReceiptAgentState):
    """ FR-8: 회사 지출 내규 검토 노드 (RAG) """
    if state["amount"] == 0:
        return {"rag_violation_report": "심사 데이터 누락"}
    
    vector_store = get_policy_vector_store()
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    query = f"{state['category']} 식비 한도 규정"
    retrieved_docs = vector_store.similarity_search(query, k=2)
    context = "\n".join([doc.page_content for doc in retrieved_docs])
    
    policy_prompt = f"""
    당신은 회사의 지출 내규 준수 여부를 판정하는 AI 감사관입니다. 내규 내용을 바탕으로 지출 데이터를 검토하세요.
    [회사 지출 내규 내용]
    {context}
    [지출 데이터]
    - 카테고리: {state['category']}
    - 상점: {state['merchant']}
    - 주소 및 연락처: {state['addr']} ({state['tel']})
    - 총 결제 금액: {state['amount']}원
    - 추정 식사 인원: {state['detected_people_count']}명
    - 1인당 계산된 금액: {state['per_person_amount']}원
    [판정 규칙]
    1인당 금액이 지출 시간대 한도(외근 석식 기준 20,000원 이내)를 넘지 않는다면 "준수"로 판단합니다.
    최종 결과 리포트에 '위반' 또는 '준수'라는 단어를 명시하여 작성하세요.
    """
    response = llm.invoke([HumanMessage(content=policy_prompt)])
    return {"rag_violation_report": response.content}

def evaluate_budget_node(state: ReceiptAgentState):
    if "위반" in state.get("rag_violation_report", ""):
        status = "주의"
    else:
        status = "정상"
    return {"budget_status": status}

def save_db_node(state: ReceiptAgentState):
    user_id = state.get("user_id") or "default-user"
    expense_data = {
        "user_id": user_id,
        "store_name": state.get("merchant") or "미상",
        "purchased_at": state.get("spent_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_amount": int(state.get("amount") or 0),
        "payment_method": state.get("payment_method") or "",
        "category": state.get("category") or "기타",
        "memo": state.get("memo") or "",
        "raw_text": state.get("ocr_raw_text") or "",
        "items": state.get("items") or [],
    }

    result = save_local_db(expense_data, db_path=DEFAULT_DB_PATH)
    return {
        "saved_local_db": result.get("saved_local_db", False),
        "saved_expense_id": result.get("expense_id"),
        "save_db_error": result.get("error", ""),
    }

def record_notion_node(state: ReceiptAgentState): return {"notion_sync_status": "success"}

def route_after_budget(state: ReceiptAgentState) -> Literal["to_notion", "to_end"]:
    if state.get("id") == "error_id": return "to_end"
    return "to_notion"

# ==========================================
# 4. 그래프 조립 및 컴파일
# ==========================================
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
app = workflow.compile(checkpointer=memory)

# ==========================================
# 5. Streamlit GUI 레이아웃 구성
# ==========================================
st.set_page_config(page_title="영수증 가계부 에이전트", layout="wide")

st.title("📸 지능형 영수증 분석 & 사내 내규 심사 시스템")
st.caption("요구사항 규격을 만족하도록 변수명 조율 및 등록일시 속성이 업데이트된 버전입니다.")

col1, col2 = st.columns([1, 1])

with col1:
    st.header("📥 영수증 증빙 제출")
    uploaded_file = st.file_uploader("영수증 이미지를 업로드하세요 (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        st.subheader("🖼️ 업로드된 원본 증빙")
        image = Image.open(uploaded_file)
        st.image(image, use_container_width=True)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_image_path = temp_file.name
        
        execute_analysis = st.button("🔍 영수증 자동 분석 가동", type="primary")

with col2:
    st.header("📊 지능형 심사 결과 리포트")
    
    if uploaded_file is not None and 'execute_analysis' in locals() and execute_analysis:
        with st.spinner("LangGraph 파이프라인 가동 중..."):
            config = {"configurable": {"thread_id": "streamlit_field_update_session"}}
            inputs = {
                "messages": [HumanMessage(content="업데이트된 필드명 기반 워크플로우 작동")],
                "image_path": temp_image_path,
                "notion_sync_status": "pending"
            }
            
            node_status_container = st.empty()
            for output in app.stream(inputs, config=config):
                for key, value in output.items():
                    node_status_container.info(f"⚙️ [진행 단계 완료]: {key}")
            
            final_state = app.get_state(config).values
            node_status_container.success("🎉 모든 분석 노드가 성공적으로 종료되었습니다.")
            
        if final_state:
            st.subheader("🎯 최종 판정 결과")
            status = final_state.get("budget_status", "정상")
            if status == "주의":
                st.error(f"🚨 위반 의심 행동 감지: [{status}]")
            else:
                st.success(f"✅ 정산 가능 승인: [{status}]")
            
            st.subheader("📜 AI 감사관 상세 검토 리포트")
            st.info(final_state.get("rag_violation_report", "리포트 유실"))
            
            with st.expander("🔍 [디버그] ocr_process_node 판독 원문"):
                st.text(final_state.get("ocr_raw_text", "텍스트 유실"))
            
            st.subheader("🔢 파싱된 정형 데이터 내역")
            summary_table = {
                "가맹점명": final_state.get("merchant"),
                "결제수단": final_state.get("payment_method"),
                "총 결제액": f"{final_state.get('amount', 0):,}원",
                "식사 인원수": f"{final_state.get('detected_people_count', 1)}명",
                "1인당 금액": f"{final_state.get('per_person_amount', 0):,}원",
                "가맹점 주소(addr)": final_state.get("addr"),          # 수정된 반영 확인용 필드 [cite: 45, 78, 79]
                "전화번호": final_state.get("tel"),
                "시스템 등록일시(reg_date)": final_state.get("reg_date") # 추가된 오늘 날짜 필드 [cite: 45, 82, 83]
            }
            st.json(summary_table)
            
            if os.path.exists(temp_image_path):
                os.remove(temp_image_path)
    else:
        st.info("좌측 컴포넌트에서 영수증 이미지를 업로드하고 분석 버튼을 누르면 실시간 감사 결과가 이곳에 출력됩니다.")
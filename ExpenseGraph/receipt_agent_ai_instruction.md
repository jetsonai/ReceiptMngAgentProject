# AI 기반 영수증 지출 관리 에이전트 MVP 개발 지시서

## 1. 프로젝트 개요

### 프로젝트명
**Smart Receipt Expense Agent**

### 프로젝트 목적
이 프로젝트는 사용자가 입력하거나 업로드한 영수증 데이터를 분석하여 지출 정보를 구조화하고, 예산 상태를 판단한 뒤, 로컬 데이터베이스와 Notion에 기록하는 **AI 기반 지출 관리 백엔드**이다.

사용자는 Streamlit 화면에서 영수증 텍스트 또는 이미지에서 추출된 데이터를 입력하고, FastAPI 백엔드는 LangGraph 기반 에이전트 흐름을 통해 지출 항목을 분석한다. 분석된 결과는 로컬 DB에 저장되며, 필요 시 Notion 데이터베이스에도 동기화된다.

---

## 2. 사용 기술 스택

### Backend
- Python
- FastAPI
- SQLAlchemy
- MariaDB
- Pydantic
- Uvicorn

### Frontend / Prototype UI
- Streamlit

### AI / Agent
- LangGraph
- LangChain
- OpenAI API 또는 로컬 LLM
- RAG
- Embedding Model
- Vector DB: ChromaDB 또는 FAISS


### External Integration
- Notion API
- google sheet

### Development Tools
- VS Code
- Conda
- Git
- dotenv
- workbench

---

## 3. MVP 핵심 기능

### 3.1 영수증 데이터 입력
사용자는 다음 방식 중 하나로 영수증 데이터를 입력한다.

1. 영수증 텍스트 직접 입력
2. OCR 처리 후 추출된 텍스트 입력
3. JSON 형태의 영수증 데이터 입력

초기 MVP에서는 OCR 자체 구현은 필수 기능이 아니다. OCR 결과로 추정되는 텍스트를 입력받아 처리하는 것을 우선한다.

---

### 3.2 영수증 정보 구조화
AI는 비정형 영수증 텍스트에서 다음 정보를 추출한다.

| 필드 | 설명 | 예시 |
|---|---|---|
| store_name | 가맹점명 | 스타벅스 강남점 |
| purchased_at | 결제일시 | 2026-06-23 14:30 |
| total_amount | 총 결제금액 | 8500 |
| payment_method | 결제수단 | 카드 |
| items | 구매 항목 목록 | 아메리카노, 샌드위치 |
| category | 지출 카테고리 | 식비 |
| memo | 요약 메모 | 카페 지출 |

---
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
---

### 3.3 지출 카테고리 분류
AI는 영수증 내용을 기반으로 지출 카테고리를 분류한다.

기본 카테고리 예시는 다음과 같다.

- 식비
- 카페/간식
- 교통
- 쇼핑
- 생활용품
- 의료
- 교육
- 문화/여가
- 업무비
- 기타

카테고리 판단 기준은 RAG 문서로 관리할 수 있다.

---

### 3.4 예산 상태 판단
월별 예산 정보와 현재 누적 지출을 기준으로 예산 상태를 판단한다.

예산 상태는 다음 중 하나로 구분한다.

| 상태 | 조건 |
|---|---|
| SAFE | 예산의 70% 미만 사용 |
| WARNING | 예산의 70% 이상 90% 미만 사용 |
| DANGER | 예산의 90% 이상 사용 |
| OVER | 예산 초과 |

AI 응답에는 다음 정보를 포함한다.

- 이번 지출 금액
- 현재 월 누적 지출
- 월 예산
- 예산 사용률
- 예산 상태
- 사용자에게 보여줄 한 줄 코멘트

---

### 3.5 로컬 DB 저장
분석된 지출 정보는 로컬 DB에 저장한다.

초기 MVP에서는 SQLite를 사용하고, 이후 PostgreSQL로 확장 가능하게 설계한다.

---

### 3.6 Notion 기록
분석이 완료된 지출 내역을 Notion 데이터베이스에 기록한다.

Notion 연동은 MVP에서 선택 기능으로 구현한다.

환경변수에 Notion API 정보가 없으면 로컬 DB 저장까지만 수행한다.

---

## 4. 전체 시스템 구조

```text
사용자
  │
  ▼
Streamlit UI
  │
  │ REST API 요청
  ▼
FastAPI Backend
  │
  ▼
LangGraph Expense Agent
  │
  ├─ 1. 입력 분석
  ├─ 2. 영수증 정보 추출
  ├─ 3. RAG 기반 카테고리 판단
  ├─ 4. 예산 상태 계산
  ├─ 5. 로컬 DB 저장
  └─ 6. Notion 기록
```

---

## 5. LangGraph 에이전트 흐름

### 노드 구성

```text
START
  │
  ▼
analyze_input
  │
  ▼
extract_receipt
  │
  ▼
classify_category
  │
  ▼
check_budget
  │
  ▼
save_local_db
  │
  ▼
sync_notion
  │
  ▼
generate_response
  │
  ▼
END
```

### 각 노드 역할

#### analyze_input
- 사용자 입력 형식 확인
- 텍스트, JSON, OCR 결과 텍스트 여부 판단
- 필수 정보 누락 여부 확인

#### extract_receipt
- LLM을 사용하여 영수증 정보를 구조화
- Pydantic 모델 형식으로 반환
- 금액, 날짜, 상호명, 항목 정보를 추출

#### classify_category
- RAG 검색 결과를 참고하여 지출 카테고리 판단
- 카테고리 판단 근거를 함께 생성

#### check_budget
- 현재 월 누적 지출 조회
- 월 예산과 비교
- SAFE, WARNING, DANGER, OVER 중 하나로 상태 결정

#### save_local_db
- 구조화된 지출 데이터를 DB에 저장
- 저장 성공/실패 상태 반환

#### sync_notion
- Notion API 설정이 있으면 Notion DB에 기록
- 설정이 없으면 skip 처리

#### generate_response
- 사용자에게 보여줄 최종 응답 생성
- 지출 요약, 예산 상태, 조언 포함

---

## 6. 주요 API 설계

### 6.1 영수증 분석 API

```http
POST /api/receipts/analyze
```

#### Request Body

```json
{
  "receipt_text": "스타벅스 강남점\n아메리카노 4500\n샌드위치 6000\n합계 10500\n2026-06-23 14:30",
  "user_id": "demo-user"
}
```

#### Response Body

```json
{
  "store_name": "스타벅스 강남점",
  "purchased_at": "2026-06-23T14:30:00",
  "total_amount": 10500,
  "category": "카페/간식",
  "budget_status": "WARNING",
  "monthly_budget": 300000,
  "monthly_spent": 215000,
  "usage_rate": 71.67,
  "comment": "카페/간식 지출이 월 예산의 70%를 넘었습니다. 남은 기간 지출을 조금 조절해보세요."
}
```

---

### 6.2 지출 목록 조회 API

```http
GET /api/expenses
```

#### Query Parameters

| 파라미터 | 설명 |
|---|---|
| user_id | 사용자 ID |
| month | 조회 월, 예: 2026-06 |
| category | 선택 카테고리 |

---

### 6.3 예산 설정 API

```http
POST /api/budgets
```

#### Request Body

```json
{
  "user_id": "demo-user",
  "month": "2026-06",
  "total_budget": 300000,
  "category_budgets": {
    "식비": 150000,
    "카페/간식": 50000,
    "교통": 70000
  }
}
```

---

## 7. DB 설계 초안

### users

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer | PK |
| user_id | varchar | 사용자 식별자 |
| name | varchar | 사용자명 |
| created_at | datetime | 생성일 |

### expenses

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer | PK |
| user_id | varchar | 사용자 ID |
| store_name | varchar | 가맹점명 |
| purchased_at | datetime | 결제일시 |
| total_amount | integer | 총 금액 |
| payment_method | varchar | 결제수단 |
| category | varchar | 카테고리 |
| memo | text | 메모 |
| raw_text | text | 원본 영수증 텍스트 |
| notion_page_id | varchar | Notion 페이지 ID |
| created_at | datetime | 생성일 |

### expense_items

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer | PK |
| expense_id | integer | expenses FK |
| item_name | varchar | 항목명 |
| amount | integer | 항목 금액 |
| quantity | integer | 수량 |

### budgets

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer | PK |
| user_id | varchar | 사용자 ID |
| month | varchar | 기준 월 |
| total_budget | integer | 월 전체 예산 |
| created_at | datetime | 생성일 |

### category_budgets

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | integer | PK |
| budget_id | integer | budgets FK |
| category | varchar | 카테고리 |
| amount | integer | 카테고리별 예산 |

---

## 8. RAG 문서 구성

RAG는 카테고리 분류 기준, 예산 판단 규칙, 사용자 지출 관리 가이드를 검색하는 데 사용한다.

### 예시 문서

```text
식비: 일반 음식점, 도시락, 편의점 식사, 배달 음식은 식비로 분류한다.
카페/간식: 커피전문점, 디저트, 베이커리, 간식성 구매는 카페/간식으로 분류한다.
교통: 버스, 지하철, 택시, 주유, 주차비는 교통으로 분류한다.
업무비: 회사 업무를 위한 문구, 인쇄, 회의비, 출장비는 업무비로 분류한다.
```

### RAG 사용 위치
- classify_category 노드
- generate_response 노드
- 예산 조언 생성 시

---

## 9. 프로젝트 폴더 구조 제안

```text
smart-receipt-agent/
  backend/
    app/
      main.py
      core/
        config.py
      api/
        receipt_router.py
        expense_router.py
        budget_router.py
      schemas/
        receipt_schema.py
        expense_schema.py
        budget_schema.py
      models/
        expense_model.py
        budget_model.py
      services/
        receipt_service.py
        budget_service.py
        notion_service.py
        rag_service.py
      agents/
        expense_graph.py
        nodes.py
        state.py
      db/
        database.py
        init_db.py
      rag_docs/
        category_rules.md
        budget_rules.md
      tests/
        test_receipt_api.py
    requirements.txt
    .env.example

  frontend/
    streamlit_app.py
    requirements.txt

  docs/
    ai_instruction.md
    api_spec.md
    db_design.md

  README.md
```

---

## 10. 환경변수 예시

`.env.example`

```env
APP_NAME=Smart Receipt Expense Agent
ENV=local

DATABASE_URL=sqlite:///./receipt_agent.db

OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

NOTION_API_KEY=your-notion-api-key
NOTION_DATABASE_ID=your-notion-database-id

VECTOR_DB_PATH=./vector_store
```

---

## 11. AI 코딩 도우미에게 줄 개발 원칙

AI는 아래 원칙을 지켜서 코드를 작성한다.

1. MVP 우선으로 단순하게 구현한다.
2. FastAPI 백엔드와 Streamlit 화면을 분리한다.
3. 비즈니스 로직은 Streamlit이 아니라 FastAPI 서비스 계층에 둔다.
4. LangGraph 노드는 작고 명확하게 분리한다.
5. LLM 응답은 반드시 Pydantic 모델로 검증한다.
6. DB 저장 전 필수 필드 검증을 수행한다.
7. Notion 연동 실패가 전체 분석 실패로 이어지지 않게 한다.
8. 환경변수는 `.env`로 관리한다.
9. API 응답은 프론트에서 바로 사용하기 쉬운 JSON으로 반환한다.
10. 테스트 가능한 구조로 작성한다.

---

## 12. 우선 개발 순서

### 1단계: 프로젝트 기본 구조 생성
- backend FastAPI 프로젝트 생성
- frontend Streamlit 프로젝트 생성
- requirements.txt 작성
- .env.example 작성

### 2단계: DB 모델 생성
- expenses
- expense_items
- budgets
- category_budgets

### 3단계: 영수증 분석 API 구현
- 

### 4단계: LangGraph 연결
- State 정의
- Node 정의
- Graph 구성
- API에서 graph.invoke 호출

### 5단계: LLM 기반 영수증 구조화
- ocr_process_node
- analyze_expenditure_node

### 6단계: RAG 기반 카테고리 분류
- policy_rag_node
- 카테고리 규칙 문서 작성
- 벡터DB 생성
- 검색 결과를 기준으로 카테고리 판단

### 7단계: 예산 판단
- 월 예산 조회
- 누적 지출 계산
- 예산 상태 계산

### 8단계: DB 저장
- 분석 결과 저장
- 지출 목록 조회 API 구현

### 9단계: Notion 연동
- Notion API 설정
- 분석 결과 Notion DB 기록

### 10단계: Streamlit UI 구현
┌───────────────────────────────────────┬────────────────────────────────────-───┐
│          📥 영수증 증빙 제출           │         📊 지능형 심사 결과 리포트      │
│                                       │                                     -  │
│ 1. [Drag and Drop 파일 업로드]         │   - LangGraph 노드 진행 단계 실시간 알림-│
│ 2. 업로드 성공 시 원본 이미지 프리뷰     │   - 🎯 최종 판정 결과 (정상/주의 상태코드)│
│ 3. [🔍 영수증 자동 분석 가동] 버튼 클릭 │   - 📜 AI 감사관 상세 검토 리포트        │
│                                       │   - 🔢 파싱된 정형 데이터 내역 (JSON) -- │
└───────────────────────────────────────┴──────────────────────────────────────-─┘
---

## 13. 샘플 사용자 시나리오

### 시나리오 1: 영수증 분석
사용자가 Streamlit에 아래 영수증 텍스트를 입력한다.

```text
스타벅스 강남점
아메리카노 4500
치킨 샌드위치 6000
합계 10500
2026-06-23 14:30
카드결제
```

시스템은 다음 작업을 수행한다.

1. 영수증 텍스트 수신
2. 가맹점, 날짜, 항목, 총액 추출
3. 카테고리를 카페/간식으로 분류
4. 월 예산과 비교
5. 로컬 DB 저장
6. Notion에 기록
7. 사용자에게 분석 결과 반환

---

## 14. 최종 응답 예시

```json
{
  "summary": "스타벅스 강남점에서 10,500원을 사용했습니다.",
  "category": "카페/간식",
  "budget_status": "WARNING",
  "usage_rate": 71.67,
  "comment": "카페/간식 예산 사용률이 높아지고 있습니다. 이번 주 카페 지출을 조금 줄이면 좋습니다.",
  "saved_local_db": true,
  "synced_notion": true
}
```

---

## 15. 추후 확장 기능

MVP 이후 다음 기능을 추가할 수 있다.

- OCR 이미지 업로드
- 카드사 문자 자동 분석
- Gmail 영수증 자동 수집
- 월별 지출 리포트 생성
- 카테고리별 차트
- 이상 지출 탐지
- 반복 지출 탐지
- 예산 초과 알림
- 사용자별 예산 추천
- Notion 양방향 동기화
- Slack 또는 카카오 알림

---

## 16. AI에게 요청할 첫 작업

아래 순서대로 코드를 생성한다.

1. 위 폴더 구조를 기준으로 프로젝트 기본 파일을 생성한다.
2. FastAPI 서버가 실행되도록 `main.py`를 만든다.
3. `/health` API를 만든다.
4. SQLite 연결 설정을 만든다.
5. expenses, budgets 관련 SQLAlchemy 모델을 만든다.
6. `/api/receipts/analyze` API를 더미 응답으로 먼저 구현한다.
7. Streamlit에서 FastAPI API를 호출하는 기본 화면을 만든다.

## 17. 카테고리 분류 RAG 생성
```sh
# rag db 생성ㄷ
cd C:\gitwork\ReceiptMngAgentProject\backend
python -m app.services.rag_build --build

# rag 테스트
python -m app.services.rag_build --query "서울역 주차장 주차비 5000"
```
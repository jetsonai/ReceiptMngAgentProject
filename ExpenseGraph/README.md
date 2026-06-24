# 📸 지능형 영수증 분석 & 사내 내규 심사 시스템 (Receipt Agent v1.0)

LangGraph 파이프라인과 OpenAI GPT-4o Vision 기술을 결합하여, 업로드된 영수증 이미지의 항목을 분류하고 사내 외근/출장 지출 내규(RAG) 준수 여부를 자동으로 심사하여 가계부 데이터 규격으로 정형화해주는 스마트 증빙 자동화 시스템입니다.

---

## ✨ 주요 기능 및 특징
- **Vision AI OCR 노드**: 오픈소스의 한계를 넘어 구겨지거나 흐릿한 실제 종이 영수증 사진까지 `gpt-4o` 시각 모델을 통해 라인과 테이블 구조를 완벽하게 텍스트로 판독합니다.
- **파이썬 기반 다인원 정산 로직**: 음료나 공기밥 등 소액 사이드 메뉴를 제외한 '주요 식사 메뉴'의 수량을 파이크 코드로 정확히 합산하여 동반 인원수(N)를 도출하고 1인당 비용을 계산합니다.
- **사내 지출 내규 RAG 검증**: 추출된 1인당 비용을 기반으로 사내 지급 규정(예: 외근 석식 1인당 20,000원 한도 등)을 참조하여 위반 여부를 동적으로 심사합니다.
- **정형 데이터 규격화 및 오늘 날짜 주입**: 기획서 DB 필드 규칙을 준수하여 상점 주소(`addr`), 연락처(`tel`), 그리고 정산 시점의 오늘 날짜(`reg_date`)를 안전하게 주입합니다.

---

## 🛠️ 개발 환경 및 필수 패키지 설치

본 프로젝트는 Anaconda 가상환경(`ml_env`) 환경에서 테스트 및 최적화되었습니다.

### 1. 가상환경 활성화 및 필수 라이브러리 설치
터미널 또는 Anaconda Prompt를 열고 프로젝트 폴더로 이동한 뒤 아래 명령어를 순서대로 실행하세요.

```bash
# 가상환경 활성화 (본인의 환경 이름으로 변경 가능)
conda activate ml_env

# LangGraph, OpenAI, Streamlit 등 핵심 패키지 설치
pip install langgraph langchain-core langchain-openai langchain-community langchain-text_splitters chroma4py
pip install streamlit pillow python-dotenv fastapi

### 2. PyTorch 설치 (노트북 환경별 선택)
허깅페이스 관련 라이브러리 의존성 해결을 위해 PyTorch 설치가 필수적입니다. 본인의 하드웨어 사양에 맞춰 한 가지만 선택하여 설치하세요.

NVIDIA GPU(예: RTX 5070 등) 가속 환경 노트북:

```python
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```
일반 강의장 및 사무용 노트북 (CPU 전용 환경):

```python
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

```

### 환경 변수 세팅

```powershell
# 프로젝트 루트의 .env.example을 복사해 .env 파일 생성 후 값 입력
Copy-Item ..\.env.example ..\.env

# 즉시 세션 반영이 필요하면 아래처럼 설정
$env:OPENAI_API_KEY=
$env:AWS_MYSQL_HOST=
$env:AWS_MYSQL_PORT=
$env:AWS_MYSQL_USER=
$env:AWS_MYSQL_PASSWORD=
$env:AWS_MYSQL_DATABASE=
```
## 필드 설명
    # 기획안 DB 속성 반영
    id: str                  # 지출 항목 고유 식별자  
    spent_at: str            # 지출 날짜 
    merchant: str            # 상점명 또는 사용처 
    amount: int              # 지출 총 금액 
    payment_method: str      # 결제수단 
    category: str            # 소비 카테고리 
    memo: str                # 사용자 메모 또는 OCR 원문 요약 
    source: str              # 입력 경로 ('image' 또는 'text') 
    budget_status: str       # 예산 평가 결과 ('정상' / '주의' / '경고' / '초과') 
    notion_sync_status: str  # Notion 기록 결과 ('success' / 'failed' / 'skipped') 
    
    # 🌟 요구사항에 맞게 변수명 수정 및 신규 필드 추가
    addr: str                # 상점 주소 (변수명 address -> addr 변경) 
    tel: str                 # 상점 전화번호 (TELL) 
    reg_date: str            # 🌟 신규 추가: 등록일시 (REG_DATE) 
    

### 카테고리 분류 RAG 생성
```sh
# rag db 생성
cd C:\gitwork\ReceiptMngAgentProject\backend
python -m app.services.rag_build --build

# rag 테스트
python -m app.services.rag_build --query "서울역 주차장 주차비 5000"
```

### BackEnd 실행 방법

```powershell
# 가상환경 상에서 실행
cd ..\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### FrontEnd 실행 방법

```python
# 가상환경 상에서 실행
streamlit run app.py
```

### 관리자 페이지 실행 방법

```bash
# DB에 저장된 영수증/지출 내역 조회
streamlit run admin_app.py
```

### Streamlit GUI 사용 가이드

Streamlit GUI 사용 가이드
<img width="601" height="665" alt="image" src="https://github.com/user-attachments/assets/b4581965-8c9e-4192-8ad2-c147bbecf9da" />


영수증 파일 업로드: 좌측 영역의 Browse files 버튼을 눌러 준비된 영수증 이미지(PNG, JPG, JPEG)를 업로드합니다.

원본 이미지 확인: 파일이 성공적으로 수신되면 브라우저 화면 좌측에 영수증 원본 사진이 선명하게 노출됩니다.

분석 가동: 이미지 아래 생성된 [🔍 영수증 자동 분석 가동] 주요 버튼을 클릭합니다.

실시간 상태 관제: 우측 리포트 창에서 LangGraph의 워크플로우 통과 정보(upload_receipt ➔ ocr_process ➔ analyze_expenditure ➔ policy_rag ➔ evaluate_budget)가 실시간 프로그래시브 형태로 바인딩되는지 확인합니다.

최종 결과 및 AI 리포트 확인:

사내 규정을 만족하면 초록색 패널로 정상, 초과 위반 시 빨간색 패널로 주의 배지가 표시됩니다.

1인당 금액 산출의 근거 및 위반 여부를 담은 상세 요약 리포트 텍스트가 화면에 노출됩니다.

최하단 JSON 컴포넌트를 통해 기획안 규격에 명시된 merchant, payment_method, amount, detected_people_count, per_person_amount, 그리고 고정 매핑된 addr와 오늘 날짜 시간 정보(reg_date)를 한눈에 검증할 수 있습니다.

디버그 익스팬더 탭 활용: 팀원 간 개발 검증을 위해 추가된 [디버그] ocr_process_node 판독 원문 탭을 클릭하여, 내가 담당한 OCR 노드가 실사 이미지에서 가로축 테이블 텍스트를 수량 깨짐 없이 얼마나 완벽하게 스캐닝했는지 실시간 텍스트로 대조할 수 있습니다.




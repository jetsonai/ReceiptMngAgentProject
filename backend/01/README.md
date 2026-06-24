# Expense Notion Record Agent

이 저장소는 영수증/지출 파이프라인 중 `7. 노션 기록` 역할만 담당한다.

## 현재 유효한 작업

- `01/notion_record_agent.py`
  - OCR/분석/예산평가 결과를 받아 Notion 페이지를 생성한다.
  - LangGraph로 `prepare -> write` 흐름을 구성한다.
  - `NOTION_TOKEN`과 `NOTION_DATABASE_ID`, `OPENAI_API_KEY`는 .env 파일에서 읽는다. 
  - 내부 구현은 `notion_constants.py`, `notion_config.py`, `notion_models.py`, `notion_text.py`, `notion_payload.py`, `notion_client.py`로 분리했다.

## 입력 데이터 구조

`ExpenseRecord`에 아래 값이 들어온다.

- `id`
- `user_id`
- `spent_at` (지출일자)
- `merchant`
- `amount` (지출금액)
- `payment_method`
- `category` (소비 카테고리)
- `memo`
- `source` (입력 경로)
- `budget_status` (예산평가결과)
- `notion_sync_status` (노션기록결과)
- `addr`
- `tell`
- `reg_date` (등록일시)

## Notion DB 속성        

회의에서 정한 속성명 기준으로 기록한다.

| 속성명 | Notion 타입 | 옵션/메모 |
|---|---|---|
| `지출 항목 고유 식별자` | `title` | 페이지 제목 |
| `지출날짜` | `date` | 지출일 |
| `상점명` | `rich_text` | 가맹점 |
| `지출 금액` | `number` | 지출금액 |
| `결제수단` | `select` | `신영카드`, `현금영수증` |
| `소비 카테고리` | `select` | `식비`, `교통`, `숙박`, `일비`, `항공`, `배송비`, `회의비`, `기타` |
| `OCR 원문` | `rich_text` | 원문 저장 |
| `OCR 원문 요약` | `rich_text` | 요약 저장 |
| `입력 경로` | `rich_text` | 예: `api`, `image_upload` |
| `예산 평가 결과` | `multi_select` | `미평가`, `예산 내`, `예산 초과`, `주의` |
| `Notion 기록 결과` | `multi_select` | `대기`, `성공` |
| `주소` | `rich_text` | 주소 |
| `전화번호` | `rich_text` | 전화번호 |
| `등록일시` | `rich_text` | ISO 문자열 저장 |

## 코드 -> Notion DB 매핑

| 코드 필드 | DB 속성명 | Notion 타입 | 메모 |
|---|---|---|---|
| `record.id` | `지출 항목 고유 식별자` | `title` | 고유 식별자 |
| `record.spent_at` | `지출날짜` | `date` | 지출일자 |
| `record.merchant` | `상점명` | `rich_text` | 가맹점명 |
| `record.amount` | `지출 금액` | `number` | 지출금액 |
| `record.payment_method` | `결제수단` | `select` | 결제수단 옵션 |
| `record.category` | `소비 카테고리` | `select` | 소비 카테고리 옵션 |
| `record.memo` | `OCR 원문 요약` | `rich_text` | 메모를 요약으로 저장 |
| `record.source` | `입력 경로` | `rich_text` | 입력 출처 |
| `record.budget_status` | `예산 평가 결과` | `multi_select` | 예산평가 결과 |
| `record.notion_sync_status` | `Notion 기록 결과` | `multi_select` | 동기화 상태 |
| `record.addr` | `주소` | `rich_text` | 주소 |
| `record.tell` | `전화번호` | `rich_text` | 전화번호 |
| `record.reg_date` | `등록일시` | `rich_text` | 등록일시 문자열 |
| 파생 텍스트 | `OCR 원문` | `rich_text` | 본문용 조합 텍스트 |

## 실행 방법

```bash
python 01/notion_record_agent.py
```

키 검증만 먼저 하려면:

```bash
python 01/env_healthcheck.py
```

FastAPI로 확인하려면:

```bash
uvicorn notion_api:app --reload --app-dir 01
```

- `GET /health/keys`
- `POST /notion/test-record`

## 회의 데모 흐름

팀원들에게는 아래 순서로 보여준다.

1. `uvicorn notion_api:app --reload --app-dir 01`로 서버 실행
2. `http://127.0.0.1:8000/docs` 접속
3. `GET /health/keys` 실행해서 OpenAI / Notion 키 정상 여부 확인
4. `POST /notion/test-record` 실행해서 실제 Notion 기록 생성 확인
5. Notion 페이지가 생성된 결과를 화면으로 확인

##  순서

notion_record_agent.py   # graph + 실행 진입점
notion_service.py        # payload 생성 + Notion 호출
notion_record_agent.py   # 전체 흐름 조립: prepare -> write
notion_payload.py        # ExpenseRecord를 Notion API payload로 변환
notion_client.py         # Notion API에 실제 요청 보내기
notion_text.py           # Notion 본문/제목 만들기
notion_models.py         # 데이터 모델 구조 정의
notion_constants.py      # Notion 속성명, 상태값 상수
notion_config.py         # 환경변수 읽기
env_loader.py            # .env 파일 찾고 로드
env_healthcheck.py       # 키가 정상인지 점검
notion_api.py            # FastAPI 데모용 API


1. 이 저장소가 담당하는 범위 설명
   - 지출 파이프라인 중 `Notion 기록`만 담당
2. 파일 구조 설명
   - `notion_api.py`가 데모 진입점
   - 나머지는 설정, 모델, payload, Notion 호출로 분리
3. 키 확인 시연
   - `/health/keys`로 OpenAI / Notion token 정상 여부 확인
4. 실제 기록 시연
   - `/notion/test-record`로 샘플 지출 1건 기록
5. Notion 결과 확인
   - 생성된 페이지 URL을 보여주고 기록 완료를 설명

환경변수:

- `NOTION_TOKEN`
- `NOTION_DATABASE_URL`  
  - 권장값, 여기서 `database_id`를 자동 추출한다.
- `NOTION_DATABASE_ID`  
  - 선택값, 직접 넣어도 된다.
- `NOTION_VERSION`  
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

`.env`는 이 폴더의 상위 경로에서 자동으로 찾는다.

## 내일 회의 이후 확장 후보

- OCR 결과와 `ExpenseRecord` 자동 매핑
- 예산평가결과를 `예산평가결과`에 연결
- 노션기록결과를 `대기/성공 `로 더 세분화
- 팀 전체 파이프라인과 인터페이스 통합

## 노션에서 데이터베이스 id 찾는 방법
Notion에서 `NOTION_DATABASE_URL` 또는 database id 찾는 방법은 이렇게 하면 돼요.

1. Notion에서 지출 기록용 **데이터베이스 페이지**를 연다.
2. 오른쪽 위 `공유` 또는 `Share` 버튼을 누른다.
3. `링크 복사` / `Copy link`를 누른다.
4. 복사된 URL을 `.env`의 `NOTION_DATABASE_URL=` 뒤에 그대로 붙여 넣는다.

예시는 이런 형태예요.

```env
NOTION_DATABASE_URL=https://www.notion.so/workspace-name/abcdef1234567890abcdef1234567890?v=...
```

여기서 database id는 보통 URL 안의 **32자리 영문+숫자 조합**입니다.

예를 들어 URL이 이렇다면:

```text
https://www.notion.so/myspace/Expense-DB-abcdef1234567890abcdef1234567890?v=123
```

database id는:

```text
abcdef1234567890abcdef1234567890
```

현재 코드에서는 `NOTION_DATABASE_URL`을 넣으면 자동으로 database id를 뽑도록 되어 있어서, 직접 `NOTION_DATABASE_ID`를 찾지 않아도 됩니다. 가장 쉬운 방법은 **데이터베이스 링크 전체를 `NOTION_DATABASE_URL`에 넣는 것**이에요.

그리고 중요한 것 하나:  
Notion integration을 만든 뒤에, 해당 데이터베이스 페이지에서 `공유` 버튼을 눌러 **내 integration을 초대/연결**해야 합니다. 이걸 안 하면 database id를 넣어도 API가 접근을 못 해요.

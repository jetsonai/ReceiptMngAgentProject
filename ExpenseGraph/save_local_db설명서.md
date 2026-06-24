# save_local_db.py README

## 1. 개요
`save_local_db.py`는 구조화된 영수증/지출 데이터를 아래 DB에 저장합니다.
- 로컬 SQLite DB (기본)
- AWS/MySQL DB (선택)

이 파일은 CLI 직접 테스트와 다른 모듈에서의 함수 재사용을 모두 지원합니다.

---

## 2. 주요 함수

### `save_local_db(expense_data, db_path=DEFAULT_DB_TARGET)`
지출 레코드 1건과 연결된 품목 행을 함께 저장합니다.

**파라미터:**
- `expense_data` (dict): 지출 데이터
- `db_path` (str): DB 경로 또는 MySQL URL (기본값: DEFAULT_DB_TARGET)

**반환값 (dict):**
```python
{
  "saved_local_db": True,        # 성공/실패
  "expense_id": 5,                # 삽입된 레코드 id
  "item_count": 2,                # 삽입된 품목 개수
  "db_path": "receipt_agent.db"  # 대상 DB
}
```

**사용 예시:**
```python
from save_local_db import save_local_db

data = {
    "user_id": "user123",
    "store_name": "카페",
    "purchased_at": "2026-06-24 10:00:00",
    "total_amount": 5000,
    "payment_method": "카드",
    "category": "음료",
    "items": [
        {"item_name": "아메리카노", "amount": 5000, "quantity": 1}
    ]
}

result = save_local_db(data)
print(result["saved_local_db"])  # True
print(result["expense_id"])       # 5
```

---

### `get_latest_expense(db_path=DEFAULT_DB_TARGET)`
대상 DB에서 가장 최근 지출 레코드를 반환합니다.

**파라미터:**
- `db_path` (str): DB 경로 또는 MySQL URL (기본값: DEFAULT_DB_TARGET)

**반환값:**
```python
{
  "id": 5,
  "user_id": "user123",
  "store_name": "카페",
  "purchased_at": "2026-06-24 10:00:00",
  "total_amount": 5000,
  "category": "음료",
  "created_at": "2026-06-24 09:30:15"
}
```

**사용 예시:**
```python
from save_local_db import get_latest_expense

latest = get_latest_expense()
if latest:
    print(f"최신 지출: {latest['store_name']}, {latest['total_amount']}원")
```

---

### `get_expense_items(expense_id, db_path=DEFAULT_DB_TARGET)`
특정 지출에 연결된 모든 품목을 반환합니다.

**파라미터:**
- `expense_id` (int): 지출 id
- `db_path` (str): DB 경로 또는 MySQL URL (기본값: DEFAULT_DB_TARGET)

**반환값:**
```python
[
  {
    "id": 9,
    "expense_id": 5,
    "item_name": "아메리카노",
    "amount": 5000,
    "quantity": 1
  }
]
```

**사용 예시:**
```python
from save_local_db import get_expense_items

items = get_expense_items(5)
for item in items:
    print(f"- {item['item_name']}: {item['amount']}원 x {item['quantity']}")
```

---

### `test_connection(db_target=DEFAULT_DB_TARGET)`
DB 연결 가능 여부와 스키마 준비 상태를 확인합니다.

**파라미터:**
- `db_target` (str): DB 경로 또는 MySQL URL (기본값: DEFAULT_DB_TARGET)

**반환값:**
```python
{
  "connected": True,
  "backend": "sqlite",      # 또는 "mysql"
  "probe": 1
}
```

**사용 예시:**
```python
from save_local_db import test_connection

result = test_connection()
if result["connected"]:
    print(f"✓ {result['backend']} 연결 성공")
```

---

### `build_dummy_expense_data()`
CLI 스모크 테스트용 더미 payload를 생성합니다.

**파라미터:** 없음

**반환값:**
```python
{
  "user_id": "demo-user",
  "store_name": "사천루",
  "purchased_at": "2026-06-23 16:30:00",
  "total_amount": 11000,
  "payment_method": "신용카드",
  "category": "점심식사",
  "memo": "주간 장",
  "items": [
    {"item_name": "식료품", "amount": 30000, "quantity": 1},
    {"item_name": "생활용품", "amount": 15000, "quantity": 1}
  ]
}
```

**사용 예시:**
```python
from save_local_db import build_dummy_expense_data, save_local_db

dummy = build_dummy_expense_data()
result = save_local_db(dummy)
```

---

### `_normalize_expense_payload(expense_data)`
입력 데이터를 표준 형식으로 정규화합니다. (내부 함수)

**동작:**
- 여러 키 스타일을 통일
- `spent_at` → `purchased_at`
- `merchant` → `store_name`
- `amount` → `total_amount`
- `ocr_raw_text` → `raw_text`

**사용 위치:** `save_local_db()` 내부에서 자동 호출

---

### `_normalize_items(items)`
품목 리스트를 표준 형식으로 정규화합니다. (내부 함수)

**동작:**
- 각 품목의 키 통일
- `name` → `item_name`
- `total` → `amount`
- `count` → `quantity`
- 기본값 보충 (quantity=1 등)

**사용 위치:** `save_local_db()` 내부에서 자동 호출

---

### `ensure_schema(conn)`
DB에 필요한 테이블이 없으면 생성합니다. (내부 함수)

**동작:**
- SQLite: 5개 테이블 생성 (users, expenses, expense_items, budgets, category_budgets)
- MySQL: 5개 테이블 생성 (expens_user, expenses, expense_items, budgets, category_budgets)

**사용 위치:** `save_local_db()`, `get_*()`, `test_connection()` 에서 자동 호출

---

## 2-1. DB 입력 부분 상세

### save_local_db() 함수 내 입력 로직

**MySQL 입력 로직** [save_local_db.py 라인 322-390](ExpenseGraph/save_local_db.py#L322)
```python
if _is_mysql_connection(conn):
    with conn.cursor() as cursor:
        # 1. 사용자 등록 [라인 333-340]
        cursor.execute(
            """
            INSERT IGNORE INTO expens_user (user_id, name, create_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, name, now_datetime)
        )
        
        # 2. 지출 레코드 삽입 [라인 345-376]
        cursor.execute(
            """
            INSERT INTO expenses (
                spent_at, merchant, addr, tel, reg_date, amount,
                payment_method, category, items,
                detected_people_count, per_person_amount, memo, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (spent_at, merchant, addr, tel, reg_date, amount, ...)
        )
        expense_id = int(cursor.lastrowid)  # 삽입된 id 가져오기
        
        # 3. 품목 삽입 (여러 건) [라인 383-390]
        if items:
            cursor.executemany(
                """
                INSERT INTO expense_items (expense_id, item_name, amount, quantity)
                VALUES (%s, %s, %s, %s)
                """,
                [(expense_id, item_name, amount, quantity), ...]
            )
        _commit(conn)  # MySQL은 명시적 커밋 필요
```

**SQLite 입력 로직** [save_local_db.py 라인 391-449](ExpenseGraph/save_local_db.py#L391)
```python
else:  # SQLite
    with conn:
        # 1. 사용자 등록 [라인 397-407]
        conn.execute(
            """
            INSERT INTO users (user_id, name, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (user_id, name, now)
        )
        
        # 2. 지출 레코드 삽입 [라인 410-431]
        cur = conn.execute(
            """
            INSERT INTO expenses (
                user_id, store_name, purchased_at, total_amount,
                payment_method, category, memo, raw_text, notion_page_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, store_name, purchased_at, total_amount, ...)
        )
        expense_id = int(cur.lastrowid)  # 삽입된 id 가져오기
        
        # 3. 품목 삽입 (여러 건) [라인 442-449]
        if items:
            conn.executemany(
                """
                INSERT INTO expense_items (expense_id, item_name, amount, quantity)
                VALUES (?, ?, ?, ?)
                """,
                [(expense_id, item_name, amount, quantity), ...]
            )
        # SQLite는 with 블록 종료 시 자동 커밋
```

### 입력 흐름 요약
1. 입력 데이터 정규화 [라인 302](ExpenseGraph/save_local_db.py#L302)
2. 필수 필드 검증 [라인 304-310](ExpenseGraph/save_local_db.py#L304)
3. DB 연결 [라인 312](ExpenseGraph/save_local_db.py#L312)
4. 스키마 확인 [라인 315](ExpenseGraph/save_local_db.py#L315)
5. **MySQL vs SQLite 분기** [라인 322](ExpenseGraph/save_local_db.py#L322)
6. 사용자, 지출, 품목 순차 삽입
7. 결과 반환 [라인 480](ExpenseGraph/save_local_db.py#L480)

---

## 2-2. 내부 헬퍼 함수들

### DB 연결 관련
- **`get_connection(db_target)`**: SQLite/MySQL 연결을 구분해서 생성
- **`_connect_mysql(db_target)`**: MySQL URL을 파싱해서 연결 생성
- **`_is_mysql_target(db_target)`**: URL이 MySQL 형식인지 판별
- **`_is_mysql_connection(conn)`**: 연결 객체가 MySQL인지 판별

### SQL 실행 관련
- **`_execute(conn, sql, params)`**: SQLite/MySQL 둘 다 지원하는 단일 실행
- **`_executemany(conn, sql, params_list)`**: 배치 INSERT/UPDATE 실행
- **`_fetchone(conn, sql, params)`**: 1개 행만 조회
- **`_fetchall(conn, sql, params)`**: 모든 행 조회

### 트랜잭션 관련
- **`_commit(conn)`**: 변경사항 커밋 (MySQL용)
- **`_rollback(conn)`**: 변경사항 롤백 (MySQL용)

### 유틸리티
- **`_now_str()`**: 현재 시각을 "YYYY-MM-DD HH:MM:SS" 형식으로 반환
- **`_normalize_items(items)`**: 품목 리스트를 표준 형식으로 정규화
- **`_normalize_expense_payload(expense_data)`**: 입력 데이터를 표준 형식으로 정규화
- **`_print_db_summary(db_path)`**: DB의 expense/item 개수 및 최신 레코드 출력 (CLI용)

### 필수 논리 필드 (정규화 후 기준)
- `user_id`
- `store_name` (or `merchant`)
- `purchased_at` (or `spent_at`)
- `total_amount` (or `amount`)

### 자주 쓰는 키 매핑
- `spent_at` -> `purchased_at`
- `merchant` -> `store_name`
- `amount` -> `total_amount`
- `ocr_raw_text` -> `raw_text`
- `id` -> fallback for `user_id`

### 품목(Item) 키 매핑
각 품목은 아래 두 스타일 중 아무거나 사용할 수 있습니다.
- `item_name` or `name`
- `amount` or `total`
- `quantity` or `count`

---

## 4. DB 대상 설정

### 기본 대상
- `DEFAULT_DB_PATH`: `ExpenseGraph/receipt_agent.db`
- `DEFAULT_DB_TARGET`: `DATABASE_URL` 환경변수가 있으면 해당 값, 없으면 로컬 SQLite 경로

### MySQL 대상 형식
아래 중 하나를 사용합니다.
- `mysql://user:password@host:3306/dbname`
- `mysql+pymysql://user:password@host:3306/dbname`

---

## 5. CLI 사용법
`ExpenseGraph` 디렉터리에서 실행합니다.

### A. 기본 실행 (로컬 SQLite + AWS 환경변수 설정 시 MySQL 추가 저장)
```bash
python save_local_db.py
```

### B. DB 대상 직접 지정
```bash
python save_local_db.py --db-target "mysql://root:admin@13.209.64.184:3306/db"
```

### C. 임시 SQLite 스모크 테스트
```bash
python save_local_db.py --use-temp-db
```

### D. 연결 확인만 수행
```bash
python save_local_db.py --test-connection
```

---

## 6. AWS MySQL 환경변수
아래 값이 설정되어 있으면 기본 실행 시 MySQL에도 추가 저장합니다.
- `AWS_MYSQL_HOST`
- `AWS_MYSQL_PORT` (optional, default `3306`)
- `AWS_MYSQL_USER`
- `AWS_MYSQL_PASSWORD`
- `AWS_MYSQL_DATABASE`

필수 Python 패키지:
- `pymysql`

설치:
```bash
python -m pip install pymysql
```

---

## 7. 실행 결과 예시
실행이 성공하면 아래 정보가 출력됩니다.
- 저장 결과 딕셔너리
- `expenses`, `expense_items` 요약 개수
- 최신 삽입 레코드
- 최신 품목 행 목록
- (환경변수 설정 시) MySQL 저장 결과

---

## 8. Troubleshooting

### `pymysql is required for MySQL connections`
원인: `python` 명령이 실제로 사용하는 인터프리터에 `pymysql`이 설치되어 있지 않습니다.

해결:
1. 인터프리터 확인:
   ```bash
   python -c "import sys; print(sys.executable)"
   ```
2. 해당 인터프리터에 설치:
   ```bash
   python -m pip install pymysql
   ```

### SQLite increases but MySQL does not
확인 사항:
- 현재 터미널 세션에 AWS 환경변수가 설정되어 있는지
- MySQL host/database 값이 정확한지
- 실행 로그에 `[MySQL 저장] ...` 문구가 출력되는지

---

## 9. 연동 메모
이 모듈은 backend 워크플로우 노드에서 호출하는 것을 기준으로 작성되었습니다.
payload 정규화가 내장되어 있어서 `backend/app/main.py`의 state 필드 데이터도 대부분 추가 매핑 코드 없이 바로 저장할 수 있습니다.

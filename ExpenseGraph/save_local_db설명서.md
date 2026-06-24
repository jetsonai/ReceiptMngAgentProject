# save_local_db.py 설명서 (최신)

## 1. 목적
`save_local_db.py`는 영수증/지출 데이터를 저장하고 조회하는 공용 DB 유틸리티 모듈입니다.

지원 백엔드:
- SQLite (기본)
- MySQL (환경변수 또는 URL 지정 시)

주요 사용 위치:
- 백엔드 워크플로우의 DB 저장 노드
- CLI 스모크 테스트
- 단위/통합 테스트 보조

---

## 2. 동작 개요
저장 흐름은 아래 순서로 진행됩니다.

1. 환경 로드 (`_load_environment`)
2. DB 대상 해석 (`_effective_db_target`, `_resolve_db_target`)
3. 연결 생성 (`get_connection`)
4. 스키마 보장 (`ensure_schema`)
5. payload 정규화 (`_normalize_expense_payload`, `_normalize_items`)
6. MySQL/SQLite 분기 저장 (`save_local_db`)
7. 결과 딕셔너리 반환

---

## 3. 환경 로드 규칙
`_load_environment()`는 실행 디렉터리와 무관하게 `.env`를 탐색합니다.

탐색 순서:
1. `ExpenseGraph/.env`
2. 프로젝트 루트 `.env`
3. 현재 작업 디렉터리 `.env`
4. 위 경로가 없으면 `load_dotenv()` 기본 동작

---

## 4. DB 대상 결정 규칙
DB 대상은 아래 우선순위로 결정됩니다.

1. 함수 인자로 전달된 `db_target`/`db_path`
2. `DATABASE_URL`
3. `AWS_MYSQL_*` 조합
4. 기본 SQLite 파일 (`ExpenseGraph/receipt_agent.db`)

MySQL URL 생성 형식:
- `mysql://user:password@host:port/dbname`

주의:
- 사용자명/비밀번호는 URL 인코딩되어 생성됩니다.
- 연결 시에는 URL 디코딩 후 실제 인증에 사용됩니다.

---

## 5. 주요 공개 함수

### 5.1 `save_local_db(expense_data, db_path=None)`
지출 1건 + 품목 목록을 저장합니다.

필수 논리 필드(정규화 후 기준):
- `user_id`
- `store_name` (또는 `merchant`)
- `purchased_at` (또는 `spent_at`)
- `total_amount` (또는 `amount`)

성공 반환 예시:
```python
{
    "saved_local_db": True,
    "expense_id": 13,
    "item_count": 2,
    "db_path": "mysql://..."  # 또는 sqlite 경로
}
```

실패 반환 예시:
```python
{
    "saved_local_db": False,
    "expense_id": None,
    "error": "..."
}
```

---

### 5.2 `get_latest_expense(db_path=None)`
가장 최근 지출 1건을 조회합니다.

- MySQL: `spent_at`, `merchant`, `amount` 등 MySQL 스키마 컬럼 반환
- SQLite: `user_id`, `store_name`, `total_amount` 등 SQLite 스키마 컬럼 반환

---

### 5.3 `get_expense_items(expense_id, db_path=None)`
특정 지출(`expense_id`)에 연결된 품목 행을 전체 조회합니다.

---

### 5.4 `test_connection(db_target=None)`
연결 + 스키마 접근 가능 여부를 점검합니다.

반환 예시:
```python
{
    "connected": True,
    "backend": "mysql",  # 또는 sqlite
    "probe": 1
}
```

---

### 5.5 `build_dummy_expense_data()`
CLI/테스트용 더미 payload를 생성합니다.

---

## 6. 내부 헬퍼 함수

### DB 연결 관련
- `_resolve_db_target(default_target)`
- `_effective_db_target(db_target)`
- `_is_mysql_target(db_target)`
- `_connect_mysql(db_target)`
- `_is_mysql_connection(conn)`
- `get_connection(db_target)`

### SQL 실행/조회 래퍼
- `_execute(conn, sql, params)`
- `_executemany(conn, sql, params_list)`
- `_fetchone(conn, sql, params)`
- `_fetchall(conn, sql, params)`
- `_commit(conn)`
- `_rollback(conn)`

### 정규화/유틸
- `_now_str()`
- `_to_int(value)`
- `_normalize_expense_payload(expense_data)`
- `_normalize_items(items)`
- `_print_db_summary(db_path)`

---

## 7. 정규화 규칙

### 상위 필드 매핑
- `spent_at` -> `purchased_at`
- `merchant` -> `store_name`
- `amount` -> `total_amount`
- `ocr_raw_text` -> `raw_text`
- `id` -> `user_id` 대체값

### 품목 필드 매핑
- `name` -> `item_name`
- `total` -> `amount`
- `count` -> `quantity`

금액/수량은 `_to_int`로 문자열(`12,000원`) 형태도 정수로 변환합니다.

---

## 8. 스키마 차이 요약

### MySQL
- `expens_user`
- `expenses` (컬럼: `spent_at`, `merchant`, `addr`, `tel`, `reg_date`, `amount`, ...)
- `expense_items`
- `budgets`
- `category_budgets`

### SQLite
- `users`
- `expenses` (컬럼: `user_id`, `store_name`, `purchased_at`, `total_amount`, ...)
- `expense_items`
- `budgets`
- `category_budgets`

---

## 9. CLI 사용법
작업 디렉터리: `ExpenseGraph`

1. 기본 실행
```bash
python save_local_db.py
```

2. 대상 직접 지정
```bash
python save_local_db.py --db-target "mysql://user:password@host:3306/db"
```

3. 임시 SQLite 테스트
```bash
python save_local_db.py --use-temp-db
```

4. 연결 점검만 수행
```bash
python save_local_db.py --test-connection
```

---

## 10. 백엔드 연동
백엔드 워크플로우의 `save_db` 노드에서 이 모듈을 호출합니다.

- 백엔드 state 값을 받아 `save_local_db()`로 전달
- `merchant/spent_at/amount` 스타일 payload도 정규화 로직으로 저장 가능

---

## 11. 트러블슈팅

### 11.1 MySQL에 저장되지 않고 SQLite에만 저장될 때
확인 순서:
1. `.env`에 `DATABASE_URL` 또는 `AWS_MYSQL_*` 값이 실제 입력되어 있는지
2. 실행한 프로세스를 재시작했는지
3. `test_connection()` 결과의 `backend`가 `mysql`인지

---

### 11.2 `pymysql is required for MySQL connections`
현재 인터프리터에 `pymysql`이 설치되지 않은 상태입니다.

```bash
python -m pip install pymysql
```

---

### 11.3 URL 비밀번호에 특수문자가 있을 때
이 모듈은 URL 인코딩/디코딩을 처리하도록 구현되어 있습니다.
그래도 인증 오류가 나면 실제 계정 비밀번호와 DB 권한을 점검하세요.

---

## 12. 관련 파일
- `ExpenseGraph/save_local_db.py`
- `ExpenseGraph/aws_test.py` (DB 연결/쓰기 스모크 테스트 전용)
- `backend/app/main.py` (워크플로우 연동)

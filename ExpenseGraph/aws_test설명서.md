# aws_test.py 설명서 (최신)

## 1. 목적
`aws_test.py`는 AWS RDS MySQL 연결 상태를 빠르게 점검하는 스모크 테스트 스크립트입니다.

주요 목표:
- 접속 가능 여부 확인
- 계정/권한/DB명 설정 오류 조기 발견
- 실제 쓰기 가능 여부 확인 (`--write-test`)

이 파일은 애플리케이션 런타임 필수 모듈이 아니라, 진단/운영 점검용 도구입니다.

---

## 2. 동작 개요
실행 시 아래 순서로 동작합니다.

1. `.env` 로드 (`_load_environment`)
2. 환경변수에서 MySQL 설정 조합 (`_build_config_from_env`)
3. 필수 설정 검증 (`_validate_config`)
4. DB 연결 후 기본 쿼리 실행 (`test_mysql_connection`)
5. 옵션 지정 시 테스트 테이블 생성 및 INSERT 수행 (`--write-test`)

---

## 3. 환경 로드 규칙
`_load_environment()`는 실행 위치와 무관하게 `.env`를 탐색합니다.

탐색 순서:
1. `ExpenseGraph/.env`
2. 프로젝트 루트 `.env`
3. 현재 작업 디렉터리 `.env`
4. 없으면 `load_dotenv()` 기본 동작

---

## 4. 사용 환경변수
기본적으로 아래 키를 사용합니다.

- `AWS_MYSQL_HOST`
- `AWS_MYSQL_PORT` (기본값 `3306`)
- `AWS_MYSQL_USER`
- `AWS_MYSQL_PASSWORD`
- `AWS_MYSQL_DATABASE`

필수 누락 키(`host`, `user`, `password`, `database`)가 있으면 실행을 중단하고 명확한 에러를 출력합니다.

---

## 5. 주요 함수

### 5.1 `_build_config_from_env()`
환경변수를 읽어 `pymysql.connect()`에 전달할 설정 dict를 생성합니다.

추가로 항상 설정되는 항목:
- `charset="utf8mb4"`
- `cursorclass=pymysql.cursors.DictCursor`

---

### 5.2 `_validate_config(config)`
필수 키 누락 여부를 검사합니다.

누락 시 예외 예시:
- `Missing required settings: host, user, password, database ...`

---

### 5.3 `test_mysql_connection(config, write_test=False)`
실제 연결과 쿼리 테스트를 수행합니다.

기본 테스트:
- `SELECT 1 AS ok, VERSION() AS version, DATABASE() AS current_db`

쓰기 테스트(`write_test=True`):
- 테이블 생성: `copilot_connection_test`
- 테스트 행 INSERT
- `COUNT(*)` 조회로 반영 확인

---

### 5.4 `main()`
CLI 인자를 파싱하고 테스트를 실행합니다.

지원 옵션:
- `--host`
- `--port`
- `--user`
- `--password`
- `--database`
- `--write-test`

인자가 제공되면 동일 키의 환경변수 값을 덮어씁니다.

---

## 6. CLI 사용법
작업 디렉터리: `ExpenseGraph`

1. 연결 확인만 수행
```bash
python aws_test.py
```

2. 연결 + 쓰기 테스트
```bash
python aws_test.py --write-test
```

3. 환경변수 대신 인자로 실행
```bash
python aws_test.py --host 13.209.64.184 --port 3306 --user root --password YOUR_PASSWORD --database db --write-test
```

---

## 7. 성공 출력 예시
```text
MySQL connection success
{'ok': 1, 'version': '8.0.xx', 'current_db': 'db'}
{'write_test_row_count': 2}
```

---

## 8. 실패 시 점검 포인트

### 8.1 필수 설정 누락
- `.env`의 `AWS_MYSQL_*` 값 입력 여부 확인
- 실행 중인 인터프리터가 올바른 프로젝트 `.env`를 읽는지 확인

### 8.2 인증 실패 (`Access denied`)
- 계정/비밀번호 재확인
- 사용자 호스트 허용 범위(`%` 또는 특정 IP) 확인

### 8.3 네트워크 실패 (`timeout`, `can't connect`)
- RDS 보안그룹 인바운드(3306) 허용 확인
- 클라이언트 IP 허용 여부 확인

### 8.4 DB 선택 실패 (`Unknown database`)
- `AWS_MYSQL_DATABASE` 값 확인

---

## 9. 관련 파일
- `ExpenseGraph/aws_test.py`
- `ExpenseGraph/save_local_db.py`
- `backend/app/main.py`

`aws_test.py`는 DB 진단 도구이고, 실제 서비스 저장 로직은 `save_local_db.py`와 백엔드 워크플로우 경로에서 처리됩니다.

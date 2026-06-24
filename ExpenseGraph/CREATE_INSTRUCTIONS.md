# 02_COPILOT_INSTRUCTIONS.md

# GitHub Copilot 개발 지침

## 목표

AI 영수증 가계부 프로젝트를 완전 구현한다.

---

## 필수 조건

* Python 3.12 사용
* FastAPI 사용
* SQLAlchemy 사용
* AWS RDS MySQL 사용
* REST API 구조 사용
* Repository Pattern 적용
* Service Layer 적용
* Pydantic Schema 적용

---

## 디렉토리 구조

project/

├── app/

│ ├── api/

│ ├── services/

│ ├── repositories/

│ ├── models/

│ ├── schemas/

│ ├── database/

│ └── main.py

├── requirements.txt

├── .env

└── README.md

---

## 구현 순서

### 1단계

MySQL 연결

* SQLAlchemy 설정
* DB Session 생성
* 환경변수 사용

---

### 2단계

ORM 모델 생성

* User
* Expense
* ExpenseItem
* Budget
* CategoryBudget

---

### 3단계

Pydantic Schema 생성

* Create
* Update
* Response

모델별 생성

---

### 4단계

Repository 구현

CRUD 구현

* create
* get
* update
* delete
* list

---

### 5단계

Service 구현

비즈니스 로직 처리

---

### 6단계

API 구현

/users
/expenses
/expense-items
/budgets
/category-budgets

REST API 작성

---

### 7단계

OCR 저장 API

POST /expenses/ocr

입력 JSON:

{
"user_id": "user001",
"store_name": "김밥천국",
"purchased_at": "2026-06-23 12:30:00",
"total_amount": 25000,
"payment_method": "신용카드",
"category": "식비/외근",
"memo": "Vision AI OCR 분석",
"raw_text": "OCR 원문",
"items": [...]
}

처리:

1. expenses 저장
2. expense_items 저장
3. transaction commit

---

### 8단계

예산 API 구현

월별 예산 생성

카테고리별 예산 생성

예산 조회

예산 수정

예산 삭제

---

### 9단계

예산 분석 API

반환:

{
"month": "2026-06",
"budget": 1000000,
"spent": 650000,
"remaining": 350000,
"usage_rate": 65.0
}

---

### 10단계

Swagger 자동 생성

FastAPI OpenAPI 활성화

---

## 품질 기준

* Type Hint 필수
* Docstring 작성
* 예외 처리 작성
* Transaction 처리
* SQL Injection 방지
* 테스트 가능한 구조

---

## 최종 결과물

Copilot은 실행 가능한 전체 프로젝트를 생성해야 한다.

코드는 즉시 실행 가능한 수준으로 작성한다.

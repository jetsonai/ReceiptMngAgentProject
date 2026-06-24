# 01_PROJECT_SPEC.md

# AI 영수증 가계부 프로젝트

## 프로젝트 개요

영수증 OCR 결과를 저장하고 예산을 관리하는 가계부 시스템을 개발한다.

사용자는 영수증을 등록할 수 있으며, 등록된 영수증은 지출 내역으로 저장된다.

시스템은 다음 기능을 제공한다.

* 사용자 관리
* 영수증 관리
* 영수증 품목 관리
* 월별 예산 관리
* 카테고리별 예산 관리
* AWS MySQL 저장
* Notion 연동 가능 구조

---

# 데이터베이스

## users

사용자 정보

| 컬럼         | 타입         |
| ---------- | ---------- |
| id         | integer PK |
| user_id    | varchar    |
| name       | varchar    |
| created_at | datetime   |

---

## expenses

영수증 헤더 정보

| 컬럼             | 타입         |
| -------------- | ---------- |
| id             | integer PK |
| user_id        | varchar    |
| store_name     | varchar    |
| purchased_at   | datetime   |
| total_amount   | integer    |
| payment_method | varchar    |
| category       | varchar    |
| memo           | text       |
| raw_text       | text       |
| notion_page_id | varchar    |
| created_at     | datetime   |

---

## expense_items

영수증 품목

| 컬럼         | 타입         |
| ---------- | ---------- |
| id         | integer PK |
| expense_id | integer FK |
| item_name  | varchar    |
| amount     | integer    |
| quantity   | integer    |

---

## budgets

월별 예산

| 컬럼           | 타입         |
| ------------ | ---------- |
| id           | integer PK |
| user_id      | varchar    |
| month        | varchar    |
| total_budget | integer    |
| created_at   | datetime   |

---

## category_budgets

카테고리별 예산

| 컬럼        | 타입         |
| --------- | ---------- |
| id        | integer PK |
| budget_id | integer FK |
| category  | varchar    |
| amount    | integer    |

---

# 관계

users
└── expenses

expenses
└── expense_items

budgets
└── category_budgets

---

# OCR 입력 데이터

시스템은 다음 JSON을 입력으로 받는다.

{
"user_id": "user001",
"store_name": "김밥천국",
"purchased_at": "2026-06-23 12:30:00",
"total_amount": 25000,
"payment_method": "신용카드",
"category": "식비/외근",
"memo": "Vision AI OCR 분석",
"raw_text": "OCR 원본 텍스트",
"items": [
{
"item_name": "김치찌개",
"amount": 18000,
"quantity": 2
}
]
}

---

# 저장 규칙

expenses 저장 후 생성된 id를 이용하여 expense_items 저장

expense_items.expense_id = expenses.id

---

# 기술 스택

Backend : Python
Database : MySQL 8
Cloud : AWS RDS MySQL
ORM : SQLAlchemy
API : FastAPI
Package : pymysql

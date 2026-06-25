"""Local DB save helpers for receipt expenses.

This module persists OCR/LLM structured expense data into a local SQLite DB
using the schema defined in PROJECT_DB_SPEC.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
import tempfile
from urllib.parse import quote_plus, unquote_plus, urlparse
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional
from dotenv import load_dotenv

if TYPE_CHECKING:
	# Optional type-only import so save_local_db can align with backend state keys.
	from backend.app.main import ReceiptAgentState

try:
	import pymysql
except ImportError:  # pragma: no cover - optional dependency for AWS MySQL.
	pymysql = None


def _load_environment() -> None:
	"""Load .env from module and project root regardless of cwd."""
	module_dir = Path(__file__).resolve().parent
	candidates = [
		module_dir / ".env",
		module_dir.parent / ".env",
		Path.cwd() / ".env",
	]

	loaded = False
	for dotenv_path in candidates:
		if dotenv_path.exists():
			load_dotenv(dotenv_path=dotenv_path, override=False)
			loaded = True

	if not loaded:
		load_dotenv(override=False)


_load_environment()

DEFAULT_DB_PATH = str(Path(__file__).with_name("receipt_agent.db"))


def _resolve_db_target(default_target: str = DEFAULT_DB_PATH) -> str:
	"""Resolve DB target using DATABASE_URL, then AWS env vars, else SQLite."""
	database_url = os.getenv("DATABASE_URL", "").strip()
	if database_url:
		return database_url

	mysql_host = os.getenv("AWS_MYSQL_HOST", "").strip()
	mysql_user = os.getenv("AWS_MYSQL_USER", "").strip()
	mysql_password = os.getenv("AWS_MYSQL_PASSWORD", "").strip()
	mysql_database = os.getenv("AWS_MYSQL_DATABASE", "").strip()
	mysql_port = os.getenv("AWS_MYSQL_PORT", "3306").strip() or "3306"

	if mysql_host and mysql_user and mysql_password and mysql_database:
		return (
			f"mysql://{quote_plus(mysql_user)}:{quote_plus(mysql_password)}"
			f"@{mysql_host}:{mysql_port}/{mysql_database}"
		)

	return default_target


DEFAULT_DB_TARGET = _resolve_db_target()


def _effective_db_target(db_target: Optional[str] = None) -> str:
	"""Return explicit target when provided, otherwise resolve from current env."""
	if db_target and str(db_target).strip():
		return str(db_target).strip()
	return _resolve_db_target()


def _is_mysql_target(db_target: str) -> bool:
	return db_target.startswith("mysql://") or db_target.startswith("mysql+pymysql://")


def _is_mysql_connection(conn: Any) -> bool:
	return conn.__class__.__module__.startswith("pymysql")


def _connect_mysql(db_target: str):
	if pymysql is None:
		raise ImportError("pymysql is required for MySQL connections")

	parsed = urlparse(db_target)
	if parsed.scheme not in ("mysql", "mysql+pymysql"):
		raise ValueError(f"Unsupported MySQL URL: {db_target}")

	username = unquote_plus(parsed.username) if parsed.username else "root"
	password = unquote_plus(parsed.password) if parsed.password else ""
	database = unquote_plus((parsed.path or "/").lstrip("/"))

	if not database:
		raise ValueError("MySQL database name is missing in DATABASE_URL")

	return pymysql.connect(
		host=parsed.hostname or "localhost",
		port=parsed.port or 3306,
		user=username,
		password=password,
		database=database,
		charset="utf8mb4",
		autocommit=False,
		cursorclass=pymysql.cursors.DictCursor,
	)


def get_connection(db_target: Optional[str] = None):
	"""Create a SQLite or MySQL connection based on the target string."""
	db_target = _effective_db_target(db_target)
	if _is_mysql_target(db_target):
		return _connect_mysql(db_target)

	conn = sqlite3.connect(db_target)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA foreign_keys = ON")
	return conn


def ensure_schema(conn: Any) -> None:
	"""Create tables if they do not exist."""
	if _is_mysql_connection(conn):
		statements = [
			"""
			CREATE TABLE IF NOT EXISTS expens_user (
				id INT AUTO_INCREMENT PRIMARY KEY,
				user_id VARCHAR(255) NOT NULL UNIQUE,
				name VARCHAR(255),
				create_at DATETIME NOT NULL
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
			""",
			"""
			CREATE TABLE IF NOT EXISTS expenses (
				id INT AUTO_INCREMENT PRIMARY KEY,
				spent_at DATETIME,
				merchant VARCHAR(255),
				addr VARCHAR(500),
				tel VARCHAR(50),
				reg_date DATETIME,
				amount INT,
				payment_method VARCHAR(255),
				category VARCHAR(255),
				items JSON,
				detected_people_count INT,
				per_person_amount INT,
				memo TEXT,
				created_at DATETIME NOT NULL
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
			""",
			"""
			CREATE TABLE IF NOT EXISTS expense_items (
				id INT AUTO_INCREMENT PRIMARY KEY,
				expense_id INT NOT NULL,
				item_name VARCHAR(255) NOT NULL,
				amount INT NOT NULL,
				quantity INT NOT NULL DEFAULT 1,
				CONSTRAINT fk_expense_items_expense
					FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
			""",
			"""
			CREATE TABLE IF NOT EXISTS budgets (
				id INT AUTO_INCREMENT PRIMARY KEY,
				user_id VARCHAR(255) NOT NULL,
				month VARCHAR(20) NOT NULL,
				total_budget INT NOT NULL,
				created_at DATETIME NOT NULL,
				UNIQUE KEY unique_user_month (user_id, month)
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
			""",
			"""
			CREATE TABLE IF NOT EXISTS category_budgets (
				id INT AUTO_INCREMENT PRIMARY KEY,
				budget_id INT NOT NULL,
				category VARCHAR(255) NOT NULL,
				amount INT NOT NULL,
				CONSTRAINT fk_category_budgets_budget
					FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
				UNIQUE KEY unique_budget_category (budget_id, category)
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
			""",
		]
		with conn.cursor() as cursor:
			for stmt in statements:
				cursor.execute(stmt)
		conn.commit()
		return

	conn.executescript(
		"""
		CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id TEXT NOT NULL UNIQUE,
			name TEXT,
			created_at TEXT NOT NULL
		);

		CREATE TABLE IF NOT EXISTS expenses (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id TEXT NOT NULL,
			store_name TEXT NOT NULL,
			purchased_at TEXT NOT NULL,
			total_amount INTEGER NOT NULL,
			payment_method TEXT,
			category TEXT,
			memo TEXT,
			raw_text TEXT,
			notion_page_id TEXT,
			created_at TEXT NOT NULL
		);

		CREATE TABLE IF NOT EXISTS expense_items (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			expense_id INTEGER NOT NULL,
			item_name TEXT NOT NULL,
			amount INTEGER NOT NULL,
			quantity INTEGER NOT NULL DEFAULT 1,
			FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE
		);

		CREATE TABLE IF NOT EXISTS budgets (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id TEXT NOT NULL,
			month TEXT NOT NULL,
			total_budget INTEGER NOT NULL,
			created_at TEXT NOT NULL,
			UNIQUE (user_id, month)
		);

		CREATE TABLE IF NOT EXISTS category_budgets (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			budget_id INTEGER NOT NULL,
			category TEXT NOT NULL,
			amount INTEGER NOT NULL,
			FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
			UNIQUE (budget_id, category)
		);
		"""
	)
	conn.execute("PRAGMA foreign_keys = ON")


def _now_str() -> str:
	return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_int(value: Any, default: int = 0) -> int:
	"""Safely parse int from numbers/strings like '12,000원'."""
	if value is None:
		return default
	if isinstance(value, bool):
		return int(value)
	if isinstance(value, (int, float)):
		return int(value)

	text = str(value).strip()
	if not text:
		return default

	filtered = "".join(ch for ch in text if ch.isdigit() or ch == "-")
	if not filtered or filtered == "-":
		return default

	try:
		return int(filtered)
	except ValueError:
		return default


def _normalize_expense_payload(expense_data: Dict[str, Any]) -> Dict[str, Any]:
	"""Normalize backend/main and legacy payload keys to one save schema."""
	now = _now_str()
	purchased_at = str(
		expense_data.get("purchased_at")
		or expense_data.get("spent_at")
		or expense_data.get("approved_at")
		or expense_data.get("reg_date")
		or now
	)

	return {
		"user_id": str(expense_data.get("user_id") or expense_data.get("id") or "demo-user"),
		"name": str(expense_data.get("name") or expense_data.get("user_id") or expense_data.get("id") or "demo-user"),
		"store_name": str(
			expense_data.get("store_name")
			or expense_data.get("merchant")
			or expense_data.get("store")
			or ""
		),
		"purchased_at": purchased_at,
		"total_amount": _to_int(expense_data.get("total_amount") or expense_data.get("amount") or 0, 0),
		"payment_method": str(expense_data.get("payment_method") or expense_data.get("pay_method") or ""),
		"category": str(expense_data.get("category") or "기타"),
		"memo": str(expense_data.get("memo") or expense_data.get("description") or ""),
		"raw_text": str(
			expense_data.get("raw_text")
			or expense_data.get("ocr_raw_text")
			or expense_data.get("ocr_text")
			or ""
		),
		"notion_page_id": str(expense_data.get("notion_page_id") or ""),
		"items": expense_data.get("items") or expense_data.get("line_items") or [],
		"addr": str(expense_data.get("addr") or expense_data.get("address") or ""),
		"tel": str(
			expense_data.get("tel")
			or expense_data.get("telephone")
			or expense_data.get("phone")
			or ""
		),
		"reg_date": str(expense_data.get("reg_date") or expense_data.get("registered_at") or now),
		"detected_people_count": _to_int(expense_data.get("detected_people_count") or expense_data.get("people_count") or 1, 1),
		"per_person_amount": _to_int(
			expense_data.get("per_person_amount")
			or expense_data.get("unit_amount")
			or expense_data.get("total_amount")
			or expense_data.get("amount")
			or 0,
			0,
		),
	}


def _normalize_items(items: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
	normalized: List[Dict[str, Any]] = []
	if not items:
		return normalized

	for item in items:
		item_name = str(item.get("item_name") or item.get("name") or "기타")
		amount = _to_int(item.get("amount") or item.get("total") or 0, 0)
		quantity = _to_int(item.get("quantity") or item.get("count") or 1, 1)
		normalized.append(
			{
				"item_name": item_name,
				"amount": amount,
				"quantity": max(1, quantity),
			}
		)
	return normalized


def _execute(conn: Any, sql: str, params: tuple = ()):
	if _is_mysql_connection(conn):
		with conn.cursor() as cursor:
			cursor.execute(sql, params)
			return cursor
	return conn.execute(sql, params)


def _executemany(conn: Any, sql: str, params_list: List[tuple]) -> None:
	if _is_mysql_connection(conn):
		with conn.cursor() as cursor:
			cursor.executemany(sql, params_list)
		return
	conn.executemany(sql, params_list)


def _fetchone(conn: Any, sql: str, params: tuple = ()):
	if _is_mysql_connection(conn):
		with conn.cursor() as cursor:
			cursor.execute(sql, params)
			return cursor.fetchone()
	return conn.execute(sql, params).fetchone()


def _fetchall(conn: Any, sql: str, params: tuple = ()):
	if _is_mysql_connection(conn):
		with conn.cursor() as cursor:
			cursor.execute(sql, params)
			return cursor.fetchall()
	return conn.execute(sql, params).fetchall()


def _commit(conn: Any) -> None:
	conn.commit()


def _rollback(conn: Any) -> None:
	conn.rollback()


def save_local_db(expense_data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
	"""Save one structured expense record and its items.

	Expected keys in expense_data:
	- user_id, store_name, purchased_at, total_amount
	- payment_method, category, memo, raw_text, notion_page_id
	- items: list[dict] where dict supports item_name/name, amount/total,
	  quantity/count.
	"""
	normalized_data = _normalize_expense_payload(expense_data)
	required = ("user_id", "store_name", "purchased_at", "total_amount")
	missing = [key for key in required if normalized_data.get(key) in (None, "")]
	if missing:
		return {
			"saved_local_db": False,
			"expense_id": None,
			"error": f"Missing required fields: {', '.join(missing)}",
		}

	db_path = _effective_db_target(db_path)
	conn = get_connection(db_path)
	try:
		ensure_schema(conn)
		now = _now_str()
		now_datetime = datetime.now()
		items = _normalize_items(normalized_data.get("items"))

		if _is_mysql_connection(conn):
			with conn.cursor() as cursor:
				spent_at = str(normalized_data.get("purchased_at") or now)
				merchant = str(normalized_data.get("store_name") or "")
				addr = str(normalized_data.get("addr") or "")
				tel = str(normalized_data.get("tel") or "")
				reg_date = str(normalized_data.get("reg_date") or now)
				amount = int(normalized_data.get("total_amount") or 0)
				detected_people_count = int(normalized_data.get("detected_people_count") or 1)
				per_person_amount = int(normalized_data.get("per_person_amount") or amount)
				items_json = json.dumps(items, ensure_ascii=False)

				cursor.execute(
					"""
					INSERT IGNORE INTO expens_user (user_id, name, create_at)
					VALUES (%s, %s, %s)
					""",
					(
						str(normalized_data["user_id"]),
						str(normalized_data.get("name") or normalized_data["user_id"]),
						now_datetime,
					),
				)

				cursor.execute(
					"""
					INSERT INTO expenses (
						spent_at,
						merchant,
						addr,
						tel,
						reg_date,
						amount,
						payment_method,
						category,
						items,
						detected_people_count,
						per_person_amount,
						memo,
						created_at
					)
					VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
					""",
					(
						spent_at,
						merchant,
						addr,
						tel,
						reg_date,
						amount,
						str(normalized_data.get("payment_method") or ""),
						str(normalized_data.get("category") or "기타"),
						items_json,
						detected_people_count,
						per_person_amount,
						str(normalized_data.get("memo") or ""),
						now_datetime,
					),
				)
				expense_id = int(cursor.lastrowid)

				if items:
					cursor.executemany(
						"""
						INSERT INTO expense_items (expense_id, item_name, amount, quantity)
						VALUES (%s, %s, %s, %s)
						""",
						[
							(expense_id, item["item_name"], item["amount"], item["quantity"])
							for item in items
						],
					)
			_commit(conn)
		else:
			with conn:
				# Keep user table in sync for later joins or user-level analytics.
				conn.execute(
					"""
					INSERT INTO users (user_id, name, created_at)
					VALUES (?, ?, ?)
					ON CONFLICT(user_id) DO NOTHING
					""",
					(
						str(normalized_data["user_id"]),
						str(normalized_data.get("name") or normalized_data["user_id"]),
						now,
					),
				)

				cur = conn.execute(
					"""
					INSERT INTO expenses (
						user_id,
						store_name,
						purchased_at,
						total_amount,
						payment_method,
						category,
						memo,
						raw_text,
						notion_page_id,
						created_at
					)
					VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
					""",
					(
						str(normalized_data["user_id"]),
						str(normalized_data["store_name"]),
						str(normalized_data["purchased_at"]),
						int(normalized_data["total_amount"]),
						str(normalized_data.get("payment_method") or ""),
						str(normalized_data.get("category") or "기타"),
						str(normalized_data.get("memo") or ""),
						str(normalized_data.get("raw_text") or ""),
						str(normalized_data.get("notion_page_id") or ""),
						now,
					),
				)
				expense_id = int(cur.lastrowid)

				if items:
					conn.executemany(
						"""
						INSERT INTO expense_items (expense_id, item_name, amount, quantity)
						VALUES (?, ?, ?, ?)
						""",
						[
							(expense_id, item["item_name"], item["amount"], item["quantity"])
							for item in items
						],
					)

		return {
			"saved_local_db": True,
			"expense_id": expense_id,
			"item_count": len(items),
			"db_path": db_path,
		}
	except Exception as exc:
		_rollback(conn)
		return {
			"saved_local_db": False,
			"expense_id": None,
			"error": str(exc),
		}
	finally:
		conn.close()


def build_dummy_expense_data() -> Dict[str, Any]:
	"""Build a realistic dummy receipt payload for local testing."""
	return {
		"user_id": "demo-user",
		"store_name": "사천루",
		"purchased_at": "2026-06-23 16:30:00",
		"total_amount": 11000,
		"payment_method": "신용카드",
		"category": "점심식사",
		"memo": "주간 장",
		"raw_text": "Lotte Mart\n장보기 45000\n합계 45000",
		"items": [
			{"item_name": "식료품", "amount": 30000, "quantity": 1},
			{"item_name": "생활용품", "amount": 15000, "quantity": 1},
		],
	}


def _print_db_summary(db_path: str) -> None:
	"""Print a compact summary of the saved rows."""
	conn = get_connection(db_path)
	try:
		ensure_schema(conn)
		expense_count = _fetchone(conn, "SELECT COUNT(*) AS c FROM expenses")["c"]
		item_count = _fetchone(conn, "SELECT COUNT(*) AS c FROM expense_items")["c"]
		if _is_mysql_connection(conn):
			latest_sql = """
			SELECT id, spent_at, merchant, amount, category
			FROM expenses
			ORDER BY id DESC
			LIMIT 1
			"""
		else:
			latest_sql = """
			SELECT id, user_id, store_name, purchased_at, total_amount, category
			FROM expenses
			ORDER BY id DESC
			LIMIT 1
			"""

		latest = _fetchone(conn, latest_sql)
		print({"expenses": expense_count, "items": item_count})
		if latest:
			print(dict(latest))
	finally:
		conn.close()


def get_latest_expense(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
	"""Return the most recently inserted expense row."""
	db_path = _effective_db_target(db_path)
	conn = get_connection(db_path)
	try:
		ensure_schema(conn)
		if _is_mysql_connection(conn):
			sql = """
			SELECT id, spent_at, merchant, addr, tel, reg_date, amount, payment_method,
			       category, items, detected_people_count, per_person_amount, memo, created_at
			FROM expenses
			ORDER BY id DESC
			LIMIT 1
			"""
		else:
			sql = """
			SELECT id, user_id, store_name, purchased_at, total_amount, payment_method,
			       category, memo, raw_text, notion_page_id, created_at
			FROM expenses
			ORDER BY id DESC
			LIMIT 1
			"""

		row = _fetchone(conn, sql)
		return dict(row) if row else None
	finally:
		conn.close()


def get_expense_items(expense_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
	"""Return all item rows for a saved expense."""
	db_path = _effective_db_target(db_path)
	conn = get_connection(db_path)
	try:
		ensure_schema(conn)
		if _is_mysql_connection(conn):
			sql = """
			SELECT id, expense_id, item_name, amount, quantity
			FROM expense_items
			WHERE expense_id = %s
			ORDER BY id ASC
			"""
		else:
			sql = """
			SELECT id, expense_id, item_name, amount, quantity
			FROM expense_items
			WHERE expense_id = ?
			ORDER BY id ASC
			"""

		rows = _fetchall(conn, sql, (expense_id,))
		return [dict(row) for row in rows]
	finally:
		conn.close()


def test_connection(db_target: Optional[str] = None) -> Dict[str, Any]:
	"""Test a database connection and basic schema access."""
	db_target = _effective_db_target(db_target)
	conn = get_connection(db_target)
	try:
		ensure_schema(conn)
		row = _fetchone(conn, "SELECT 1 AS ok")
		backend = "mysql" if _is_mysql_connection(conn) else "sqlite"
		return {"connected": True, "backend": backend, "probe": row["ok"]}
	finally:
		conn.close()


def main() -> None:
	"""Run a dummy save test from the command line."""
	parser = argparse.ArgumentParser(description="Test local receipt DB save with dummy data.")
	parser.add_argument(
		"--db-target",
		default="",
		help="SQLite file path or MySQL DATABASE_URL. If omitted, DATABASE_URL or a temporary DB is used.",
	)
	parser.add_argument(
		"--use-temp-db",
		action="store_true",
		help="Use a temporary SQLite DB for one-time smoke tests.",
	)
	parser.add_argument(
		"--test-connection",
		action="store_true",
		help="Only test the database connection and schema creation.",
	)
	args = parser.parse_args()
	db_target = args.db_target or DEFAULT_DB_TARGET

	if args.test_connection:
		print(test_connection(db_target))
		return

	if args.use_temp_db:
		with tempfile.TemporaryDirectory() as temp_dir:
			db_path = str(Path(temp_dir) / "receipt_agent_demo.db")
			print(f"Using temporary DB path: {db_path}")
			result = save_local_db(build_dummy_expense_data(), db_path=db_path)
			print(result)
			_print_db_summary(db_path)
			latest = get_latest_expense(db_path)
			if latest:
				print({"latest_expense": latest})
				print({"latest_items": get_expense_items(int(latest["id"]), db_path=db_path)})
		return

	if args.db_target:
		print(f"Using DB target: {db_target}")
		result = save_local_db(build_dummy_expense_data(), db_path=db_target)
		print(result)
		if not result.get("saved_local_db"):
			return
		_print_db_summary(db_target)
		latest = get_latest_expense(db_target)
		if latest:
			print({"latest_expense": latest})
			print({"latest_items": get_expense_items(int(latest["id"]), db_path=db_target)})
		return

	# Default behavior: save to the configured default target so data persists.
	print(f"Using default DB target: {DEFAULT_DB_TARGET}")
	dummy_data = build_dummy_expense_data()
	
	# Save to default target (local SQLite)
	result = save_local_db(dummy_data, db_path=DEFAULT_DB_TARGET)
	print(result)
	if not result.get("saved_local_db"):
		return
	_print_db_summary(DEFAULT_DB_TARGET)
	latest = get_latest_expense(DEFAULT_DB_TARGET)
	if latest:
		print({"latest_expense": latest})
		print({"latest_items": get_expense_items(int(latest["id"]), db_path=DEFAULT_DB_TARGET)})
	
	# Also save to MySQL if AWS credentials are set
	mysql_host = os.getenv("AWS_MYSQL_HOST")
	mysql_user = os.getenv("AWS_MYSQL_USER")
	mysql_password = os.getenv("AWS_MYSQL_PASSWORD")
	mysql_database = os.getenv("AWS_MYSQL_DATABASE")
	
	if mysql_host and mysql_user and mysql_password and mysql_database:
		mysql_port = os.getenv("AWS_MYSQL_PORT", "3306")
		mysql_url = (
			f"mysql://{quote_plus(mysql_user)}:{quote_plus(mysql_password)}"
			f"@{mysql_host}:{mysql_port}/{mysql_database}"
		)
		print(f"\n[MySQL 저장] {mysql_host}:{mysql_port}/{mysql_database}")
		try:
			mysql_result = save_local_db(dummy_data, db_path=mysql_url)
			print(mysql_result)
			if mysql_result.get("saved_local_db"):
				_print_db_summary(mysql_url)
				mysql_latest = get_latest_expense(mysql_url)
				if mysql_latest:
					print({"mysql_latest_expense": mysql_latest})
		except Exception as e:
			print(f"MySQL 저장 실패: {e}")

# ADIM code by Kate 20260625

def load_dashboard_data_shared(db_target: str, start_date: str = None, end_date: str = None, category: str = None) -> dict:
    """
    admin_app.py에서 직접 수행하던 DB 조회 및 필터링 로직을 백엔드로 이관한 공용 함수.
    MySQL과 SQLite의 컬럼명 및 쿼리 파라미터 바인딩 차이를 자동으로 상쇄합니다.
    """
    import sqlite3
    conn = get_connection(db_target)
    
    # 연결 객체의 모듈명으로 MySQL 여부 판단
    is_mysql = conn.__class__.__module__.startswith("pymysql")
    
    # 1. DB 환경별 테이블, 컬럼명, 플레이스홀더 매핑
    if is_mysql:
        table_name = "expenses"
        date_col = "spent_at"
        merchant_col = "merchant"
        amount_col = "amount"
        category_col = "category"
        param_placeholder = "%s"
    else:
        table_name = "expenses"
        date_col = "purchased_at"
        merchant_col = "store_name"
        amount_col = "total_amount"
        category_col = "category"
        param_placeholder = "?"

    # 2. 동적 WHERE 절 구성
    where_clauses = []
    params = []
    
    if start_date:
        where_clauses.append(f"{date_col} >= {param_placeholder}")
        params.append(start_date)
    if end_date:
        where_clauses.append(f"{date_col} <= {param_placeholder}")
        params.append(end_date)
    if category and category != "전체":
        where_clauses.append(f"{category_col} = {param_placeholder}")
        params.append(category)
        
    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # 코어 결과 세트 빌드를 위한 내부 헬퍼 쿼리 실행기
    def _execute_query(sql, p):
        if is_mysql:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(p))
                return [dict(r) for r in cursor.fetchall()]
        else:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, tuple(p)).fetchall()]

    # 3. 메인 지출 목록 조회
    sql_rows = f"""
        SELECT id, {date_col} AS `날짜`, {merchant_col} AS `가맹점명`, 
               {amount_col} AS `금액`, {category_col} AS `카테고리`
        FROM {table_name} {where_str} ORDER BY id DESC
    """
    rows = _execute_query(sql_rows, params)

    # 4. 카테고리별 합계 조회 (차트용)
    sql_chart = f"""
        SELECT {category_col} AS `카테고리`, SUM({amount_col}) AS `금액`
        FROM {table_name} {where_str} GROUP BY {category_col}
    """
    category_rows = _execute_query(sql_chart, params)

    # 5. 전체 데이터 수 조회 (Metric용)
    sql_count = f"SELECT COUNT(*) AS total_count FROM {table_name}"
    count_res = _execute_query(sql_count, [])
    total_count = count_res[0]["total_count"] if count_res else 0

    conn.close()

    return {
        "backend": "MySQL" if is_mysql else "SQLite",
        "total_count": total_count,
        "rows": rows,
        "category_rows": category_rows
    }

if __name__ == "__main__":
	main()


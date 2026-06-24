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
from urllib.parse import urlparse
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

if TYPE_CHECKING:
	# Optional type-only import so save_local_db can align with backend state keys.
	from backend.app.main import ReceiptAgentState

try:
	import pymysql
except ImportError:  # pragma: no cover - optional dependency for AWS MySQL.
	pymysql = None


DEFAULT_DB_PATH = str(Path(__file__).with_name("receipt_agent.db"))
DEFAULT_DB_TARGET = os.getenv("DATABASE_URL", DEFAULT_DB_PATH)


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

	return pymysql.connect(
		host=parsed.hostname or "localhost",
		port=parsed.port or 3306,
		user=parsed.username or "root",
		password=parsed.password or "",
		database=(parsed.path or "/").lstrip("/"),
		charset="utf8mb4",
		autocommit=False,
		cursorclass=pymysql.cursors.DictCursor,
	)


def get_connection(db_target: str = DEFAULT_DB_TARGET):
	"""Create a SQLite or MySQL connection based on the target string."""
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


def _normalize_expense_payload(expense_data: Dict[str, Any]) -> Dict[str, Any]:
	"""Normalize backend/main and legacy payload keys to one save schema."""
	now = _now_str()
	purchased_at = str(
		expense_data.get("purchased_at")
		or expense_data.get("spent_at")
		or expense_data.get("reg_date")
		or now
	)

	return {
		"user_id": str(expense_data.get("user_id") or expense_data.get("id") or "demo-user"),
		"name": str(expense_data.get("name") or expense_data.get("user_id") or expense_data.get("id") or "demo-user"),
		"store_name": str(expense_data.get("store_name") or expense_data.get("merchant") or ""),
		"purchased_at": purchased_at,
		"total_amount": int(expense_data.get("total_amount") or expense_data.get("amount") or 0),
		"payment_method": str(expense_data.get("payment_method") or ""),
		"category": str(expense_data.get("category") or "기타"),
		"memo": str(expense_data.get("memo") or ""),
		"raw_text": str(expense_data.get("raw_text") or expense_data.get("ocr_raw_text") or ""),
		"notion_page_id": str(expense_data.get("notion_page_id") or ""),
		"items": expense_data.get("items") or [],
		"addr": str(expense_data.get("addr") or ""),
		"tel": str(expense_data.get("tel") or ""),
		"reg_date": str(expense_data.get("reg_date") or now),
		"detected_people_count": int(expense_data.get("detected_people_count") or 1),
		"per_person_amount": int(
			expense_data.get("per_person_amount")
			or expense_data.get("total_amount")
			or expense_data.get("amount")
			or 0
		),
	}


def _normalize_items(items: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
	normalized: List[Dict[str, Any]] = []
	if not items:
		return normalized

	for item in items:
		item_name = str(item.get("item_name") or item.get("name") or "기타")
		amount = int(item.get("amount") or item.get("total") or 0)
		quantity = int(item.get("quantity") or item.get("count") or 1)
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


def save_local_db(expense_data: Dict[str, Any], db_path: str = DEFAULT_DB_TARGET) -> Dict[str, Any]:
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


def get_latest_expense(db_path: str = DEFAULT_DB_TARGET) -> Optional[Dict[str, Any]]:
	"""Return the most recently inserted expense row."""
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


def get_expense_items(expense_id: int, db_path: str = DEFAULT_DB_TARGET) -> List[Dict[str, Any]]:
	"""Return all item rows for a saved expense."""
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


def test_connection(db_target: str = DEFAULT_DB_TARGET) -> Dict[str, Any]:
	"""Test a database connection and basic schema access."""
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
		mysql_url = f"mysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_database}"
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


if __name__ == "__main__":
	main()


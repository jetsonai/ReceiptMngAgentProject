"""AWS RDS MySQL connection smoke test.

Usage:
1) Set environment variables:
   - AWS_MYSQL_HOST
   - AWS_MYSQL_PORT (optional, default: 3306)
   - AWS_MYSQL_USER
   - AWS_MYSQL_PASSWORD
   - AWS_MYSQL_DATABASE
2) Run:
   python aws_test.py

Optional write test:
   python aws_test.py --write-test
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict

import pymysql


def _build_config_from_env() -> Dict[str, Any]:
    return {
        "host": os.getenv("AWS_MYSQL_HOST", ""),
        "port": int(os.getenv("AWS_MYSQL_PORT", "3306")),
        "user": os.getenv("AWS_MYSQL_USER", ""),
        "password": os.getenv("AWS_MYSQL_PASSWORD", ""),
        "database": os.getenv("AWS_MYSQL_DATABASE", ""),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


def _validate_config(config: Dict[str, Any]) -> None:
    missing = [
        key
        for key in ("host", "user", "password", "database")
        if not config.get(key)
    ]
    if missing:
        raise ValueError(
            "Missing required settings: "
            + ", ".join(missing)
            + " | Set AWS_MYSQL_HOST/AWS_MYSQL_USER/AWS_MYSQL_PASSWORD/AWS_MYSQL_DATABASE"
        )


def test_mysql_connection(config: Dict[str, Any], write_test: bool = False) -> None:
    _validate_config(config)
    conn = pymysql.connect(**config)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok, VERSION() AS version, DATABASE() AS current_db")
            row = cur.fetchone()
            print("MySQL connection success")
            print(row)

            if write_test:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS copilot_connection_test (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT,
                        note VARCHAR(100) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO copilot_connection_test (note) VALUES (%s)",
                    ("aws mysql write test",),
                )
                conn.commit()
                cur.execute("SELECT COUNT(*) AS cnt FROM copilot_connection_test")
                print({"write_test_row_count": cur.fetchone()["cnt"]})
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="AWS RDS MySQL connection test")
    parser.add_argument("--host", default="", help="MySQL host")
    parser.add_argument("--port", type=int, default=0, help="MySQL port")
    parser.add_argument("--user", default="", help="MySQL user")
    parser.add_argument("--password", default="", help="MySQL password")
    parser.add_argument("--database", default="", help="MySQL database")
    parser.add_argument("--write-test", action="store_true", help="Run create/insert smoke test")
    args = parser.parse_args()

    config = _build_config_from_env()

    # CLI args override env vars when provided.
    if args.host:
        config["host"] = args.host
    if args.port:
        config["port"] = args.port
    if args.user:
        config["user"] = args.user
    if args.password:
        config["password"] = args.password
    if args.database:
        config["database"] = args.database

    try:
        test_mysql_connection(config, write_test=args.write_test)
        return 0
    except Exception as exc:  # pragma: no cover - CLI error path
        print(f"Connection test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
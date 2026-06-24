import tempfile
import unittest
from datetime import datetime

from check_budget import check_budget
from save_local_db import ensure_schema, get_connection, save_local_db


class ReceiptDbBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = f"{self.temp_dir.name}/test_receipt_agent.db"
        conn = get_connection(self.db_path)
        try:
            ensure_schema(conn)
        finally:
            conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _insert_budget(self, user_id: str, month: str, total_budget: int) -> None:
        conn = get_connection(self.db_path)
        try:
            ensure_schema(conn)
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO budgets (user_id, month, total_budget, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, month, total_budget, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                budget_id = int(cur.lastrowid)
                conn.execute(
                    """
                    INSERT INTO category_budgets (budget_id, category, amount)
                    VALUES (?, ?, ?)
                    """,
                    (budget_id, "food", int(total_budget * 0.5)),
                )
        finally:
            conn.close()

    def _insert_expense(self, user_id: str, purchased_at: str, amount: int, category: str = "food") -> None:
        payload = {
            "user_id": user_id,
            "store_name": "Test Store",
            "purchased_at": purchased_at,
            "total_amount": amount,
            "payment_method": "card",
            "category": category,
            "memo": "",
            "raw_text": "",
            "items": [
                {"item_name": "item-a", "amount": amount, "quantity": 1},
            ],
        }
        result = save_local_db(payload, db_path=self.db_path)
        self.assertTrue(result["saved_local_db"])

    def test_save_local_db_saves_expense_and_items(self) -> None:
        payload = {
            "user_id": "demo-user",
            "store_name": "Coffee Shop",
            "purchased_at": "2026-06-23 14:30:00",
            "total_amount": 10500,
            "payment_method": "card",
            "category": "food",
            "memo": "ocr memo",
            "raw_text": "raw receipt text",
            "items": [
                {"name": "americano", "total": 4500, "count": 1},
                {"item_name": "sandwich", "amount": 6000, "quantity": 1},
            ],
        }

        result = save_local_db(payload, db_path=self.db_path)

        self.assertTrue(result["saved_local_db"])
        self.assertIsNotNone(result["expense_id"])
        self.assertEqual(result["item_count"], 2)

        conn = get_connection(self.db_path)
        try:
            expense_count = conn.execute("SELECT COUNT(*) AS c FROM expenses").fetchone()["c"]
            item_count = conn.execute("SELECT COUNT(*) AS c FROM expense_items").fetchone()["c"]
        finally:
            conn.close()

        self.assertEqual(expense_count, 1)
        self.assertEqual(item_count, 2)

    def test_save_local_db_validates_required_fields(self) -> None:
        payload = {
            "user_id": "demo-user",
            "store_name": "",
            "purchased_at": "2026-06-23 14:30:00",
            "total_amount": 1000,
        }

        result = save_local_db(payload, db_path=self.db_path)

        self.assertFalse(result["saved_local_db"])
        self.assertIn("Missing required fields", result["error"])

    def test_check_budget_status_safe(self) -> None:
        self._insert_budget("u1", "2026-06", 100000)
        self._insert_expense("u1", "2026-06-10 12:00:00", 60000)

        result = check_budget("u1", 5000, purchased_at="2026-06-23 10:00:00", category="food", db_path=self.db_path)

        self.assertEqual(result["budget_status"], "SAFE")
        self.assertEqual(result["monthly_spent"], 65000)

    def test_check_budget_status_warning(self) -> None:
        self._insert_budget("u2", "2026-06", 100000)
        self._insert_expense("u2", "2026-06-10 12:00:00", 65000)

        result = check_budget("u2", 7000, purchased_at="2026-06-23 10:00:00", category="food", db_path=self.db_path)

        self.assertEqual(result["budget_status"], "WARNING")
        self.assertEqual(result["usage_rate"], 72.0)

    def test_check_budget_status_danger(self) -> None:
        self._insert_budget("u3", "2026-06", 100000)
        self._insert_expense("u3", "2026-06-10 12:00:00", 85000)

        result = check_budget("u3", 5000, purchased_at="2026-06-23 10:00:00", category="food", db_path=self.db_path)

        self.assertEqual(result["budget_status"], "DANGER")
        self.assertEqual(result["usage_rate"], 90.0)

    def test_check_budget_status_over(self) -> None:
        self._insert_budget("u4", "2026-06", 100000)
        self._insert_expense("u4", "2026-06-10 12:00:00", 98000)

        result = check_budget("u4", 3000, purchased_at="2026-06-23 10:00:00", category="food", db_path=self.db_path)

        self.assertEqual(result["budget_status"], "OVER")
        self.assertEqual(result["monthly_spent"], 101000)

    def test_check_budget_returns_category_metrics_when_available(self) -> None:
        self._insert_budget("u5", "2026-06", 100000)
        self._insert_expense("u5", "2026-06-10 12:00:00", 10000, category="food")

        result = check_budget("u5", 10000, purchased_at="2026-06-23 10:00:00", category="food", db_path=self.db_path)

        self.assertIn("category_budget", result)
        self.assertIn("category_spent", result)
        self.assertIn("category_usage_rate", result)
        self.assertEqual(result["category_budget"], 50000)
        self.assertEqual(result["category_spent"], 20000)


if __name__ == "__main__":
    unittest.main(verbosity=2)

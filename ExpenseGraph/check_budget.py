"""Budget evaluation helpers.

Implements budget status rules from CREATE_INSTRUCTIONS.md:
- SAFE: usage < 70%
- WARNING: 70% <= usage < 90%
- DANGER: usage >= 90%
- OVER: exceeded monthly budget
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from save_local_db import DEFAULT_DB_PATH, ensure_schema, get_connection


def _month_key(purchased_at: Optional[str]) -> str:
	if not purchased_at:
		return datetime.now().strftime("%Y-%m")

	for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
		try:
			return datetime.strptime(purchased_at, fmt).strftime("%Y-%m")
		except ValueError:
			continue

	# Fallback for already month-prefixed strings.
	return str(purchased_at)[:7]


def _status_from_budget(spent: int, budget: int) -> Tuple[str, float]:
	if budget <= 0:
		return "SAFE", 0.0

	usage_rate = round((spent / budget) * 100, 2)
	if spent > budget:
		return "OVER", usage_rate
	if usage_rate >= 90:
		return "DANGER", usage_rate
	if usage_rate >= 70:
		return "WARNING", usage_rate
	return "SAFE", usage_rate


def _comment_for_status(status: str, category: Optional[str], has_budget: bool) -> str:
	category_text = category if category else "전체"
	if not has_budget:
		return "월 예산이 설정되지 않았습니다. 먼저 예산을 등록하세요."
	if status == "OVER":
		return f"{category_text} 지출이 월 예산을 초과했습니다. 즉시 지출 조정이 필요합니다."
	if status == "DANGER":
		return f"{category_text} 예산이 90% 이상 사용되었습니다. 남은 기간 지출을 최소화하세요."
	if status == "WARNING":
		return f"{category_text} 예산 사용률이 70%를 넘었습니다. 지출 속도를 점검해보세요."
	return f"{category_text} 예산 범위 내에서 지출 중입니다."


def check_budget(
	user_id: str,
	expense_amount: int,
	purchased_at: Optional[str] = None,
	category: Optional[str] = None,
	db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
	"""Evaluate monthly budget status for an incoming expense.

	Returns fields suitable for API response composition:
	- budget_status, monthly_budget, monthly_spent, usage_rate, comment
	- plus month and optional category budget metrics when available.
	"""
	month = _month_key(purchased_at)
	amount = max(0, int(expense_amount))

	conn = get_connection(db_path)
	try:
		ensure_schema(conn)

		budget_row = conn.execute(
			"""
			SELECT id, total_budget
			FROM budgets
			WHERE user_id = ? AND month = ?
			ORDER BY id DESC
			LIMIT 1
			""",
			(user_id, month),
		).fetchone()

		total_budget = int(budget_row["total_budget"]) if budget_row else 0

		spent_row = conn.execute(
			"""
			SELECT COALESCE(SUM(total_amount), 0) AS spent
			FROM expenses
			WHERE user_id = ? AND substr(purchased_at, 1, 7) = ?
			""",
			(user_id, month),
		).fetchone()

		spent_before = int(spent_row["spent"]) if spent_row else 0
		spent_after = spent_before + amount

		status, usage_rate = _status_from_budget(spent_after, total_budget)
		has_budget = total_budget > 0

		result: Dict[str, Any] = {
			"month": month,
			"budget_status": status,
			"monthly_budget": total_budget,
			"monthly_spent": spent_after,
			"usage_rate": usage_rate,
			"comment": _comment_for_status(status, category, has_budget),
		}

		if budget_row and category:
			category_row = conn.execute(
				"""
				SELECT amount
				FROM category_budgets
				WHERE budget_id = ? AND category = ?
				LIMIT 1
				""",
				(int(budget_row["id"]), category),
			).fetchone()

			if category_row:
				category_budget = int(category_row["amount"])
				category_spent_row = conn.execute(
					"""
					SELECT COALESCE(SUM(total_amount), 0) AS spent
					FROM expenses
					WHERE user_id = ?
					  AND category = ?
					  AND substr(purchased_at, 1, 7) = ?
					""",
					(user_id, category, month),
				).fetchone()
				category_spent = int(category_spent_row["spent"]) + amount
				category_usage = (
					round((category_spent / category_budget) * 100, 2)
					if category_budget > 0
					else 0.0
				)

				result.update(
					{
						"category": category,
						"category_budget": category_budget,
						"category_spent": category_spent,
						"category_usage_rate": category_usage,
					}
				)

		return result
	except Exception as exc:
		return {
			"month": month,
			"budget_status": "SAFE",
			"monthly_budget": 0,
			"monthly_spent": amount,
			"usage_rate": 0.0,
			"comment": f"예산 점검 중 오류가 발생했습니다: {exc}",
		}
	finally:
		conn.close()


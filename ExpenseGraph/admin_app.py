from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from save_local_db import DEFAULT_DB_TARGET, ensure_schema, get_connection, get_expense_items


st.set_page_config(page_title="영수증 관리자", layout="wide")


def _is_mysql_connection(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("pymysql")


def _param_placeholder(conn: Any) -> str:
    return "%s" if _is_mysql_connection(conn) else "?"


def _fetchall(conn: Any, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    if _is_mysql_connection(conn):
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def _fetchone(conn: Any, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    rows = _fetchall(conn, sql, params)
    return rows[0] if rows else None


def _table_columns(conn: Any, table_name: str) -> set[str]:
    if _is_mysql_connection(conn):
        rows = _fetchall(conn, f"SHOW COLUMNS FROM {table_name}")
        return {str(row.get("Field")) for row in rows}

    rows = _fetchall(conn, f"PRAGMA table_info({table_name})")
    return {str(row.get("name")) for row in rows}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format_money(value: Any) -> str:
    return f"{_int_value(value):,}원"


def _normalize_expense(row: Dict[str, Any]) -> Dict[str, Any]:
    spent_at = row.get("spent_at") or row.get("purchased_at") or row.get("reg_date")
    merchant = row.get("merchant") or row.get("store_name") or ""
    amount = row.get("amount") if "amount" in row else row.get("total_amount")

    return {
        "id": row.get("id"),
        "사용일": spent_at,
        "가맹점": merchant,
        "금액": _int_value(amount),
        "결제수단": row.get("payment_method") or "",
        "카테고리": row.get("category") or "기타",
        "인원": row.get("detected_people_count") or None,
        "1인당": row.get("per_person_amount") or None,
        "주소": row.get("addr") or "",
        "전화번호": row.get("tel") or "",
        "메모": row.get("memo") or "",
        "Notion": row.get("notion_page_id") or "",
        "생성일": row.get("created_at") or "",
        "_raw": row,
    }


def _build_filter_parts(
    conn: Any,
    columns: set[str],
    keyword: str,
    category: str,
    start: Optional[date],
    end: Optional[date],
    min_amount: Optional[int],
    max_amount: Optional[int],
) -> Tuple[List[str], List[Any], str, str, str]:
    ph = _param_placeholder(conn)
    date_col = "spent_at" if "spent_at" in columns else "purchased_at"
    merchant_col = "merchant" if "merchant" in columns else "store_name"
    amount_col = "amount" if "amount" in columns else "total_amount"

    where: List[str] = []
    params: List[Any] = []

    if keyword:
        searchable = [merchant_col]
        if "memo" in columns:
            searchable.append("memo")
        if "raw_text" in columns:
            searchable.append("raw_text")
        where.append("(" + " OR ".join(f"{col} LIKE {ph}" for col in searchable) + ")")
        params.extend([f"%{keyword}%"] * len(searchable))

    if category and category != "전체":
        where.append(f"category = {ph}")
        params.append(category)

    if start:
        where.append(f"DATE({date_col}) >= {ph}")
        params.append(start.isoformat())

    if end:
        where.append(f"DATE({date_col}) <= {ph}")
        params.append(end.isoformat())

    if min_amount is not None:
        where.append(f"{amount_col} >= {ph}")
        params.append(min_amount)

    if max_amount is not None:
        where.append(f"{amount_col} <= {ph}")
        params.append(max_amount)

    return where, params, date_col, merchant_col, amount_col


def _build_expense_query(
    conn: Any,
    columns: set[str],
    keyword: str,
    category: str,
    start: Optional[date],
    end: Optional[date],
    min_amount: Optional[int],
    max_amount: Optional[int],
    limit: int,
) -> Tuple[str, List[Any]]:
    where, params, _date_col, _merchant_col, _amount_col = _build_filter_parts(
        conn,
        columns,
        keyword,
        category,
        start,
        end,
        min_amount,
        max_amount,
    )
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT *
        FROM expenses
        {where_sql}
        ORDER BY id DESC
        LIMIT {int(limit)}
    """
    return sql, params


def _build_monthly_query(
    conn: Any,
    columns: set[str],
    keyword: str,
    category: str,
    start: Optional[date],
    end: Optional[date],
    min_amount: Optional[int],
    max_amount: Optional[int],
) -> Tuple[str, List[Any]]:
    where, params, date_col, _merchant_col, amount_col = _build_filter_parts(
        conn,
        columns,
        keyword,
        category,
        start,
        end,
        min_amount,
        max_amount,
    )
    month_expr = f"DATE_FORMAT({date_col}, '%%Y-%%m')" if _is_mysql_connection(conn) else f"strftime('%Y-%m', {date_col})"
    where.append(f"{date_col} IS NOT NULL")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    sql = f"""
        SELECT {month_expr} AS month,
               COUNT(*) AS count,
               SUM({amount_col}) AS amount
        FROM expenses
        {where_sql}
        GROUP BY month
        ORDER BY month ASC
    """
    return sql, params


@st.cache_data(ttl=30)
def load_dashboard_data(
    db_target: str,
    keyword: str,
    category: str,
    start: Optional[date],
    end: Optional[date],
    min_amount: Optional[int],
    max_amount: Optional[int],
    limit: int,
) -> Dict[str, Any]:
    conn = get_connection(db_target)
    try:
        ensure_schema(conn)
        backend = "MySQL" if _is_mysql_connection(conn) else "SQLite"
        columns = _table_columns(conn, "expenses")
        sql, params = _build_expense_query(
            conn,
            columns,
            keyword,
            category,
            start,
            end,
            min_amount,
            max_amount,
            limit,
        )
        rows = [_normalize_expense(row) for row in _fetchall(conn, sql, params)]
        monthly_sql, monthly_params = _build_monthly_query(
            conn,
            columns,
            keyword,
            category,
            start,
            end,
            min_amount,
            max_amount,
        )
        monthly_rows = _fetchall(conn, monthly_sql, monthly_params)

        categories = _fetchall(
            conn,
            "SELECT DISTINCT category FROM expenses WHERE category IS NOT NULL AND category <> '' ORDER BY category",
        )
        total_row = _fetchone(conn, "SELECT COUNT(*) AS count FROM expenses") or {"count": 0}

        return {
            "backend": backend,
            "columns": sorted(columns),
            "rows": rows,
            "monthly_rows": monthly_rows,
            "categories": [str(row["category"]) for row in categories if row.get("category")],
            "total_count": _int_value(total_row.get("count")),
        }
    finally:
        conn.close()


def _summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_amount = sum(_int_value(row["금액"]) for row in rows)
    categories: Dict[str, int] = {}
    for row in rows:
        categories[str(row["카테고리"])] = categories.get(str(row["카테고리"]), 0) + _int_value(row["금액"])

    top_category = "-"
    if categories:
        top_category = max(categories.items(), key=lambda item: item[1])[0]

    return {
        "count": len(rows),
        "total_amount": total_amount,
        "avg_amount": round(total_amount / len(rows)) if rows else 0,
        "top_category": top_category,
    }


def _to_csv(rows: List[Dict[str, Any]]) -> str:
    output = StringIO()
    fields = ["id", "사용일", "가맹점", "금액", "결제수단", "카테고리", "인원", "1인당", "주소", "전화번호", "메모", "Notion", "생성일"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _render_filters(categories: List[str]) -> Dict[str, Any]:
    st.sidebar.header("필터")
    default_start = date.today() - timedelta(days=365)
    default_end = date.today()

    keyword = st.sidebar.text_input("검색어", placeholder="가맹점, 메모, OCR 원문")
    category = st.sidebar.selectbox("카테고리", ["전체", *categories])
    period = st.sidebar.date_input("사용 기간", value=(default_start, default_end))
    min_amount = st.sidebar.number_input("최소 금액", min_value=0, value=0, step=1000)
    max_amount = st.sidebar.number_input("최대 금액", min_value=0, value=0, step=1000)
    limit = st.sidebar.slider("표시 건수", min_value=10, max_value=500, value=100, step=10)

    if isinstance(period, tuple):
        start, end = period if len(period) == 2 else (period[0], period[0])
    else:
        start, end = period, period

    return {
        "keyword": keyword.strip(),
        "category": category,
        "start": start,
        "end": end,
        "min_amount": int(min_amount) if min_amount else None,
        "max_amount": int(max_amount) if max_amount else None,
        "limit": int(limit),
    }


def _render_monthly_charts(monthly_rows: List[Dict[str, Any]]) -> None:
    st.subheader("월별 지출 그래프")

    if not monthly_rows:
        st.info("월별 그래프를 표시할 데이터가 없습니다.")
        return

    chart_rows = [
        {
            "월": str(row.get("month") or ""),
            "금액": _int_value(row.get("amount")),
            "건수": _int_value(row.get("count")),
        }
        for row in monthly_rows
        if row.get("month")
    ]
    df = pd.DataFrame(chart_rows)

    amount_tab, count_tab = st.tabs(["월별 금액", "월별 건수"])
    with amount_tab:
        st.bar_chart(df, x="월", y="금액", use_container_width=True)
    with count_tab:
        st.line_chart(df, x="월", y="건수", use_container_width=True)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "금액": st.column_config.NumberColumn("금액", format="%d원"),
            "건수": st.column_config.NumberColumn("건수", format="%d건"),
        },
    )


def _render_detail(selected: Dict[str, Any], db_target: str) -> None:
    st.subheader("상세 내역")
    left, right = st.columns([1, 1])

    with left:
        st.write(
            {
                "ID": selected["id"],
                "사용일": str(selected["사용일"]),
                "가맹점": selected["가맹점"],
                "금액": _format_money(selected["금액"]),
                "결제수단": selected["결제수단"],
                "카테고리": selected["카테고리"],
            }
        )

    with right:
        st.write(
            {
                "인원": selected["인원"],
                "1인당": _format_money(selected["1인당"]) if selected["1인당"] != "" else "",
                "주소": selected["주소"],
                "전화번호": selected["전화번호"],
                "Notion": selected["Notion"],
                "생성일": str(selected["생성일"]),
            }
        )

    items = get_expense_items(int(selected["id"]), db_path=db_target)
    st.dataframe(items, use_container_width=True, hide_index=True)

    memo = selected.get("메모") or selected["_raw"].get("raw_text") or ""
    if memo:
        st.text_area("메모 / OCR 원문", value=str(memo), height=160, disabled=True)


def main() -> None:
    st.title("영수증 관리자")

    db_target = st.sidebar.text_input("DB Target", value=DEFAULT_DB_TARGET, type="password")
    if st.sidebar.button("새로고침"):
        st.cache_data.clear()

    initial_data = load_dashboard_data(db_target, "", "전체", None, None, None, None, 1)
    filters = _render_filters(initial_data["categories"])
    data = load_dashboard_data(db_target=db_target, **filters)
    rows = data["rows"]
    summary = _summary(rows)

    status_cols = st.columns([1, 1, 1, 1, 1])
    status_cols[0].metric("DB", data["backend"])
    status_cols[1].metric("전체 저장 건수", f"{data['total_count']:,}")
    status_cols[2].metric("조회 건수", f"{summary['count']:,}")
    status_cols[3].metric("조회 합계", _format_money(summary["total_amount"]))
    status_cols[4].metric("최다 금액 카테고리", summary["top_category"])

    table_rows = [{key: value for key, value in row.items() if key != "_raw"} for row in rows]

    _render_monthly_charts(data["monthly_rows"])

    st.subheader("지출 목록")
    st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "금액": st.column_config.NumberColumn("금액", format="%d원"),
            "1인당": st.column_config.NumberColumn("1인당", format="%d원"),
        },
    )

    st.download_button(
        "CSV 다운로드",
        data=_to_csv(table_rows),
        file_name=f"receipt_expenses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    if not rows:
        st.info("조건에 맞는 지출 내역이 없습니다.")
        return

    selected_id = st.selectbox("상세 조회", [int(row["id"]) for row in rows])
    selected = next(row for row in rows if int(row["id"]) == selected_id)
    _render_detail(selected, db_target)


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import requests  # 백엔드 API 호출을 위해 추가
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

import altair as alt
import pandas as pd
import streamlit as st

import os
import sys

# 현재 파일(admin_app.py)의 상위 폴더(pages)의 상위 폴더(ExpenseGraph) 경로를 시스템 패스에 주입합니다.
current_dir = os.path.dirname(os.path.abspath(__file__))  # C:.../ExpenseGraph/pages
parent_dir = os.path.dirname(current_dir)                 # C:.../ExpenseGraph

if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# 이제 DB 직접 조회가 아니므로 기본 타겟 상수(DEFAULT_DB_TARGET)만 가져옵니다.
from save_local_db import DEFAULT_DB_TARGET

st.set_page_config(page_title="영수증 관리자", layout="wide")


# =========================================================================
# 백엔드 API 연동 함수 (기존 로컬 DB 직접 조회 로직 대체)
# =========================================================================
def load_dashboard_data(db_target: str, **filters) -> dict:
    """
    로컬 DB를 직접 찌르지 않고, FastAPI 백엔드 서버로 요청을 위임하여 
    가공된 대시보드 데이터를 원격으로 수신합니다.
    """
    BACKEND_URL = "http://localhost:8000/api/admin/dashboard"
    
    # API 규격에 맞춰 날짜 객체 문자열 변환 및 파라미터 패킹
    payload = {
        "db_target": db_target,
        "start_date": str(filters.get("start_date")) if filters.get("start_date") else None,
        "end_date": str(filters.get("end_date")) if filters.get("end_date") else None,
        "category": filters.get("category")
    }
    
    try:
        response = requests.post(BACKEND_URL, json=payload)
        if response.status_code == 200:
            return response.json().get("data")
        else:
            st.error(f"❌ 백엔드 서버 처리 에러 (코드: {response.status_code}): {response.text}")
            return {"backend": "Error", "total_count": 0, "rows": [], "category_rows": []}
    except Exception as e:
        st.error(f"❌ 백엔드 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해 주세요: {e}")
        return {"backend": "Disconnected", "total_count": 0, "rows": [], "category_rows": []}


# =========================================================================
# UI 헬퍼 및 렌더링 함수들 (기존 비즈니스 로직 유지)
# =========================================================================
def _summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"count": 0, "total_amount": 0, "top_category": "없음"}

    total_amount = sum(row.get("금액", 0) for row in rows)
    counts: Dict[str, int] = {}
    for row in rows:
        cat = row.get("카테고리", "미분류")
        counts[cat] = counts.get(cat, 0) + 1
    top_category = max(counts, key=counts.get) if counts else "없음"

    return {
        "count": len(rows),
        "total_amount": total_amount,
        "top_category": top_category,
    }


def _format_money(val: Any) -> str:
    try:
        return f"{int(val):,}원"
    except (ValueError, TypeError):
        return "0원"


def _render_category_charts(category_rows: List[Dict[str, Any]]) -> None:
    if not category_rows:
        st.info("카테고리별 차트 데이터를 표시할 내역이 없습니다.")
        return

    df = pd.DataFrame(category_rows)
    st.subheader("📊 카테고리별 지출 통계")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**금액 기준 비율**")
        pie_chart = (
            alt.Chart(df)
            .mark_arc()
            .encode(
                theta=alt.Theta(field="금액", type="quantitative"),
                color=alt.Color(field="카테고리", type="nominal"),
                tooltip=["카테고리", "금액"],
            )
        )
        st.altair_chart(pie_chart, use_container_width=True)

    with col2:
        st.markdown("**카테고리별 총액 바 차트**")
        bar_chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X(field="카테고리", type="nominal", sort="-y"),
                y=alt.Y(field="금액", type="quantitative"),
                color=alt.Color(field="카테고리", type="nominal"),
                tooltip=["카테고리", "금액"],
            )
        )
        st.altair_chart(bar_chart, use_container_width=True)


def _to_csv_download(table_rows: List[Dict[str, Any]]) -> str:
    if not table_rows:
        return ""
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=list(table_rows[0].keys()))
    writer.writeheader()
    writer.writerows(table_rows)
    return output.getvalue()


# =========================================================================
# 메인 어플리케이션 UI 실행부
# =========================================================================
def main() -> None:

# 💡 [권한 검증 로직 추가]
    # 세션에 유저 정보가 없거나, 'admin'이 아닌 경우 화면을 가리고 차단 팝업/경고 유도
    if "user_id" not in st.session_state or st.session_state["user_id"] != "admin":
        st.title("🏛️ 영수증 관리자 대시보드 (Admin)")
        
        # 에러 메시지와 함께 접근 제한 알림 경고창 노출
        st.error("🛑 접근 권한이 없습니다. 관리자 계정(admin)으로 로그인해 주세요.")
        
        # 필요시 예쁘게 경고 모달 팝업 띄우기
        @st.dialog("⚠️ 권한 경고")
        def access_denied_popup():
            st.write(f"현재 접속 계정 계정: '{st.session_state.get('user_id', 'None')}'")
            st.write("이 페이지는 최고 관리자(admin) 전용 공간입니다. 일반 사용자는 접근할 수 없습니다.")
        
        access_denied_popup()
        st.stop() # 💡 중요: 하단의 모든 어드민 UI 및 DB 쿼리 로직 실행을 즉시 중단합니다.
            
    st.title("🏛️ 영수증 관리자 대시보드 (Admin)")
    st.caption("어드민 화면의 모든 DB 쿼리 연동 처리가 백엔드 API 레이어로 일원화되었습니다.")

    with st.sidebar:
        st.header("⚙️ 데이터베이스 구성")
        db_target = st.text_input("Database URL / File Target", value=DEFAULT_DB_TARGET)

        st.header("🔍 검색 필터링 조건")
        today = date.today()
        start_date = st.date_input("시작일", today - timedelta(days=30))
        end_date = st.date_input("종료일", today)

        # 초기 더미용 카테고리 풀 구성
        categories = ["전체", "식대", "교통비", "도서비", "비품구입비", "기타"]
        category = st.selectbox("지출 카테고리", categories)

    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
    }

    # API를 통해 백엔드 데이터 서빙 수신
    data = load_dashboard_data(db_target=db_target, **filters)
    rows = data["rows"]
    summary = _summary(rows)

    # 상단 요약 Metric 지표 카드 배치
    status_cols = st.columns([1, 1, 1, 1, 1])
    status_cols[0].metric("통신 연동 DB", data["backend"])
    status_cols[1].metric("전체 저장 건수", f"{data['total_count']:,}")
    status_cols[2].metric("조회 조건 건수", f"{summary['count']:,}")
    status_cols[3].metric("조회 조건 합계", _format_money(summary["total_amount"]))
    status_cols[4].metric("최다 금액 카테고리", summary["top_category"])

    table_rows = [{key: value for key, value in row.items() if key != "_raw"} for row in rows]

    # 시각화 렌더링 영역
    _render_category_charts(data["category_rows"])

    st.subheader("📝 상세 지출 내역 목록")
    st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "금액": st.column_config.NumberColumn("금액", format="%d원"),
            "1인당": st.column_config.NumberColumn("1인당", format="%d원"),
        },
    )

    csv_data = _to_csv_download(table_rows)
    if csv_data:
        st.download_button(
            label="📥 현재 내역 CSV 다운로드",
            data=csv_data,
            file_name=f"expense_report_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
import os
import requests
import streamlit as st
from PIL import Image

st.set_page_config(page_title="사내 내규 심사 시스템", layout="wide")

# 테스트를 위해 세션 상태에 user_id가 없으면 초기화 (기본값은 일반유저)
if "user_id" not in st.session_state:
    st.session_state["user_id"] = "user01"

st.title("📸 지능형 영수증 분석 & 사내 내규 심사 시스템")
st.caption("Streamlit Frontend + FastAPI Backend 멀티 티어 아키텍처 구성입니다.")

# [사이드바 등 테스트용 UI] 개발 과정에서 admin 권한 토글을 쉽게 하기 위함
with st.sidebar:
    st.subheader("🔑 로그인 세션 테스트")
    st.session_state["user_id"] = st.text_input("현재 접속 User ID", value=st.session_state["user_id"])
    st.caption(f"현재 권한 상태: {st.session_state['user_id']}")

# 백엔드 API 주소 정의
BACKEND_API_URL = "http://localhost:8000/api/analyze-receipt"

col1, col2 = st.columns([1, 1])

with col1:
    st.header("📥 영수증 증빙 제출")

    # 추가: user_id 입력 컴포넌트 (추후 관리자 페이지 접근 권한 판별의 기준이 됨)
    user_id = st.text_input("� 사용자 ID를 입력하세요", value="demo-user", help="관리자 페이지(admin) 접근 및 DB 기록에 사용됩니다.")

    
    # 1) 파일을 업로드하는 GUI 버튼
    uploaded_file = st.file_uploader("영수증 이미지를 업로드하세요 (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])
    
    # 2) 파일 업로드 완료 시 화면에 원본 이미지 노출
    if uploaded_file is not None:
        st.subheader("🖼️ 업로드된 원본 증빙")
        image = Image.open(uploaded_file)
        st.image(image, width="stretch")
        
        # 3) 기능 시작 버튼 클릭 제어
        execute_analysis = st.button("🔍 영수증 자동 분석 가동", type="primary")

with col2:
    st.header("📊 지능형 심사 결과 리포트")
    
    if uploaded_file is not None and 'execute_analysis' in locals() and execute_analysis:
        if not user_id.strip():
            st.error("⚠️ 분석을 진행하려면 사용자 ID를 입력해야 합니다.")
        else:
            with st.spinner("백엔드 에이전트 파이프라인 작동 중 (OCR 및 RAG 감사 연동)..."):
                try:
                    # 파일 바이트 및 멀티파트 전송용 객체 생성
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    
                    # 수정: 쿼리 스트링 매개변수로 user_id 전달
                    params = {"user_id": user_id.strip()}
                    
                    # 백엔드 FastAPI REST API 호출 (params 추가)
                    response = requests.post(BACKEND_API_URL, files=files, params=params)
                    
                    if response.status_code == 200:
                        res_data = response.json()
                        
                        if res_data.get("status") == "success":
                            result = res_data.get("data", {})
                            
                            # 4) 최종 판정 결과 컴포넌트 출력
                            st.subheader("� 최종 판정 결과")
                            status = result.get("budget_status", "정상")
                            if status == "주의":
                                st.error(f"� 위반 의심 행동 감지: [{status}] (제출자: {result.get('user_id')})")
                            else:
                                st.success(f"✅ 정산 가능 승인: [{status}] (제출자: {result.get('user_id')})")
                                
                            # 3) 최종 결과 리포트 화면 출력
                            st.subheader("� AI 감사관 상세 검토 리포트")
                            st.info(result.get("rag_violation_report", "리포트 유실"))
                            
                            # 디버그 탭 출력 (OCR 원문)
                            with st.expander("� [디버그] ocr_process_node 판독 원문"):
                                st.text(result.get("ocr_raw_text", "텍스트 유실"))
                                
                            # 파싱된 정형 내역 정렬
                            st.subheader("� 파싱된 정형 데이터 내역")
                            summary_table = {
                                "지출 식별 고유 ID": result.get("id"),
                                "사용자 ID": result.get("user_id"),
                                "가맹점명": result.get("merchant"),
                                "결제수단": result.get("payment_method"),
                                "총 결제액": f"{result.get('amount', 0):,}원",
                                "식사 인원수": f"{result.get('detected_people_count', 1)}명",
                                "1인당 금액": f"{result.get('per_person_amount', 0):,}원",
                                "가맹점 주소(addr)": result.get("addr"),
                                "전화번호": result.get("tel"),
                                "시스템 등록일시(reg_date)": result.get("reg_date")
                            }
                            st.json(summary_table)
                        else:
                            st.error(f"❌ 분석 실패: {res_data.get('message')}")
                    else:
                        st.error(f"❌ 백엔드 서버 에러 발생 (Status Code: {response.status_code})")
                except Exception as e:
                    st.error(f"❌ 백엔드 API 연결에 실패했습니다: {e}")
    else:
        st.info("좌측 컴포넌트에서 영수증 이미지를 업로드하고 분석 버튼을 누르면 백엔드에서 실시간 연산된 결과가 이곳에 출력됩니다.")

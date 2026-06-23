import os
import requests
import streamlit as st
from PIL import Image

st.set_page_config(page_title="영수증 가계부 프론트엔드", layout="wide")

st.title("📸 지능형 영수증 분석 & 사내 내규 심사 시스템")
st.caption("Streamlit Frontend + FastAPI Backend 멀티 티어 아키텍처 구성입니다.")

# 백엔드 API 주소 정의
BACKEND_API_URL = "http://localhost:8000/api/analyze-receipt"

col1, col2 = st.columns([1, 1])

with col1:
    st.header("📥 영수증 증빙 제출")
    
    # 1) 파일을 업로드하는 GUI 버튼
    uploaded_file = st.file_uploader("영수증 이미지를 업로드하세요 (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])
    
    # 2) 파일 업로드 완료 시 화면에 원본 이미지 노출
    if uploaded_file is not None:
        st.subheader("🖼️ 업로드된 원본 증빙")
        image = Image.open(uploaded_file)
        st.image(image, use_container_width=True)
        
        # 3) 기능 시작 버튼 클릭 제어
        execute_analysis = st.button("🔍 영수증 자동 분석 가동", type="primary")

with col2:
    st.header("📊 지능형 심사 결과 리포트")
    
    if uploaded_file is not None and 'execute_analysis' in locals() and execute_analysis:
        with st.spinner("백엔드 에이전트 파이프라인 작동 중 (OCR 및 RAG 감사 연동)..."):
            try:
                # 파일 바이트 및 멀티파트 전송용 객체 생성
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                
                # 백엔드 FastAPI REST API 호출
                response = requests.post(BACKEND_API_URL, files=files)
                
                if response.status_code == 200:
                    res_data = response.json()
                    
                    if res_data.get("status") == "success":
                        result = res_data.get("data", {})
                        
                        # 4) 최종 판정 결과 컴포넌트 출력
                        st.subheader("🎯 최종 판정 결과")
                        status = result.get("budget_status", "정상")
                        if status == "주의":
                            st.error(f"🚨 위반 의심 행동 감지: [{status}]")
                        else:
                            st.success(f"✅ 정산 가능 승인: [{status}]")
                            
                        # 3) 최종 결과 리포트 화면 출력
                        st.subheader("📜 AI 감사관 상세 검토 리포트")
                        st.info(result.get("rag_violation_report", "리포트 유실"))
                        
                        # 디버그 탭 출력 (OCR 원문)
                        with st.expander("🔍 [디버그] ocr_process_node 판독 원문"):
                            st.text(result.get("ocr_raw_text", "텍스트 유실"))
                            
                        # 파싱된 정형 내역 정렬
                        st.subheader("🔢 파싱된 정형 데이터 내역")
                        summary_table = {
                            "지출 식별 고유 ID": result.get("id"),
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
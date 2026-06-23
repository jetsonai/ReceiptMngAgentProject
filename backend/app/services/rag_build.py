from __future__ import annotations

import argparse
import os

from app.services.rag_service import (
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    POLICY_DOCX_PATH,
    VECTOR_STORE_PATH,
    PolicyRagService,
    build_chroma_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="외근비/출장비 내규 ChromaDB RAG 관리")
    parser.add_argument(
        "--build",
        action="store_true",
        help="DOCX 내규를 읽어 ChromaDB 인덱스를 생성하거나 갱신합니다.",
    )
    parser.add_argument(
        "--query",
        help="이미 생성된 ChromaDB에서 검색/분류만 실행합니다.",
    )
    args = parser.parse_args()

    if args.query:
        return run_query(args.query)

    # 인자를 주지 않으면 초보 실행 편의를 위해 build를 기본 동작으로 둔다.
    return run_build()


def run_build() -> int:
    print("[RAG] ChromaDB 인덱스 생성을 시작합니다.")
    print(f"[RAG] 내규 문서: {POLICY_DOCX_PATH}")
    print(f"[RAG] 저장 경로: {VECTOR_STORE_PATH}")
    print(f"[RAG] Collection: {COLLECTION_NAME}")
    print(f"[RAG] Embedding model: {EMBEDDING_MODEL}")

    if not os.getenv("OPENAI_API_KEY"):
        print("[ERROR] OPENAI_API_KEY 환경변수가 없습니다.")
        return 1

    try:
        service = build_chroma_index()
    except Exception as exc:
        print(f"[ERROR] ChromaDB 인덱스 생성 실패: {exc}")
        return 1

    if service.collection is None:
        print("[ERROR] ChromaDB collection이 생성되지 않았습니다.")
        return 1

    print("[RAG] ChromaDB 인덱스 생성이 완료되었습니다.")
    print(f"[RAG] 저장된 조항 수: {service.collection.count()}")
    print(f"[RAG] 분리된 조항 수: {len(service.chunks)}")
    return 0


def run_query(query: str) -> int:
    print("[RAG] 기존 ChromaDB 인덱스에서 검색합니다.")
    print(f"[RAG] 저장 경로: {VECTOR_STORE_PATH}")
    print(f"[RAG] query: {query}")

    if not os.getenv("OPENAI_API_KEY"):
        print("[ERROR] OPENAI_API_KEY 환경변수가 없습니다.")
        return 1

    try:
        service = PolicyRagService()
        result = service.classify(receipt_text=query)
    except Exception as exc:
        print(f"[ERROR] ChromaDB 검색 실패: {exc}")
        return 1

    print("[RAG] 검색/분류 결과")
    print(f"  - category: {result.category}")
    print(f"  - confidence: {result.confidence}")
    print(f"  - reason: {result.reason}")
    for index, rule in enumerate(result.matched_rules, start=1):
        print(f"  - matched_rule_{index}: {rule}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

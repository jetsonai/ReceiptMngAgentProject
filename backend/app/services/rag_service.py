from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
POLICY_DOCX_FILENAME = "외근비 및 출장비 지급 내규.docx"
VECTOR_STORE_PATH = APP_ROOT / "vector_store" / "chroma"
COLLECTION_NAME = "travel_expense_policy"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
JUDGE_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# RAG 원문 문서는 최종적으로 app/rag_docs 아래에 두는 것을 우선한다.
# 아직 프로젝트 구조를 단계별로 만드는 중이라 현재 루트 경로도 임시 fallback으로 지원한다.
POLICY_DOCX_PATHS = [
    APP_ROOT / "rag_docs" / POLICY_DOCX_FILENAME,
    PROJECT_ROOT / POLICY_DOCX_FILENAME,
]
POLICY_DOCX_PATH = next((path for path in POLICY_DOCX_PATHS if path.exists()), POLICY_DOCX_PATHS[0])

POLICY_CATEGORIES = [
    "식비",
    "교통",
    "숙박",
    "일비",
    "항공",
    "배송비",
    "회의비",
    "기타",
]

POLICY_DETAIL_CATEGORIES = [
    "외근 식비",
    "외근 일비",
    "국내 교통비",
    "국내 출장 식비/일비",
    "국내 숙박비",
    "해외 항공비",
    "해외 출장 식비/일비",
    "해외 숙박비",
    "해외 현지 교통비",
    "장비 운반/배송비",
    "회의비/고객 응대",
    "지급 제외",
    "기타",
]

BROAD_CATEGORY_MAP = {
    "외근 식비": "식비",
    "국내 출장 식비/일비": "식비",
    "해외 출장 식비/일비": "식비",
    "외근 일비": "일비",
    "국내 교통비": "교통",
    "해외 현지 교통비": "교통",
    "국내 숙박비": "숙박",
    "해외 숙박비": "숙박",
    "해외 항공비": "항공",
    "장비 운반/배송비": "배송비",
    "회의비/고객 응대": "회의비",
    "지급 제외": "기타",
    "기타": "기타",
}

CATEGORY_HINTS = {
    "외근 식비": ["제6조", "외근 식비", "일반 식당", "구내식당", "휴게소 식당", "조식", "중식", "석식"],
    "외근 일비": ["제7조", "외근 일비", "4시간", "8시간", "일비"],
    "국내 교통비": ["제8조", "국내 교통비", "지하철", "버스", "KTX", "SRT", "택시", "자가용", "주차비", "통행료", "유류비"],
    "국내 출장 식비/일비": ["제9조", "국내 출장 식비", "출장 일비", "출장자 개인 식비"],
    "국내 숙박비": ["제10조", "국내 숙박비", "숙박", "호텔", "모텔", "객실", "1박"],
    "해외 항공비": ["제12조", "해외 출장 항공비", "항공권", "이코노미", "비즈니스석", "노쇼", "취소 수수료"],
    "해외 출장 식비/일비": ["제13조", "해외 출장 식비", "동아시아", "동남아시아", "북미", "유럽", "현지 통화"],
    "해외 숙박비": ["제14조", "해외 숙박비", "해외 출장 숙박", "컨퍼런스", "국제 행사"],
    "해외 현지 교통비": ["제15조", "해외 현지 교통비", "공항철도", "차량 호출", "렌터카"],
    "장비 운반/배송비": ["제16조", "장비 운반", "배송비", "택배비", "퀵서비스", "화물비", "추가 수하물", "포장재"],
    "회의비/고객 응대": ["제17조", "회의비", "고객 응대", "협력사", "회의 목적", "참석자"],
    "지급 제외": ["제18조", "지급 제외", "개인적인 식사", "간식", "음료", "주류", "유흥", "마사지", "관광", "쇼핑", "과태료", "범칙금"],
}

ITEM_CATEGORY_HINTS = {
    "외근 식비": [
        "백반", "정식", "국밥", "찌개", "김치찌개", "된장찌개", "비빔밥", "덮밥", "도시락",
        "라면", "국수", "칼국수", "냉면", "분식", "김밥", "샌드위치", "햄버거", "식사",
    ],
    "국내 교통비": ["주차", "주차비", "택시", "버스", "지하철", "KTX", "SRT", "통행료", "유류비", "주유"],
    "국내 숙박비": ["숙박", "호텔", "모텔", "객실", "1박"],
    "해외 항공비": ["항공권", "항공", "비행기", "이코노미", "비즈니스석"],
    "장비 운반/배송비": ["택배", "택배비", "퀵", "퀵서비스", "화물", "배송", "수하물", "포장재"],
    "회의비/고객 응대": ["회의", "회의비", "고객", "응대", "미팅", "다과"],
    "지급 제외": [
        "아메리카노", "라떼", "커피", "음료", "간식", "케이크", "디저트", "빵", "베이커리",
        "소주", "맥주", "와인", "주류", "담배", "쇼핑",
    ],
}


@dataclass(frozen=True)
class RetrievedPolicyChunk:
    title: str
    content: str
    score: float


@dataclass(frozen=True)
class CategoryClassification:
    category: str
    policy_category: str
    payment_status: str
    confidence: float
    reason: str
    payment_reason: str
    review_result: str
    report: str
    matched_rules: list[str]


class PolicyRagService:
    """외근비/출장비 내규 DOCX를 근거로 영수증 지출 카테고리를 분류한다.

    ChromaDB 기반 RAG 흐름:
    1. DOCX 원문을 텍스트로 읽는다.
    2. "제6조 외근 식비 기준" 같은 조항 단위로 문서를 나눈다.
    3. 조항 chunk를 ChromaDB collection에 저장한다.
    4. 영수증 내용을 embedding으로 바꿔 ChromaDB에서 유사 조항을 검색한다.
    5. 검색된 조항 근거를 백엔드 정산 카테고리로 매핑한다.
    """

    def __init__(
        self,
        policy_path: Path | str = POLICY_DOCX_PATH,
        vector_store_path: Path | str = VECTOR_STORE_PATH,
        use_chroma: bool = True,
        rebuild: bool = False,
    ):
        self.policy_path = Path(policy_path)
        self.vector_store_path = Path(vector_store_path)
        self.use_chroma = use_chroma
        self.rebuild = rebuild
        self.embedder = build_openai_embedder() if self.use_chroma else None
        self.policy_text = load_docx_text(self.policy_path) if self.rebuild or not self.use_chroma else ""
        self.chunks = split_policy_articles(self.policy_text) if self.policy_text else []
        self.collection = self._get_or_create_collection() if self.use_chroma else None

    def classify(
        self,
        *,
        receipt_text: str = "",
        store_name: str = "",
        items: Iterable[str] | None = None,
        memo: str = "",
        per_person_amount: int = 0,
    ) -> CategoryClassification:
        # 벡터 검색 query는 가맹점, 메모, OCR 원문만 사용한다.
        # 품목명(items)은 검색 후 카테고리 보정 점수에만 별도로 반영한다.
        item_text = self._build_item_text(items)
        query = self._build_query(receipt_text, store_name, memo)
        retrieved = self.retrieve(query, k=3)

        if not retrieved or retrieved[0].score <= 0:
            return CategoryClassification(
                category="기타",
                policy_category="기타",
                payment_status="검토 필요",
                confidence=0.25,
                reason="내규 문서에서 관련 조항을 충분히 찾지 못해 기타로 분류했습니다.",
                payment_reason="관련 내규 근거가 부족하여 담당자 확인이 필요합니다.",
                review_result="검토 필요",
                report=(
                    "검토 필요: RAG 분류 결과 '기타', 지급여부 '검토 필요'입니다.\n"
                    "분류 근거: 내규 문서에서 관련 조항을 충분히 찾지 못했습니다.\n"
                    "지급 판단 근거: 관련 내규 근거가 부족하여 담당자 확인이 필요합니다."
                ),
                matched_rules=[],
            )

        # 검색 단계는 관련 조항을 찾고, 카테고리 선택 단계는 그 조항을 정산 항목으로 변환한다.
        policy_category, category_score = self._select_policy_category(query, retrieved, item_text)
        category = self._to_broad_category(policy_category)
        payment_status, payment_reason = self._judge_payment_status(
            policy_category=policy_category,
            query=query,
            item_text=item_text,
            chunks=retrieved,
            per_person_amount=per_person_amount,
        )
        confidence = min(0.95, 0.45 + (retrieved[0].score * 0.06) + (category_score * 0.04))
        evidence_titles = ", ".join(chunk.title for chunk in retrieved[:2])
        reason = (
            f"내규의 {evidence_titles} 조항이 영수증 내용과 가장 관련 있어 "
            f"세부 분류 '{policy_category}', 카테고리 '{category}'로 분류했습니다."
        )
        matched_rules = [format_policy_chunk(chunk) for chunk in retrieved]
        review_result = self._build_review_result(payment_status)
        report = self._build_report(
            review_result=review_result,
            category=category,
            policy_category=policy_category,
            payment_status=payment_status,
            reason=reason,
            payment_reason=payment_reason,
            confidence=round(confidence, 2),
            per_person_amount=per_person_amount,
            matched_rules=matched_rules,
        )

        return CategoryClassification(
            category=category,
            policy_category=policy_category,
            payment_status=payment_status,
            confidence=round(confidence, 2),
            reason=reason,
            payment_reason=payment_reason,
            review_result=review_result,
            report=report,
            matched_rules=matched_rules,
        )

    def retrieve(self, query: str, k: int = 3) -> list[RetrievedPolicyChunk]:
        if not self.use_chroma or self.collection is None or self.embedder is None:
            return self._retrieve_with_keyword(query, k=k)

        # OpenAI embedding으로 질의 문장을 벡터화한 뒤 ChromaDB에서 유사 조항을 검색한다.
        query_embedding = self.embedder.embed_query(query)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        retrieved: list[RetrievedPolicyChunk] = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            # Chroma의 cosine distance는 낮을수록 유사하다. 서비스 내부에서는 높을수록 좋은 score로 변환한다.
            score = max(0.0, 1.0 - float(distance))
            retrieved.append(
                RetrievedPolicyChunk(
                    title=str(metadata.get("title", "내규 조항")),
                    content=str(document),
                    score=score,
                )
            )

        return retrieved

    def _retrieve_with_keyword(self, query: str, k: int = 3) -> list[RetrievedPolicyChunk]:
        """테스트나 API 키가 없는 환경에서만 사용하는 키워드 기반 fallback 검색."""

        query_tokens = set(_tokenize(query))
        scored: list[RetrievedPolicyChunk] = []

        for title, content in self.chunks:
            content_tokens = set(_tokenize(f"{title} {content}"))
            token_hits = query_tokens.intersection(content_tokens)
            phrase_hits = sum(1 for token in query_tokens if len(token) >= 2 and token in content)
            score = float(len(token_hits) + phrase_hits)
            scored.append(RetrievedPolicyChunk(title=title, content=content, score=score))

        return sorted(scored, key=lambda chunk: chunk.score, reverse=True)[:k]

    def _get_or_create_collection(self):
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "ChromaDB를 사용하려면 'pip install chromadb'를 먼저 실행하세요."
            ) from exc

        self.vector_store_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self.vector_store_path))

        if not self.rebuild:
            try:
                return client.get_collection(COLLECTION_NAME)
            except Exception as exc:
                raise RuntimeError(
                    "ChromaDB collection이 아직 없습니다. 먼저 'python main.py --build'로 인덱스를 생성하세요."
                ) from exc

        fingerprint = build_policy_fingerprint(self.policy_path, self.chunks)

        try:
            collection = client.get_collection(COLLECTION_NAME)
            metadata = collection.metadata or {}
            if metadata.get("source_fingerprint") != fingerprint:
                client.delete_collection(COLLECTION_NAME)
                collection = self._create_collection(client, fingerprint)
        except Exception:
            collection = self._create_collection(client, fingerprint)

        if collection.count() != len(self.chunks):
            self._rebuild_collection(collection, fingerprint)

        return collection

    def _create_collection(self, client, fingerprint: str):
        return client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "source": str(self.policy_path),
                "source_fingerprint": fingerprint,
            },
        )

    def _rebuild_collection(self, collection, fingerprint: str) -> None:
        existing = collection.get()
        existing_ids = existing.get("ids", [])
        if existing_ids:
            collection.delete(ids=existing_ids)

        ids = [f"policy-article-{index}" for index, _ in enumerate(self.chunks)]
        documents = [content for _, content in self.chunks]
        metadatas = [
            {
                "title": title,
                "article_index": index,
                "source": str(self.policy_path),
                "source_fingerprint": fingerprint,
            }
            for index, (title, _) in enumerate(self.chunks)
        ]
        if self.embedder is None:
            raise RuntimeError("OpenAI embedding model is not initialized.")

        # 조항 제목과 본문을 함께 임베딩해야 "제8조 국내 교통비" 같은 제목 신호도 검색에 반영된다.
        embeddings = self.embedder.embed_documents(
            [f"{title} {content}" for title, content in self.chunks]
        )

        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def _select_policy_category(
        self,
        query: str,
        chunks: list[RetrievedPolicyChunk],
        item_text: str = "",
    ) -> tuple[str, int]:
        evidence = f"{query} " + " ".join(f"{chunk.title} {chunk.content}" for chunk in chunks)
        scored: list[tuple[str, int]] = []
        item_text_lower = item_text.lower()

        for category, hints in CATEGORY_HINTS.items():
            # CATEGORY_HINTS는 "어떤 조항/키워드가 어떤 정산 카테고리를 의미하는지"를 담은 매핑표다.
            # 예: "제8조", "주차비"가 많이 보이면 "국내 교통비" 가능성이 높다.
            score = 0
            for hint in hints:
                normalized_hint = hint.lower()
                if normalized_hint in evidence.lower():
                    score += 2 if normalized_hint.startswith("제") else 1

            # 품목명은 실제 결제 성격을 가장 직접적으로 보여주므로 더 높은 가중치로 반영한다.
            for item_hint in ITEM_CATEGORY_HINTS.get(category, []):
                if item_hint.lower() in item_text_lower:
                    score += 5

            scored.append((category, score))

        category, score = max(scored, key=lambda row: row[1])
        if score <= 0:
            return "기타", 0
        return category, score

    def _judge_payment_status(
        self,
        policy_category: str,
        query: str,
        item_text: str,
        chunks: list[RetrievedPolicyChunk],
        per_person_amount: int = 0,
    ) -> tuple[str, str]:
        llm_result = self._judge_payment_status_with_llm(
            policy_category=policy_category,
            query=query,
            item_text=item_text,
            chunks=chunks,
            per_person_amount=per_person_amount,
        )
        if llm_result is not None:
            payment_status, payment_reason = llm_result
        else:
            payment_status, payment_reason = self._judge_payment_status_by_rules(
                policy_category=policy_category,
                query=query,
                chunks=chunks,
                per_person_amount=per_person_amount,
            )

        return self._apply_safety_payment_rules(
            policy_category=policy_category,
            query=query,
            item_text=item_text,
            per_person_amount=per_person_amount,
            payment_status=payment_status,
            payment_reason=payment_reason,
        )

    def _judge_payment_status_with_llm(
        self,
        *,
        policy_category: str,
        query: str,
        item_text: str,
        chunks: list[RetrievedPolicyChunk],
        per_person_amount: int,
    ) -> tuple[str, str] | None:
        if not item_text.strip():
            return None

        try:
            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI
        except ImportError:
            return None

        policy_context = "\n".join(format_policy_chunk(chunk, max_length=500) for chunk in chunks)
        prompt = f"""
너는 회사 외근비 및 출장비 정산 심사 담당자다.
영수증 품목(items)을 가장 중요하게 보고, RAG로 검색된 내규 조항을 근거로 지급여부를 판단하라.

[영수증 품목]
{item_text}

[검색 query]
{query}

[RAG 세부 분류 후보]
{policy_category}

[1인당 금액]
{per_person_amount}원

[RAG 검색 내규]
{policy_context}

반드시 아래 JSON 하나만 반환하라.
payment_status는 "지급 가능", "지급 제외", "검토 필요" 중 하나만 사용한다.
{{
  "payment_status": "지급 가능|지급 제외|검토 필요",
  "payment_reason": "items와 내규 조항을 근거로 한 판단 이유"
}}
"""
        try:
            llm = ChatOpenAI(
                model=JUDGE_MODEL,
                temperature=0.0,
                model_kwargs={"response_format": {"type": "json_object"}},
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            data = json.loads(response.content)
        except Exception:
            return None

        payment_status = str(data.get("payment_status", "")).strip()
        payment_reason = str(data.get("payment_reason", "")).strip()
        if payment_status not in {"지급 가능", "지급 제외", "검토 필요"}:
            return None
        if not payment_reason:
            payment_reason = "LLM이 items와 내규 조항을 기준으로 지급여부를 판단했습니다."
        return payment_status, payment_reason

    @staticmethod
    def _judge_payment_status_by_rules(
        policy_category: str,
        query: str,
        chunks: list[RetrievedPolicyChunk],
        per_person_amount: int = 0,
    ) -> tuple[str, str]:
        evidence = f"{query} " + " ".join(f"{chunk.title} {chunk.content}" for chunk in chunks)

        if policy_category == "지급 제외":
            return "지급 제외", "내규의 지급 제외 항목과 직접 관련된 지출로 판단했습니다."

        if "식비" in policy_category and per_person_amount > 20000:
            return "지급 제외", "식비 1인당 금액이 내규상 석식 기준 한도 20,000원을 초과했습니다."

        excluded_keywords = [
            "개인",
            "사적",
            "주류",
            "유흥",
            "마사지",
            "관광",
            "쇼핑",
            "과태료",
            "범칙금",
            "증빙이 없는",
        ]
        if any(keyword in query for keyword in excluded_keywords):
            return "지급 제외", "영수증 내용에 지급 제외 가능성이 높은 개인/사적 지출 키워드가 포함되어 있습니다."

        approval_keywords = [
            "사전 승인",
            "비즈니스석",
            "특실",
            "렌터카",
            "숙박비 한도 초과",
            "100,000원을 초과하는 회의비",
            "고가 장비",
        ]
        if any(keyword in evidence for keyword in approval_keywords):
            return "검토 필요", "내규상 사전 승인 또는 추가 확인이 필요한 항목과 관련되어 있습니다."

        if policy_category == "기타":
            return "검토 필요", "명확한 정산 카테고리로 분류되지 않아 담당자 검토가 필요합니다."

        return "지급 가능", "검색된 내규 기준상 지급 가능한 정산 항목으로 판단했습니다."

    @staticmethod
    def _apply_safety_payment_rules(
        *,
        policy_category: str,
        query: str,
        item_text: str,
        per_person_amount: int,
        payment_status: str,
        payment_reason: str,
    ) -> tuple[str, str]:
        combined_text = f"{query} {item_text}"

        if policy_category == "지급 제외":
            return "지급 제외", "내규의 지급 제외 항목과 직접 관련된 지출로 판단했습니다."

        if "식비" in policy_category and per_person_amount > 20000:
            return "지급 제외", "식비 1인당 금액이 내규상 석식 기준 한도 20,000원을 초과했습니다."

        excluded_keywords = [
            "개인",
            "사적",
            "주류",
            "유흥",
            "마사지",
            "관광",
            "쇼핑",
            "과태료",
            "범칙금",
            "증빙이 없는",
        ]
        if any(keyword in combined_text for keyword in excluded_keywords):
            return "지급 제외", "영수증 품목 또는 원문에 지급 제외 가능성이 높은 키워드가 포함되어 있습니다."

        return payment_status, payment_reason

    @staticmethod
    def _build_review_result(payment_status: str) -> str:
        if payment_status == "지급 제외":
            return "위반"
        if payment_status == "검토 필요":
            return "검토 필요"
        return "준수"

    @staticmethod
    def _build_report(
        *,
        review_result: str,
        category: str,
        policy_category: str,
        payment_status: str,
        reason: str,
        payment_reason: str,
        confidence: float,
        per_person_amount: int,
        matched_rules: list[str],
    ) -> str:
        matched_rules_text = "\n".join(f"- {rule}" for rule in matched_rules)
        return (
            f"{review_result}: RAG 분류 결과 '{category}', 세부 분류 '{policy_category}', 지급여부 '{payment_status}'입니다.\n"
            f"분류 근거: {reason}\n"
            f"지급 판단 근거: {payment_reason}\n"
            f"신뢰도: {confidence}\n"
            f"1인당 금액: {per_person_amount:,}원\n"
            f"참조 조항:\n{matched_rules_text}"
        )

    @staticmethod
    def _to_broad_category(policy_category: str) -> str:
        return BROAD_CATEGORY_MAP.get(policy_category, "기타")

    @staticmethod
    def _build_query(
        receipt_text: str,
        store_name: str,
        memo: str,
    ) -> str:
        return f"{store_name} {memo} {receipt_text}".strip()

    @staticmethod
    def _build_item_text(items: Iterable[str] | None) -> str:
        return " ".join(str(item) for item in (items or []))


def classify_category(
    *,
    receipt_text: str = "",
    store_name: str = "",
    items: Iterable[str] | None = None,
    memo: str = "",
    use_chroma: bool = True,
    per_person_amount: int = 0,
) -> CategoryClassification:
    return PolicyRagService(use_chroma=use_chroma).classify(
        receipt_text=receipt_text,
        store_name=store_name,
        items=items,
        memo=memo,
        per_person_amount=per_person_amount,
    )


def build_chroma_index(
    policy_path: Path | str = POLICY_DOCX_PATH,
    vector_store_path: Path | str = VECTOR_STORE_PATH,
) -> PolicyRagService:
    """DOCX 내규를 읽어 ChromaDB collection을 생성하거나 최신 상태로 갱신한다."""

    return PolicyRagService(
        policy_path=policy_path,
        vector_store_path=vector_store_path,
        use_chroma=True,
        rebuild=True,
    )


def build_openai_embedder():
    """환경변수 OPENAI_API_KEY를 사용하는 OpenAI 임베딩 클라이언트를 만든다."""

    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError as exc:
        raise ImportError(
            "OpenAI 임베딩을 사용하려면 'pip install langchain-openai'를 먼저 실행하세요."
        ) from exc

    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def load_docx_text(path: Path) -> str:
    """DOCX 파일에서 사람이 읽을 수 있는 본문 텍스트를 추출한다.

    DOCX는 실제로 여러 XML 파일을 묶은 ZIP 파일이다.
    본문은 보통 word/document.xml에 들어 있으므로, 이 함수는 다음 순서로 동작한다.
    1. DOCX를 ZIP처럼 연다.
    2. word/document.xml을 읽는다.
    3. WordprocessingML XML에서 문단(w:p)과 텍스트 조각(w:t)을 찾는다.
    4. 나뉘어 있는 텍스트 조각들을 문단 단위로 합쳐 일반 문자열로 반환한다.
    """

    if not path.exists():
        raise FileNotFoundError(f"Policy DOCX file not found: {path}")

    # DOCX 파일은 ZIP 컨테이너이며, 화면에 보이는 문서 본문은 word/document.xml에 있다.
    with zipfile.ZipFile(path) as docx:
        xml = docx.read("word/document.xml")

    # Word 문서 XML은 네임스페이스가 붙어 있어 w:p, w:t를 찾을 때 namespace 정보가 필요하다.
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []

    for paragraph in root.findall(".//w:p", namespace):
        # 한 문단 안의 텍스트는 스타일 변경 등으로 여러 w:t 조각에 나뉘어 있을 수 있다.
        # 모든 w:t를 이어 붙이면 사용자가 읽는 문단 텍스트에 가까워진다.
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        text = normalize_text(text)
        if text:
            paragraphs.append(text)

    return "\n".join(paragraphs)


def split_policy_articles(policy_text: str) -> list[tuple[str, str]]:
    # 내규를 "제6조 외근 식비 기준" 같은 조항 단위 chunk로 나눈다.
    # 이 chunk가 로컬 RAG 검색의 기본 단위가 된다.
    matches = list(re.finditer(r"제\d+조\s+[^\n]+", policy_text))
    if not matches:
        return [("내규 전체", policy_text)]

    chunks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(policy_text)
        article = normalize_text(policy_text[start:end])
        title = match.group(0).strip()
        chunks.append((title, article))
    return chunks


def format_policy_chunk(chunk: RetrievedPolicyChunk, max_length: int = 260) -> str:
    content = normalize_text(chunk.content)
    if len(content) > max_length:
        content = f"{content[:max_length].rstrip()}..."
    return f"{chunk.title}: {content}"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def build_policy_fingerprint(policy_path: Path, chunks: list[tuple[str, str]]) -> str:
    stat = policy_path.stat()
    payload = f"{policy_path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{len(chunks)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[0-9a-zA-Z가-힣/]+", text.lower())

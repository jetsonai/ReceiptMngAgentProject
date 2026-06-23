from __future__ import annotations

import hashlib
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

# RAG 원문 문서는 최종적으로 app/rag_docs 아래에 두는 것을 우선한다.
# 아직 프로젝트 구조를 단계별로 만드는 중이라 현재 루트 경로도 임시 fallback으로 지원한다.
POLICY_DOCX_PATHS = [
    APP_ROOT / "rag_docs" / POLICY_DOCX_FILENAME,
    PROJECT_ROOT / POLICY_DOCX_FILENAME,
]
POLICY_DOCX_PATH = next((path for path in POLICY_DOCX_PATHS if path.exists()), POLICY_DOCX_PATHS[0])

POLICY_CATEGORIES = [
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


@dataclass(frozen=True)
class RetrievedPolicyChunk:
    title: str
    content: str
    score: float


@dataclass(frozen=True)
class CategoryClassification:
    category: str
    confidence: float
    reason: str
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
    ) -> CategoryClassification:
        # 가맹점, 품목명, 메모, OCR 원문을 하나의 검색 문장으로 합친다.
        # 영수증마다 정보가 들어오는 위치가 다를 수 있어 가능한 필드를 모두 사용한다.
        query = self._build_query(receipt_text, store_name, items, memo)
        retrieved = self.retrieve(query, k=3)

        if not retrieved or retrieved[0].score <= 0:
            return CategoryClassification(
                category="기타",
                confidence=0.25,
                reason="내규 문서에서 관련 조항을 충분히 찾지 못해 기타로 분류했습니다.",
                matched_rules=[],
            )

        # 검색 단계는 관련 조항을 찾고, 카테고리 선택 단계는 그 조항을 정산 항목으로 변환한다.
        category, category_score = self._select_category(query, retrieved)
        confidence = min(0.95, 0.45 + (retrieved[0].score * 0.06) + (category_score * 0.04))
        evidence_titles = ", ".join(chunk.title for chunk in retrieved[:2])

        return CategoryClassification(
            category=category,
            confidence=round(confidence, 2),
            reason=f"내규의 {evidence_titles} 조항이 영수증 내용과 가장 관련 있어 '{category}'로 분류했습니다.",
            matched_rules=[format_policy_chunk(chunk) for chunk in retrieved],
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

    def _select_category(self, query: str, chunks: list[RetrievedPolicyChunk]) -> tuple[str, int]:
        evidence = f"{query} " + " ".join(f"{chunk.title} {chunk.content}" for chunk in chunks)
        scored: list[tuple[str, int]] = []

        for category, hints in CATEGORY_HINTS.items():
            # CATEGORY_HINTS는 "어떤 조항/키워드가 어떤 정산 카테고리를 의미하는지"를 담은 매핑표다.
            # 예: "제8조", "주차비"가 많이 보이면 "국내 교통비" 가능성이 높다.
            score = 0
            for hint in hints:
                normalized_hint = hint.lower()
                if normalized_hint in evidence.lower():
                    score += 2 if normalized_hint.startswith("제") else 1
            scored.append((category, score))

        category, score = max(scored, key=lambda row: row[1])
        if score <= 0:
            return "기타", 0
        return category, score

    @staticmethod
    def _build_query(
        receipt_text: str,
        store_name: str,
        items: Iterable[str] | None,
        memo: str,
    ) -> str:
        item_text = " ".join(str(item) for item in (items or []))
        return f"{store_name} {item_text} {memo} {receipt_text}".strip()


def classify_category(
    *,
    receipt_text: str = "",
    store_name: str = "",
    items: Iterable[str] | None = None,
    memo: str = "",
    use_chroma: bool = True,
) -> CategoryClassification:
    return PolicyRagService(use_chroma=use_chroma).classify(
        receipt_text=receipt_text,
        store_name=store_name,
        items=items,
        memo=memo,
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

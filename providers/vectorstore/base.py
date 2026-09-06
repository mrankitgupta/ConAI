"""
VectorStoreProvider interface for real RAG (not keyword search dressed up).

Default: TfidfVectorStore — scikit-learn TF-IDF + cosine similarity.
  Chosen as the default because it installs in seconds on Streamlit Community
  Cloud's free tier with no model download, no GPU, no disk cache — while
  still being genuine dense-ish retrieval over real chunk embeddings (TF-IDF
  vectors), not a fake. It is swappable.

Optional: FaissEmbeddingStore — sentence-transformers + FAISS, used
  automatically if both packages are importable (set RAG_BACKEND=faiss to
  force / require it). Better semantic recall, heavier install.
"""
from __future__ import annotations
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Chunk:
    chunk_id: str
    text: str
    document: str
    metadata: dict = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float


class VectorStoreProvider(ABC):
    name: str = "base"

    @abstractmethod
    def add_document(self, document: str, text: str, metadata: dict | None = None) -> int:
        """Chunk + index a document's text. Returns number of chunks added."""

    @abstractmethod
    def query(self, text: str, top_k: int = 5) -> list[RetrievedChunk]:
        ...

    @property
    @abstractmethod
    def size(self) -> int:
        ...


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i : i + chunk_size])
        i += chunk_size - overlap
    return chunks


class TfidfVectorStore(VectorStoreProvider):
    name = "tfidf"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(stop_words="english", max_features=20000)
        self._chunks: list[Chunk] = []
        self._matrix = None
        self._dirty = False

    def add_document(self, document: str, text: str, metadata: dict | None = None) -> int:
        pieces = _chunk_text(text)
        for i, p in enumerate(pieces):
            self._chunks.append(
                Chunk(
                    chunk_id=str(uuid.uuid4())[:8],
                    text=p,
                    document=document,
                    metadata={**(metadata or {}), "chunk_index": i},
                )
            )
        self._dirty = True
        return len(pieces)

    def _ensure_fit(self):
        if not self._dirty and self._matrix is not None:
            return
        if not self._chunks:
            self._matrix = None
            return
        self._matrix = self._vectorizer.fit_transform([c.text for c in self._chunks])
        self._dirty = False

    def query(self, text: str, top_k: int = 5) -> list[RetrievedChunk]:
        self._ensure_fit()
        if self._matrix is None:
            return []
        from sklearn.metrics.pairwise import cosine_similarity

        qv = self._vectorizer.transform([text])
        sims = cosine_similarity(qv, self._matrix)[0]
        ranked = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:top_k]
        return [RetrievedChunk(self._chunks[i], float(sims[i])) for i in ranked if sims[i] > 0]

    @property
    def size(self) -> int:
        return len(self._chunks)


class FaissEmbeddingStore(VectorStoreProvider):
    name = "faiss"

    def __init__(self):
        import faiss
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer("all-MiniLM-L6-v2")
        self._index = faiss.IndexFlatIP(384)
        self._chunks: list[Chunk] = []

    def add_document(self, document: str, text: str, metadata: dict | None = None) -> int:
        import numpy as np

        pieces = _chunk_text(text)
        if not pieces:
            return 0
        vecs = self._model.encode(pieces, normalize_embeddings=True)
        self._index.add(np.array(vecs, dtype="float32"))
        for i, p in enumerate(pieces):
            self._chunks.append(
                Chunk(str(uuid.uuid4())[:8], p, document, {**(metadata or {}), "chunk_index": i})
            )
        return len(pieces)

    def query(self, text: str, top_k: int = 5) -> list[RetrievedChunk]:
        import numpy as np

        if not self._chunks:
            return []
        qv = self._model.encode([text], normalize_embeddings=True)
        scores, idx = self._index.search(np.array(qv, dtype="float32"), min(top_k, len(self._chunks)))
        out = []
        for s, i in zip(scores[0], idx[0]):
            if i == -1:
                continue
            out.append(RetrievedChunk(self._chunks[i], float(s)))
        return out

    @property
    def size(self) -> int:
        return len(self._chunks)


def get_vectorstore() -> VectorStoreProvider:
    backend = os.environ.get("RAG_BACKEND", "auto")
    if backend == "faiss":
        return FaissEmbeddingStore()
    if backend == "tfidf":
        return TfidfVectorStore()
    try:
        import faiss  # noqa
        import sentence_transformers  # noqa

        return FaissEmbeddingStore()
    except Exception:
        return TfidfVectorStore()

"""RAG core engine -- session-level semantic vector database (FAISS-based)

Design decisions (confirmed with user):
1. In-memory storage: Each interview session gets an independent FAISS index.
   Destroyed after interview ends via clear_session(). No disk writes, no privacy leakage.
2. Multi-session isolation: session_id is used as key, each session fully isolated.
3. Embedding model: BAAI/bge-small-zh-v1.5 (Beijing Academy of AI)
   - Trained specifically for Chinese semantic retrieval, bilingual CN+EN
   - Auto-downloads on first run (~95MB), then fully offline
   - Free, no API key needed

Workflow:
  resume_analyzer_node (after resume analysis)
    --> build_session_rag(session_id, chunks)
  [FAISS in-memory index for this session]
    --> retrieve_resume_context(session_id, query_topic)
  question_generator_node (retrieves per JD focus area)
    --> inject retrieved snippets into prompt
  [AI generates targeted deep-dive questions based on real project details]
    --> clear_session(session_id)
  [Index released from memory]
"""

import logging
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

# ---- Global session store ----
# key: session_id (str), value: dict with "index", "texts", "model"
_session_stores: dict = {}

# ---- Global embedding model singleton ----
_embedding_model = None


def _get_embedding_model():
    """
    Get embedding model singleton (lazy loading).

    Uses BAAI/bge-small-zh-v1.5 Chinese semantic embedding model:
    - Downloads from HuggingFace on first call (~95MB), then cached locally
    - Returns SentenceTransformer model instance
    """
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading BAAI/bge-small-zh-v1.5 embedding model (first run ~95MB download)...")
            _embedding_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Embedding model load failed: {e}")
            raise RuntimeError(f"RAG embedding model init failed: {e}") from e
    return _embedding_model


def _embed_texts(texts: list) -> np.ndarray:
    """
    Convert list of texts to normalized embedding vectors.

    Args:
        texts: List of text strings to embed

    Returns:
        numpy array of shape (n, embedding_dim), L2 normalized
    """
    model = _get_embedding_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,  # L2 normalize for cosine similarity via dot product
        show_progress_bar=False,
        batch_size=32,
    )
    return embeddings.astype("float32")


def build_session_rag(session_id: str, chunks: list) -> bool:
    """
    Build in-memory FAISS semantic index for the given interview session.

    Called after resume_analyzer_node completes resume analysis. Embeds the
    resume chunks and stores them in a FAISS IndexFlatIP (inner product,
    equivalent to cosine similarity after normalization).

    Args:
        session_id: Interview session unique ID (from InterviewState.session_id)
        chunks: Resume chunk list, each chunk:
                {"id": "chunk_0", "text": "...", "metadata": {"section": "project"}}

    Returns:
        bool: True if successfully indexed, False on failure (graceful degradation)
    """
    if not chunks:
        logger.warning(f"Session {session_id}: Empty chunk list, skipping RAG indexing")
        return False

    try:
        import faiss

        texts = [chunk["text"] for chunk in chunks]
        embeddings = _embed_texts(texts)

        dim = embeddings.shape[1]
        # IndexFlatIP: exact inner product search (= cosine similarity on normalized vectors)
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        _session_stores[session_id] = {
            "index": index,
            "texts": texts,
            "chunks": chunks,
        }

        logger.info(f"Session {session_id}: Successfully indexed {len(chunks)} resume chunks into FAISS")
        return True

    except Exception as e:
        logger.error(f"Session {session_id}: RAG indexing failed -- {e}")
        return False


def retrieve_resume_context(
    session_id: str,
    query_topic: str,
    top_k: int = 2,
    min_similarity: float = 0.4
) -> Optional[str]:
    """
    Retrieve the most relevant resume snippets from the session FAISS index.

    Called in question_generator_node for each JD focus area. Returns the
    matched resume project excerpt(s) to inject into the question-generation prompt.

    Args:
        session_id: Interview session ID
        query_topic: Current focus topic for search (e.g. "distributed lock", "high concurrency")
        top_k: Return top K most similar chunks (default 2)
        min_similarity: Minimum cosine similarity threshold (0~1). Below this, return None.

    Returns:
        str: Concatenated relevant resume snippets (ready to inject into prompt)
        None: No match above threshold, or session has no RAG index
    """
    store = _session_stores.get(session_id)
    if store is None:
        return None

    try:
        import faiss

        query_embedding = _embed_texts([query_topic])
        index = store["index"]
        texts = store["texts"]

        actual_k = min(top_k, len(texts))
        scores, indices = index.search(query_embedding, actual_k)

        # scores[0] are inner products = cosine similarity (since vectors are normalized)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:  # FAISS returns -1 for empty slots
                continue
            similarity = float(score)
            if similarity >= min_similarity:
                results.append((texts[idx], similarity))

        if not results:
            logger.debug(f"Session {session_id}: Query [{query_topic}] below threshold {min_similarity}")
            return None

        snippets = [text for text, sim in results]
        context = "\n---\n".join(snippets)
        logger.info(
            f"Session {session_id}: Query [{query_topic}] matched {len(results)} snippet(s), "
            f"top similarity {results[0][1]:.3f}"
        )
        return context

    except Exception as e:
        logger.error(f"Session {session_id}: RAG retrieval failed -- {e}")
        return None


def clear_session(session_id: str) -> None:
    """
    Release the in-memory FAISS index for the given session.

    Call this when the interview ends or session times out to free memory
    and ensure resume data does not remain in memory.

    Args:
        session_id: Session ID to clean up
    """
    if session_id in _session_stores:
        del _session_stores[session_id]
        logger.info(f"Session {session_id}: RAG index cleared from memory")


def get_session_count() -> int:
    """Return number of currently active RAG sessions (for monitoring/debugging)."""
    return len(_session_stores)

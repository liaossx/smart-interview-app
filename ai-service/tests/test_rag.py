"""Unit tests for RAG engine and resume chunker.

Most tests run WITHOUT needing faiss/sentence-transformers installed,
using mocks where needed.
"""
import pytest
from unittest.mock import patch, MagicMock
import numpy as np


# =====================================================================
# Resume Chunker Tests (no external deps needed)
# =====================================================================

class TestResumeChunker:
    """Tests for extract_resume_chunks function."""

    def test_extract_project_chunks(self):
        """Should extract one chunk per project plus one skills chunk."""
        from app.core.resume_chunker import extract_resume_chunks

        analysis = {
            "skills": ["Java", "Redis", "MySQL"],
            "projects": [
                {
                    "name": "SmartCommunity Platform",
                    "tech_stack": ["SpringBoot", "Redis", "RabbitMQ"],
                    "description": "High-concurrency e-commerce system",
                    "highlights": ["Redis+Lua atomic inventory deduction", "1200+ QPS"]
                },
                {
                    "name": "Parking Management System",
                    "tech_stack": ["Redisson", "MySQL"],
                    "description": "Distributed lock prevents duplicate billing",
                    "highlights": ["Redisson distributed lock", "Spring transaction integration"]
                }
            ]
        }

        chunks = extract_resume_chunks(analysis)
        assert len(chunks) == 3
        assert chunks[0]["id"] == "chunk_0"
        assert chunks[1]["id"] == "chunk_1"
        assert chunks[2]["id"] == "chunk_2"

    def test_project_chunk_contains_tech_keywords(self):
        """Project chunk text should contain tech stack and highlights."""
        from app.core.resume_chunker import extract_resume_chunks

        analysis = {
            "skills": ["Java"],
            "projects": [
                {
                    "name": "SmartCommunity",
                    "tech_stack": ["Redis", "RabbitMQ", "Lua"],
                    "description": "Seckill module",
                    "highlights": ["Atomic deduction", "Peak clipping"]
                }
            ]
        }

        chunks = extract_resume_chunks(analysis)
        project_chunk = chunks[0]
        assert "SmartCommunity" in project_chunk["text"]
        assert "Redis" in project_chunk["text"]
        assert "RabbitMQ" in project_chunk["text"]
        assert project_chunk["metadata"]["section"] == "project"

    def test_skills_chunk_is_last(self):
        """Skills chunk should always be the last chunk."""
        from app.core.resume_chunker import extract_resume_chunks

        analysis = {
            "skills": ["Java", "Redis", "MySQL", "Docker"],
            "projects": [{"name": "Test", "tech_stack": ["Java"], "highlights": ["x"]}]
        }

        chunks = extract_resume_chunks(analysis)
        skills_chunk = chunks[-1]
        assert skills_chunk["metadata"]["section"] == "skills"
        assert "Java" in skills_chunk["text"]
        assert "Redis" in skills_chunk["text"]

    def test_empty_resume_returns_empty_chunks(self):
        """Empty resume analysis should return empty list without error."""
        from app.core.resume_chunker import extract_resume_chunks
        chunks = extract_resume_chunks({})
        assert chunks == []

    def test_empty_projects_but_has_skills(self):
        """If no projects but has skills, should return just skills chunk."""
        from app.core.resume_chunker import extract_resume_chunks

        analysis = {"skills": ["Java", "Spring"], "projects": []}
        chunks = extract_resume_chunks(analysis)
        assert len(chunks) == 1
        assert chunks[0]["metadata"]["section"] == "skills"


# =====================================================================
# RAG Engine Tests (mock faiss and sentence_transformers)
# =====================================================================

class TestRagEngine:
    """Tests for rag_engine using mocked FAISS."""

    def test_build_session_rag_empty_chunks_returns_false(self):
        """build_session_rag should return False for empty chunks."""
        from app.core.rag_engine import build_session_rag
        result = build_session_rag("session_empty", [])
        assert result is False

    def test_retrieve_returns_none_for_unknown_session(self):
        """retrieve_resume_context should return None if session not in registry."""
        from app.core.rag_engine import retrieve_resume_context
        result = retrieve_resume_context("nonexistent_session_xyz", "distributed lock")
        assert result is None

    def test_clear_session_removes_from_registry(self):
        """clear_session should remove session from the registry."""
        from app.core import rag_engine
        rag_engine._session_stores["test_clear_session"] = {"index": MagicMock(), "texts": []}
        assert "test_clear_session" in rag_engine._session_stores

        from app.core.rag_engine import clear_session
        clear_session("test_clear_session")
        assert "test_clear_session" not in rag_engine._session_stores

    def test_get_session_count(self):
        """get_session_count should return current registry size."""
        from app.core import rag_engine
        from app.core.rag_engine import get_session_count, clear_session

        initial_count = get_session_count()
        rag_engine._session_stores["count_test_1"] = {"index": MagicMock(), "texts": []}
        rag_engine._session_stores["count_test_2"] = {"index": MagicMock(), "texts": []}
        assert get_session_count() == initial_count + 2

        clear_session("count_test_1")
        clear_session("count_test_2")
        assert get_session_count() == initial_count

    def test_build_session_rag_success_with_mocks(self):
        """build_session_rag should return True and populate store when mocks work."""
        import sys
        import types
        from app.core import rag_engine

        # Mock faiss
        mock_index = MagicMock()
        mock_faiss = types.ModuleType("faiss")
        mock_faiss.IndexFlatIP = MagicMock(return_value=mock_index)
        sys.modules["faiss"] = mock_faiss

        # Mock embedding model
        fake_embeddings = np.random.rand(2, 512).astype("float32")
        rag_engine._embedding_model = MagicMock()
        rag_engine._embedding_model.encode = MagicMock(return_value=fake_embeddings)

        chunks = [
            {"id": "c0", "text": "Redis distributed lock project", "metadata": {"section": "project"}},
            {"id": "c1", "text": "RabbitMQ peak clipping async", "metadata": {"section": "project"}},
        ]
        result = rag_engine.build_session_rag("test_faiss_mock", chunks)
        assert result is True
        assert "test_faiss_mock" in rag_engine._session_stores
        mock_index.add.assert_called_once()

        # Cleanup
        rag_engine.clear_session("test_faiss_mock")
        rag_engine._embedding_model = None
        sys.modules.pop("faiss", None)

    def test_retrieve_with_mocked_index(self):
        """retrieve_resume_context should return text when similarity is above threshold."""
        import sys
        import types
        from app.core import rag_engine

        # Mock faiss
        mock_faiss = types.ModuleType("faiss")
        sys.modules["faiss"] = mock_faiss

        # Mock embedding model
        fake_query_emb = np.random.rand(1, 512).astype("float32")
        rag_engine._embedding_model = MagicMock()
        rag_engine._embedding_model.encode = MagicMock(return_value=fake_query_emb)

        # Manually insert a mock store
        mock_index = MagicMock()
        # Simulate FAISS returning score=0.85 for index 0
        mock_index.search = MagicMock(
            return_value=(np.array([[0.85]]), np.array([[0]]))
        )
        rag_engine._session_stores["retrieve_test"] = {
            "index": mock_index,
            "texts": ["Redis Lua atomic seckill project highlight"],
            "chunks": [{"id": "c0", "text": "Redis Lua atomic seckill", "metadata": {}}],
        }

        result = rag_engine.retrieve_resume_context("retrieve_test", "high concurrency seckill", min_similarity=0.5)
        assert result is not None
        assert "Redis" in result

        # Cleanup
        rag_engine.clear_session("retrieve_test")
        rag_engine._embedding_model = None
        sys.modules.pop("faiss", None)

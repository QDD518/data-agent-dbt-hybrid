"""RAG keyword retriever — unit tests (no LLM / no PG needed)."""

import pytest
from backend.rag.retriever import retrieve_context, _tokenize


class TestTokenize:
    def test_latin_words(self):
        tokens = _tokenize("revenue orders customers")
        assert "revenue" in tokens
        assert "orders" in tokens
        assert "customers" in tokens

    def test_latin_lowercased(self):
        tokens = _tokenize("Revenue ORDERS")
        assert "revenue" in tokens
        assert "orders" in tokens

    def test_cjk_unigrams(self):
        tokens = _tokenize("营收")
        assert "营" in tokens
        assert "收" in tokens

    def test_cjk_bigrams(self):
        tokens = _tokenize("营收")
        assert "营收" in tokens

    def test_cjk_long_string(self):
        tokens = _tokenize("总营收是多少")
        assert "营收" in tokens
        assert "少" in tokens

    def test_mixed_latin_cjk(self):
        tokens = _tokenize("revenue 营收")
        assert "revenue" in tokens
        assert "营收" in tokens

    def test_digits(self):
        tokens = _tokenize("order_123")
        assert "order_123" in tokens


class TestRetrieveContext:
    def test_returns_documents(self):
        results = retrieve_context("营收", top_k=3)
        assert len(results) > 0
        assert isinstance(results[0], str)

    def test_english_query(self):
        results = retrieve_context("revenue", top_k=3)
        assert len(results) > 0

    def test_chinese_query(self):
        results = retrieve_context("订单量是多少", top_k=3)
        assert len(results) > 0

    def test_empty_query_returns_docs(self):
        results = retrieve_context("", top_k=3)
        assert len(results) > 0

    def test_top_k_respected(self):
        results = retrieve_context("revenue", top_k=2)
        assert len(results) <= 2

    def test_no_duplicates(self):
        results = retrieve_context("revenue", top_k=5)
        assert len(results) == len(set(results))

    def test_relevant_for_metric_question(self):
        """A metric question should return metric-related docs."""
        results = retrieve_context("revenue 是怎么计算的", top_k=3)
        combined = " ".join(results).lower()
        assert any(w in combined for w in ["revenue", "metric", "total", "amount"])

"""Unit tests for embedder retry + OCR text extraction + Lance index guard."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import httpx
import pytest

from backend.core.embedder import HTTPOpenAIEmbeddings
from backend.core.ocr_client import _extract_texts_from_ocr_item


class TestExtractOcrText:
    def test_markdown_text(self):
        item = {"layoutParsingResults": [{"markdown": {"text": "hello"}}]}
        assert _extract_texts_from_ocr_item(item) == "hello"

    def test_rec_texts_fallback_when_markdown_empty(self):
        item = {
            "layoutParsingResults": [
                {
                    "markdown": {"text": ""},
                    "prunedResult": {"rec_texts": ["line A", "line B"]},
                }
            ]
        }
        out = _extract_texts_from_ocr_item(item)
        assert "line A" in out and "line B" in out

    def test_nested_overall_ocr_res(self):
        item = {
            "layoutParsingResults": [
                {
                    "prunedResult": {
                        "overall_ocr_res": {"rec_texts": ["chart title", "42%"]}
                    }
                }
            ]
        }
        out = _extract_texts_from_ocr_item(item)
        assert "chart title" in out

    def test_empty(self):
        assert _extract_texts_from_ocr_item({}) == ""
        assert _extract_texts_from_ocr_item({"layoutParsingResults": []}) == ""


class TestEmbedderRetry:
    def _emb(self):
        return HTTPOpenAIEmbeddings(
            api_base="https://api.example.com/v1",
            api_key="k",
            model="m",
        )

    def test_retries_on_request_error_then_succeeds(self):
        emb = self._emb()
        emb._max_retries = 3
        emb._retry_backoff = 0  # no sleep

        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}

        with patch("backend.core.embedder.httpx.Client") as client_cls, patch(
            "backend.core.embedder.time.sleep"
        ):
            client = MagicMock()
            client_cls.return_value.__enter__.return_value = client
            client.post.side_effect = [
                httpx.ConnectError("boom"),
                ok,
            ]
            out = emb._call_api("hello")
        assert out == [[0.1, 0.2]]
        assert client.post.call_count == 2

    def test_retries_on_503_then_zero(self):
        emb = self._emb()
        emb._max_retries = 2
        emb._retry_backoff = 0
        bad = MagicMock()
        bad.status_code = 503
        bad.text = "unavailable"
        with patch("backend.core.embedder.httpx.Client") as client_cls, patch(
            "backend.core.embedder.time.sleep"
        ), patch("backend.config.settings") as s:
            s.EMBEDDINGS_DIMENSION = 4
            # re-read dims inside method uses settings from import; patch getattr path
            client = MagicMock()
            client_cls.return_value.__enter__.return_value = client
            client.post.return_value = bad
            with patch.object(
                __import__("backend.core.embedder", fromlist=["settings"]),
                "settings",
            ) as st:
                st.EMBEDDINGS_DIMENSION = 4
                st.EMBEDDING_PROVIDER = "x"
                out = emb._call_api("hi")
        assert len(out) == 1
        assert out[0] == [0.0] * len(out[0])

    def test_embed_documents_retries_zero_items(self):
        emb = self._emb()
        emb._max_retries = 1
        emb._retry_backoff = 0
        # First batch call returns zeros, single retry returns real
        with patch.object(emb, "_call_api") as m:
            m.side_effect = [
                [[0.0, 0.0], [0.5, 0.5]],  # batch
                [[0.1, 0.2]],  # retry index 0
            ]
            out = emb.embed_documents(["a", "b"])
        assert out[0] == [0.1, 0.2]
        assert out[1] == [0.5, 0.5]
        assert m.call_count == 2


class TestLanceIndexAttempts:
    def test_no_positional_vector_metric(self):
        """Source must not call create_index('vector') — Lance treats that as metric."""
        import inspect
        from backend.vector_store import lance_db as ldb

        src = inspect.getsource(ldb.ensure_vector_ann_index)
        assert 'create_index("vector")' not in src
        assert "create_index('vector')" not in src
        assert 'metric="cosine"' in src or "metric='cosine'" in src

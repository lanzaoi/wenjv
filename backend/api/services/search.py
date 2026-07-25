"""Document search orchestration."""
from __future__ import annotations

from typing import List, Optional, Tuple
import hashlib

from backend.config import settings
from backend.vector_store.adapter import vector_db
from backend.core.logging import get_logger
from backend.core.rerank_client import rerank
from backend.core.mmr import mmr_diversify
from backend.api.services.structured_recall import search_resources
from backend.vector_store.lance_db import fetch_documents_by_resource

vector_store = vector_db()


async def search_documents(
    *,
    prompt: str,
    user_email: str,
    include_sources: Optional[List[str]] = None,
    exclude_sources: Optional[List[str]] = None,
    window_size: int = 5,
    source_type: Optional[str] = None,
    user_id: Optional[int] = None,
) -> List[Tuple[object, float]]:
    """Return list of (Document, score).

    score is engine-native distance/similarity — see RAG notes in UPGRADE_ROADMAP.
    """
    kwargs = dict(
        include_selected=include_sources,
        exclude_selected=exclude_sources,
        window_size=window_size,
        username=user_email,
        prompt=prompt,
        source_type=source_type,
    )
    mmr_enabled = getattr(settings, "MMR_ENABLED", False)
    pool_size = getattr(settings, "RERANK_CANDIDATES", 20)
    fetch_limit = pool_size if mmr_enabled else window_size

    kwargs["window_size"] = fetch_limit

    # Backends that accept user_id (Lance) will use it; others ignore via TypeError fallback
    try:
        vector_results = vector_store.fetch_documents(**kwargs, user_id=user_id)
    except TypeError:
        vector_results = vector_store.fetch_documents(
            include_sources,
            exclude_sources,
            fetch_limit,
            user_email,
            prompt,
            source_type,
        )

    if not getattr(settings, "HYBRID_SEARCH_ENABLED", False):
        final_results = vector_results
    else:
        # ----- L2: 词法列表 K -----
        backend_mode = getattr(settings, "HYBRID_KEYWORD_BACKEND", "fts5")

        def _fetch_like():
            if not hasattr(vector_store, "fetch_documents_keyword"):
                return []
            try:
                return vector_store.fetch_documents_keyword(**kwargs, user_id=user_id)
            except Exception:
                return []

        def _fetch_fts5():
            try:
                from backend.database import sync_engine
                from backend.core.fts5_utils import match_fts5
                from langchain.schema import Document
                
                uid = user_id
                if uid is None and user_email:
                    # Resolve real user_id to avoid FTS isolation breach or paralysis 
                    from sqlalchemy.orm import Session
                    from backend.api.models import User
                    try:
                        with Session(sync_engine) as session:
                            u = session.query(User).filter(User.email == user_email).first()
                            if u:
                                uid = u.id
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                
                if uid is None:
                    return []
                
                with sync_engine.connect() as conn:
                    raw_conn = conn.connection.dbapi_connection
                    rows = match_fts5(raw_conn, prompt, user_id=uid, belongs_to=user_email, limit=fetch_limit * 5)
                    
                docs = []
                for row in rows:
                    metadata = {
                        "id": row.get("chunk_id"),
                        "title": row.get("title"),
                        "filename": row.get("filename"),
                        "source_type": row.get("source_type"),
                        "user_id": row.get("user_id"),
                        "link_id": row.get("link_id")
                    }
                    metadata = {k: v for k, v in metadata.items() if v is not None}
                    
                    doc = Document(page_content=row.get("page_content", ""), metadata=metadata)
                    docs.append((doc, 0.0))
                return docs
            except Exception:
                import traceback
                traceback.print_exc()
                return []

        def _get_stable_id(doc):
            doc_id = doc.metadata.get("id")
            if doc_id:
                return doc_id
            return hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()

        def _fetch_structured():
            if not getattr(settings, "STRUCTURED_RECALL_ENABLED", False):
                return []
            
            try:
                uid = user_id
                if uid is None and user_email:
                    from sqlalchemy.orm import Session
                    from backend.database import sync_engine
                    from backend.api.models import User
                    with Session(sync_engine) as session:
                        u = session.query(User).filter(User.email == user_email).first()
                        if u:
                            uid = u.id
                
                if uid is None:
                    return []
                    
                structured_limit = getattr(settings, "STRUCTURED_RECALL_LIMIT", 20)
                resources = search_resources(prompt, uid, limit=structured_limit)
                
                docs = []
                for res in resources:
                    # fetch chunks from lance
                    chunks = fetch_documents_by_resource(
                        resource_id=res["resource_id"], 
                        source_type=res["source_type"],
                        user_id=uid,
                        username=user_email
                    )
                    docs.extend(chunks)
                    
                return docs
            except Exception as e:
                import traceback
                traceback.print_exc()
                return []

        if backend_mode == "like":
            kw_results = _fetch_like()
        elif backend_mode == "fts5":
            kw_results = _fetch_fts5()
        else:  # fallback
            kw_results = _fetch_fts5()

        structured_results = _fetch_structured()

        if not kw_results and not structured_results:
            final_results = vector_results
        else:
            # ----- L3: 融合 -----
            max_dist = getattr(settings, "HYBRID_VECTOR_MAX_DISTANCE", 0.8)
            filtered_vector_results = [(d, s) for d, s in vector_results if s < max_dist]
            k = getattr(settings, "HYBRID_RRF_K", 5)
            w_v = getattr(settings, "HYBRID_RRF_WEIGHT_VECTOR", 1.0)
            w_k = getattr(settings, "HYBRID_RRF_WEIGHT_KEYWORD", 1.0)
            w_s = getattr(settings, "HYBRID_RRF_WEIGHT_STRUCTURED", 1.0)
            
            w_v = max(0.0, float(w_v))
            w_k = max(0.0, float(w_k))
            w_s = max(0.0, float(w_s))
            
            rrf_scores = {}
            doc_map = {}

            if w_v > 0:
                for rank, (doc, _dist) in enumerate(filtered_vector_results, 1):
                    doc_id = _get_stable_id(doc)
                    doc_map[doc_id] = doc
                    rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_v / (k + rank)

            if w_k > 0:
                for rank, (doc, _dist) in enumerate(kw_results, 1):
                    doc_id = _get_stable_id(doc)
                    doc_map[doc_id] = doc
                    rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_k / (k + rank)

            if w_s > 0:
                for rank, (doc, _dist) in enumerate(structured_results, 1):
                    doc_id = _get_stable_id(doc)
                    doc_map[doc_id] = doc
                    rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_s / (k + rank)

            # Sort by descending RRF score
            sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
            
            final_results = []
            for doc_id, score in sorted_docs[:fetch_limit]:
                final_results.append((doc_map[doc_id], 1.0 / score if score > 0 else float('inf')))

    if getattr(settings, "RERANK_ENABLED", False) and len(final_results) > 0:
        from backend.core.rerank_client import rerank
        try:
            docs_to_rerank = final_results[:fetch_limit]
            docs_content = [res[0].page_content for res in docs_to_rerank]

            rerank_results = await rerank(prompt, docs_content)

            if rerank_results is not None and len(rerank_results) > 0:
                # Rerank succeeded: rebuild in new order by relevance_score
                reranked_final = []
                for item in rerank_results:
                    original_idx = item["index"]
                    score = item["relevance_score"]
                    doc = docs_to_rerank[original_idx][0]
                    reranked_final.append((doc, score))
                final_results = reranked_final
            # else: rerank failed (None) or empty — keep original final_results
        except Exception as e:
            import logging
            logging.getLogger(settings.LOGGER_NAME).error(f"Rerank failed: {e}")

    if mmr_enabled and len(final_results) > window_size:
        from backend.core.mmr import mmr_diversify
        try:
            query_vec = vector_store.embeddings.embed_query(prompt)
            contents = [res[0].page_content for res in final_results]
            doc_vecs = vector_store.embeddings.embed_documents(contents)
            
            candidates = []
            for i, res in enumerate(final_results):
                doc_id = res[0].metadata.get("id", str(i))
                candidates.append((doc_id, doc_vecs[i], res))
                
            lambda_ = getattr(settings, "MMR_LAMBDA", 0.7)
            final_results = mmr_diversify(query_vec, candidates, window_size, lambda_=lambda_)
        except Exception as e:
            import logging
            logging.getLogger(settings.LOGGER_NAME).error(f"MMR diversification failed: {e}")
            final_results = final_results[:window_size]
    else:
        final_results = final_results[:window_size]
        
    return final_results


def format_search_hits(
    docs_with_scores,
    *,
    source_type: Optional[str],
    window_size: int,
):
    """Apply link URL de-dupe policy used by the API."""
    results = []
    uniq_sources = set()
    for doc, score in docs_with_scores:
        source = doc.metadata.get("source", "")
        if source_type == "link" and len(uniq_sources) >= window_size:
            break
        if source_type == "link" and source in uniq_sources:
            continue
        results.append((doc, score, source))
        if source not in uniq_sources:
            uniq_sources.add(source)
    return results, uniq_sources

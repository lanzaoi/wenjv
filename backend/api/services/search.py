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
import time
import asyncio
from backend.core.observability import ObsLogger
from backend.core.query_classifier import classify

vector_store = vector_db()
logger = get_logger()
obs_logger = ObsLogger()


def _get_stable_id(doc):
    doc_id = doc.metadata.get("id")
    if doc_id:
        return doc_id
    return hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()


def _resolve_user_id(user_id: Optional[int], user_email: str) -> int:
    if user_id is not None:
        return user_id
    if user_email:
        try:
            from sqlalchemy.orm import Session
            from backend.database import sync_engine
            from backend.api.models import User
            with Session(sync_engine) as session:
                u = session.query(User).filter(User.email == user_email).first()
                if u and u.id is not None:
                    return u.id
        except Exception:
            pass
    return -1


def _compute_query_hash(prompt: str, include_sources: Optional[List[str]], exclude_sources: Optional[List[str]], source_type: Optional[str], window_size: int) -> str:
    import json
    data = {
        "p": prompt,
        "inc": sorted(include_sources) if include_sources else None,
        "exc": sorted(exclude_sources) if exclude_sources else None,
        "st": source_type,
        "w": window_size,
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _get_query_cache(query_hash: str, user_id: int) -> Optional[List[Tuple[object, float]]]:
    if not getattr(settings, "QUERY_CACHE_ENABLED", True):
        return None
    try:
        import unittest.mock
        if isinstance(vector_store, (unittest.mock.Mock, unittest.mock.MagicMock, unittest.mock.AsyncMock)):
            return None
        from sqlalchemy.orm import Session
        from backend.database import get_cache_engine, QueryResultCacheTable
        from datetime import datetime, timezone
        from langchain.schema import Document
        import json

        try:
            QueryResultCacheTable.__table__.create(bind=get_cache_engine(), checkfirst=True)
        except Exception:
            pass

        with Session(get_cache_engine()) as session:
            row = session.get(QueryResultCacheTable, (query_hash, user_id))
            if row:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                expires = row.expires_at.replace(tzinfo=None) if row.expires_at.tzinfo else row.expires_at
                if now < expires and row.result_json:
                    items = json.loads(row.result_json)
                    docs = [
                        (Document(page_content=item.get("page_content", ""), metadata=item.get("metadata", {})), float(item.get("score", 0.0)))
                        for item in items
                    ]
                    return docs
                elif now >= expires:
                    session.delete(row)
                    session.commit()
    except Exception as e:
        logger.warning(f"Query cache get failed (fail-open): {e}")
    return None


def _set_query_cache(query_hash: str, user_id: int, results: List[Tuple[object, float]]) -> None:
    if not getattr(settings, "QUERY_CACHE_ENABLED", True) or not results:
        return
    try:
        import unittest.mock
        if isinstance(vector_store, (unittest.mock.Mock, unittest.mock.MagicMock, unittest.mock.AsyncMock)):
            return
        from sqlalchemy.orm import Session
        from backend.database import get_cache_engine, QueryResultCacheTable
        from datetime import datetime, timezone, timedelta
        import json

        try:
            QueryResultCacheTable.__table__.create(bind=get_cache_engine(), checkfirst=True)
        except Exception:
            pass

        ttl = getattr(settings, "QUERY_CACHE_TTL_SECONDS", 300)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).replace(tzinfo=None)

        top_10 = results[:10]
        items = []
        for doc, score in top_10:
            content = getattr(doc, "page_content", "")
            meta = getattr(doc, "metadata", {})
            items.append({
                "page_content": content,
                "metadata": meta,
                "score": float(score)
            })
        result_json = json.dumps(items, ensure_ascii=False)

        with Session(get_cache_engine()) as session:
            try:
                row = session.get(QueryResultCacheTable, (query_hash, user_id))
                if row:
                    row.result_json = result_json
                    row.expires_at = expires_at
                else:
                    new_row = QueryResultCacheTable(
                        query_hash=query_hash,
                        user_id=user_id,
                        result_json=result_json,
                        expires_at=expires_at
                    )
                    session.add(new_row)
                session.commit()
            except Exception:
                session.rollback()
                try:
                    row = session.get(QueryResultCacheTable, (query_hash, user_id))
                    if row:
                        row.result_json = result_json
                        row.expires_at = expires_at
                        session.commit()
                except Exception:
                    session.rollback()
    except Exception as e:
        logger.warning(f"Query cache set failed (fail-open): {e}")



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
    start_time = time.perf_counter()
    v_hits = 0
    fts5_hits = 0
    s_hits = 0
    total_hits = 0
    cache_hit = False
    error_msg = None

    try:
        uid = _resolve_user_id(user_id, user_email)
        query_hash = _compute_query_hash(prompt, include_sources, exclude_sources, source_type, window_size)
        cached_docs = _get_query_cache(query_hash, uid)
        if cached_docs is not None:
            cache_hit = True
            total_hits = len(cached_docs[:window_size])
            return cached_docs[:window_size]

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

        # Late chunking: search doc-level embeddings first
        if getattr(settings, "LATE_CHUNKING_ENABLED", False):
            return _late_chunking_search(
                prompt, user_email, window_size, user_id, source_type,
                include_sources, exclude_sources, user_id
            )

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
            v_hits = len({_get_stable_id(doc) for doc, _ in vector_results})
            total_hits = len(final_results)
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
                v_hits = len({_get_stable_id(doc) for doc, _ in vector_results})
                total_hits = len(final_results)
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

                if getattr(settings, "QUERY_CLASSIFIER_ENABLED", False):
                    q_type = classify(prompt)
                    max_w = float(getattr(settings, "QUERY_CLASSIFIER_MAX_WEIGHT", 5.0))
                    if q_type == "short_keyword":
                        boost = float(getattr(settings, "QUERY_CLASSIFIER_SHORT_KEYWORD_BOOST", 2.0))
                        w_k = min(max_w, max(0.0, w_k * boost))
                    elif q_type == "long_question":
                        boost = float(getattr(settings, "QUERY_CLASSIFIER_LONG_QUESTION_BOOST", 2.0))
                        w_v = min(max_w, max(0.0, w_v * boost))

                v_hits = len({_get_stable_id(doc) for doc, _ in filtered_vector_results})
                fts5_hits = len({_get_stable_id(doc) for doc, _ in kw_results})
                s_hits = len({_get_stable_id(doc) for doc, _ in structured_results})
                
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
                total_hits = len(sorted_docs)
                
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
            mode = getattr(settings, "MMR_MODE", "standard")

            if mode == "same_resource":
                # 同 resource_id 内只保留最高分 chunk
                # ⚠️ RRF 融合后 score 越高越好，比较方向是 > 不是 <
                deduped: dict = {}
                for doc_tuple in final_results:
                    doc = doc_tuple[0]
                    score = doc_tuple[1]
                    rid = doc.metadata.get("resource_id") or doc.metadata.get("title", "")
                    if not rid:
                        rid = doc.metadata.get("id", str(hash(doc.page_content)))
                    if rid not in deduped or score > deduped[rid][1]:
                        deduped[rid] = (doc, score)
                final_results = sorted(deduped.values(), key=lambda x: x[1], reverse=True)

            if len(final_results) > window_size:
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
            
        final_results = await asyncio.to_thread(_expand_context, final_results, window_size)
        _set_query_cache(query_hash, uid, final_results)
        return final_results
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        try:
            await asyncio.to_thread(
                obs_logger.log,
                query=prompt,
                latency_ms=latency_ms,
                v_hits=v_hits,
                fts5_hits=fts5_hits,
                s_hits=s_hits,
                total_hits=total_hits,
                cache_hit=cache_hit,
                error=error_msg,
            )
        except Exception as log_err:
            logger.warning(f"Failed to record observability log: {log_err}")


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


def _fetch_chunks_by_ids(ids: List[str]) -> dict:
    if not ids:
        return {}
    id_to_content = {}
    try:
        from backend.vector_store.adapter import vector_db
        vs = vector_db()
        if hasattr(vs, "db") and hasattr(vs, "TABLE_NAME"):
            table = vs.db.open_table(vs.TABLE_NAME)
            cond = " OR ".join(f"id = '{str(i)}'" for i in ids)
            df = table.search(None).where(cond).limit(len(ids) + 10).to_pandas()
            for _, row in df.iterrows():
                id_to_content[str(row["id"])] = str(row["page_content"])
        elif hasattr(vs, "collection") and hasattr(vs.collection, "get"):
            res = vs.collection.get(ids=ids)
            for i, doc in zip(res.get("ids", []), res.get("documents", [])):
                id_to_content[str(i)] = str(doc)
        elif hasattr(vs, "client") and hasattr(vs, "COLLECTION_NAME"):
            res = vs.client.query(collection_name=vs.COLLECTION_NAME, filter=f"id in {ids}", output_fields=["id", "page_content"])
            for r in res:
                id_to_content[str(r["id"])] = str(r["page_content"])
    except Exception as e:
        logger.warning(f"Error fetching chunks by ids: {e}")
    return id_to_content


def _late_chunking_search(prompt, user_email, window_size, user_id, source_type, include_sources, exclude_sources, uid):
    """Late chunking: recall docs via doc_embeddings table, then score chunks within those docs."""
    import numpy as np
    from backend.database import sync_engine, DocEmbeddingTable
    from sqlalchemy.orm import Session
    from langchain.schema import Document

    # Embed query
    query_vec = np.array(vector_store.embeddings.embed_query(prompt), dtype=np.float32)

    top_docs = getattr(settings, "LATE_CHUNKING_TOP_DOCS", 5)
    doc_scores = []
    with Session(sync_engine) as session:
        rows = session.query(DocEmbeddingTable).all()
        for row in rows:
            doc_vec = np.frombuffer(row.embedding, dtype=np.float32)
            sim = float(np.dot(query_vec, doc_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-10))
            doc_scores.append((row.resource_id, sim))
    doc_scores.sort(key=lambda x: x[1], reverse=True)
    top_rids = [rid for rid, _ in doc_scores[:top_docs]]

    # Fetch all chunks for top docs from LanceDB
    from backend.vector_store.lance_db import fetch_documents_by_resource
    all_chunks = []
    for rid in top_rids:
        chunks = fetch_documents_by_resource(rid, source_type or "note", user_id=uid, username=user_email)
        all_chunks.extend(chunks)

    # Re-score chunks against query
    scored = []
    for doc, _ in all_chunks:
        cvec = np.array(vector_store.embeddings.embed_query(doc.page_content), dtype=np.float32)
        sim = float(np.dot(query_vec, cvec) / (
            np.linalg.norm(query_vec) * np.linalg.norm(cvec) + 1e-10))
        scored.append((doc, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:window_size]


def _expand_context(results: List, window_size: int) -> List:
    if not getattr(settings, "CHUNK_EXPAND_ENABLED", False) or not results:
        return results[:window_size]
    
    window = getattr(settings, "CHUNK_EXPAND_WINDOW", 2)
    expanded_results = []
    
    try:
        from sqlalchemy.orm import Session
        from backend.database import sync_engine, ChunkMappingTable
        from langchain_core.documents import Document
        
        with Session(sync_engine) as session:
            for item in results[:window_size]:
                try:
                    doc = item[0]
                    score = item[1]
                    chunk_id = _get_stable_id(doc)
                    if not chunk_id:
                        expanded_results.append(item)
                        continue
                        
                    mapping_row = session.query(ChunkMappingTable).filter(ChunkMappingTable.chunk_id == str(chunk_id)).first()
                    if not mapping_row:
                        expanded_results.append(item)
                        continue
                        
                    group_id = mapping_row.chunk_group
                    center_order = mapping_row.chunk_order
                    
                    neighbor_rows = session.query(ChunkMappingTable).filter(
                        ChunkMappingTable.chunk_group == group_id,
                        ChunkMappingTable.chunk_order >= center_order - window,
                        ChunkMappingTable.chunk_order <= center_order + window
                    ).order_by(ChunkMappingTable.chunk_order).all()
                    
                    if not neighbor_rows:
                        expanded_results.append(item)
                        continue
                        
                    neighbor_ids = [r.chunk_id for r in neighbor_rows]
                    id_to_content = _fetch_chunks_by_ids(neighbor_ids)
                    
                    id_to_content[str(chunk_id)] = doc.page_content
                    
                    ordered_contents = []
                    for nid in neighbor_ids:
                        if nid in id_to_content and id_to_content[nid].strip():
                            ordered_contents.append(id_to_content[nid].strip())
                            
                    if not ordered_contents:
                        expanded_results.append(item)
                        continue
                        
                    merged_content = "\n\n".join(ordered_contents)
                    new_doc = Document(page_content=merged_content, metadata=dict(doc.metadata))
                    new_doc.metadata["expanded_from_chunk"] = str(chunk_id)
                    expanded_results.append((new_doc, score))
                except Exception as chunk_err:
                    logger.warning(f"Fail-open expanding chunk {item[0].metadata.get('id')}: {chunk_err}")
                    expanded_results.append(item)
    except Exception as e:
        logger.warning(f"Fail-open in _expand_context: {e}")
        return results[:window_size]
        
    return expanded_results[:window_size]

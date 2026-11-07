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


def truncate_by_score_gap(
    items: List[Tuple[Any, float]],
    min_keep: int = 2,
    max_keep: int = 8,
    rel_gap_threshold: float = 0.40,
) -> List[Tuple[Any, float]]:
    """
    Apply relative drop-off (Elbow/Cliff) truncation on sorted reranked documents.
    Detects when relevance score drops by more than rel_gap_threshold compared to the previous item,
    trimming the noisy long tail while preserving at least min_keep high-confidence matches.
    """
    if len(items) <= min_keep:
        return items[:max_keep]

    cutoff = min(len(items), max_keep)
    for i in range(min_keep, cutoff):
        prev_score = items[i - 1][1]
        curr_score = items[i][1]
        if prev_score > 0 and (prev_score - curr_score) / prev_score >= rel_gap_threshold:
            return items[:i]
    return items[:max_keep]


import re
from backend.api.services.tags import normalize_tags, resolve_sources_by_tags


def extract_inline_tags(prompt: str) -> Tuple[str, List[str]]:
    """Extract #tags from prompt text, returning cleaned prompt and extracted tags."""
    if not prompt:
        return prompt, []
    pattern = re.compile(r"(?:^|\s)#([\w\u4e00-\u9fa5]{2,24})(?=\s|[，。！？,\.!?]|$)")
    extracted = [m.group(1) for m in pattern.finditer(prompt)]
    if not extracted:
        return prompt, []
    cleaned_prompt = pattern.sub(" ", prompt).strip()
    cleaned_prompt = re.sub(r"\s+", " ", cleaned_prompt)
    return (cleaned_prompt or prompt), normalize_tags(extracted)


def _compute_query_hash(
    prompt: str,
    include_sources: Optional[List[str]],
    exclude_sources: Optional[List[str]],
    source_type: Optional[str],
    window_size: int,
    tags: Optional[List[str]] = None,
    query_image_bytes: Optional[bytes] = None,
) -> str:
    import json
    img_sig = None
    if query_image_bytes:
        img_sig = hashlib.sha256(query_image_bytes).hexdigest()[:16]

    data = {
        "p": prompt,
        "inc": sorted(include_sources) if include_sources else None,
        "exc": sorted(exclude_sources) if exclude_sources else None,
        "st": source_type,
        "w": window_size,
        "tg": sorted(tags) if tags else None,
        "img": img_sig,
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


_cache_table_initialized = False


def _ensure_cache_table():
    global _cache_table_initialized
    if not _cache_table_initialized:
        try:
            from backend.database import get_cache_engine, QueryResultCacheTable
            QueryResultCacheTable.__table__.create(bind=get_cache_engine(), checkfirst=True)
            _cache_table_initialized = True
        except Exception:
            pass


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

        _ensure_cache_table()

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

        _ensure_cache_table()

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
    tags: Optional[List[str]] = None,
    lost_in_the_middle: bool = False,
    query_image_bytes: Optional[bytes] = None,
) -> List[Tuple[object, float]]:
    """Return list of (Document, score).

    score is engine-native distance/similarity — see RAG notes in UPGRADE_ROADMAP.
    """
    start_time = time.perf_counter()
    timings = {}
    v_hits = 0
    fts5_hits = 0
    s_hits = 0
    total_hits = 0
    cache_hit = False
    error_msg = None

    try:
        uid = _resolve_user_id(user_id, user_email)

        # Parse inline hashtags from prompt and combine with explicit tags parameter
        clean_prompt, inline_tags = extract_inline_tags(prompt)
        all_target_tags = normalize_tags((tags or []) + inline_tags)

        # Layer 1 Pre-filter mapping via SQLite
        source_tag_scores: dict[str, int] = {}
        tag_matched_rids: list[int] = []
        tag_sources: list[str] = []
        effective_includes = include_sources

        if all_target_tags and uid != -1:
            source_tag_scores, tag_matched_rids, tag_sources = resolve_sources_by_tags(uid, all_target_tags)
            if tag_sources:
                if include_sources:
                    matched_common = [s for s in include_sources if s in tag_sources]
                    effective_includes = matched_common if matched_common else ["__no_match_tag__"]
                else:
                    effective_includes = list(tag_sources)
            else:
                effective_includes = ["__no_match_tag__"]

        query_hash = _compute_query_hash(
            clean_prompt or prompt,
            effective_includes,
            exclude_sources,
            source_type,
            window_size,
            all_target_tags if all_target_tags else None,
            query_image_bytes=query_image_bytes,
        )
        
        t0 = time.perf_counter()
        cached_docs = _get_query_cache(query_hash, uid)
        timings["query_cache"] = (time.perf_counter() - t0) * 1000.0
        
        if cached_docs is not None:
            cache_hit = True
            total_hits = len(cached_docs[:window_size])
            return cached_docs[:window_size]

        kwargs = dict(
            include_selected=effective_includes,
            exclude_selected=exclude_sources,
            window_size=window_size,
            username=user_email,
            prompt=clean_prompt or prompt,
            source_type=source_type,
        )
        mmr_enabled = getattr(settings, "MMR_ENABLED", False)
        rerank_enabled = getattr(settings, "RERANK_ENABLED", False)
        pool_size = getattr(settings, "RERANK_CANDIDATES", 30)
        fetch_limit = pool_size if (mmr_enabled or rerank_enabled) else window_size
        if all_target_tags and effective_includes:
            fetch_limit = max(fetch_limit * 3, 20)

        # Late chunking: search doc-level embeddings first
        if getattr(settings, "LATE_CHUNKING_ENABLED", False):
            return _late_chunking_search(
                clean_prompt or prompt, user_email, window_size, user_id, source_type,
                effective_includes, exclude_sources, user_id
            )

        kwargs["window_size"] = fetch_limit

        # Backends that accept user_id (Lance) will use it; others ignore via TypeError fallback
        def _do_vector():
            t0 = time.perf_counter()
            try:
                res = vector_store.fetch_documents(**kwargs, user_id=user_id)
            except TypeError:
                res = vector_store.fetch_documents(
                    effective_includes,
                    exclude_sources,
                    fetch_limit,
                    user_email,
                    clean_prompt or prompt,
                    source_type,
                )
            timings["vector_leg"] = (time.perf_counter() - t0) * 1000.0
            return res

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
                
                uid_fts = uid
                if uid_fts is None or uid_fts == -1:
                    return []
                
                # Multiply fetch limit for keywords if set
                multiplier = getattr(settings, "SEARCH_FETCH_MULTIPLIER", 1)
                
                with sync_engine.connect() as conn:
                    raw_conn = conn.connection.dbapi_connection
                    rows = match_fts5(
                        raw_conn,
                        clean_prompt or prompt,
                        user_id=uid_fts,
                        belongs_to=user_email,
                        limit=fetch_limit * 5 * multiplier,
                        include_sources=effective_includes,
                        source_type=source_type,
                    )
                    
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
                multiplier = getattr(settings, "SEARCH_FETCH_MULTIPLIER", 1)
                resources = search_resources(prompt, uid, limit=structured_limit * multiplier)
                
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

        if getattr(settings, "SEARCH_PARALLEL_LEGS", True):
            # Parallel execution
            tasks = [asyncio.to_thread(_do_vector)]
            if getattr(settings, "HYBRID_SEARCH_ENABLED", False):
                def _do_keyword():
                    t0 = time.perf_counter()
                    res = _fetch_like() if backend_mode == "like" else _fetch_fts5()
                    timings["keyword_leg"] = (time.perf_counter() - t0) * 1000.0
                    return res
                    
                def _do_structured():
                    t0 = time.perf_counter()
                    res = _fetch_structured()
                    timings["structured_leg"] = (time.perf_counter() - t0) * 1000.0
                    return res
                    
                tasks.append(asyncio.to_thread(_do_keyword))
                tasks.append(asyncio.to_thread(_do_structured))
            
            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            if getattr(settings, "HYBRID_SEARCH_ENABLED", False):
                kw_results = gathered[1] if (len(gathered) > 1 and not isinstance(gathered[1], Exception)) else []
                structured_results = gathered[2] if (len(gathered) > 2 and not isinstance(gathered[2], Exception)) else []
                if isinstance(gathered[0], Exception):
                    if kw_results or structured_results:
                        logger.warning(f"Vector search failed (fail-open): {gathered[0]}")
                        timings["vector_error"] = str(gathered[0])
                        vector_results = []
                    else:
                        raise gathered[0]
                else:
                    vector_results = gathered[0]
            else:
                if isinstance(gathered[0], Exception):
                    raise gathered[0]
                vector_results = gathered[0]
        else:
            # Sequential execution
            try:
                vector_results = _do_vector()
            except Exception as v_err:
                if getattr(settings, "HYBRID_SEARCH_ENABLED", False):
                    logger.warning(f"Vector search failed sequentially (fail-open): {v_err}")
                    timings["vector_error"] = str(v_err)
                    vector_results = []
                else:
                    raise
            if getattr(settings, "HYBRID_SEARCH_ENABLED", False):
                t0 = time.perf_counter()
                if backend_mode == "like":
                    kw_results = _fetch_like()
                else:
                    kw_results = _fetch_fts5()
                timings["keyword_leg"] = (time.perf_counter() - t0) * 1000.0
                
                t0 = time.perf_counter()
                structured_results = _fetch_structured()
                timings["structured_leg"] = (time.perf_counter() - t0) * 1000.0

        vis_results = []
        if getattr(settings, "VISUAL_SEARCH_ENABLED", False):
            import unittest.mock
            if not isinstance(vector_store, (unittest.mock.Mock, unittest.mock.MagicMock, unittest.mock.AsyncMock)):
                t0 = time.perf_counter()
                try:
                    from backend.vector_store.lance_db import fetch_visual_documents
                    vis_hits = await asyncio.to_thread(
                        fetch_visual_documents,
                        prompt=(clean_prompt or prompt) if not query_image_bytes else None,
                        image_bytes=query_image_bytes,
                        window_size=fetch_limit,
                        username=user_email,
                        user_id=uid if uid != -1 else None,
                        source_type=source_type,
                    )
                    timings["visual_leg"] = (time.perf_counter() - t0) * 1000.0
                    vis_results = [(doc, dist) for doc, dist, _ in vis_hits]
                except Exception as vis_err:
                    logger.warning(f"Visual cross-modal search leg failed (non-fatal): {vis_err}")

        def _check_doc_tag_match(doc) -> Tuple[bool, int]:
            if not all_target_tags:
                return False, 0
            fn = doc.metadata.get("filename")
            src = doc.metadata.get("source")
            title = doc.metadata.get("title")
            rid = doc.metadata.get("resource_id") or doc.metadata.get("file_id")

            best_overlap = 0
            for k in (fn, src, title):
                if k and k in source_tag_scores:
                    best_overlap = max(best_overlap, source_tag_scores[k])

            if best_overlap == 0 and rid:
                try:
                    if int(rid) in tag_matched_rids:
                        best_overlap = 1
                except Exception:
                    pass

            return (best_overlap > 0), best_overlap

        if not getattr(settings, "HYBRID_SEARCH_ENABLED", False):
            if vis_results:
                k = getattr(settings, "HYBRID_RRF_K", 5)
                w_v = getattr(settings, "HYBRID_RRF_WEIGHT_VECTOR", 1.0)
                w_vis = getattr(settings, "HYBRID_RRF_WEIGHT_VISUAL", 1.0)
                rrf_scores = {}
                doc_map = {}
                for rank, (doc, _dist) in enumerate(vector_results, 1):
                    doc_id = _get_stable_id(doc)
                    doc_map[doc_id] = doc
                    rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_v / (k + rank)
                for rank, (doc, _dist) in enumerate(vis_results, 1):
                    doc_id = _get_stable_id(doc)
                    doc_map[doc_id] = doc
                    rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_vis / (k + rank)
                sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
                final_results = [(doc_map[doc_id], 1.0 / score if score > 0 else float('inf')) for doc_id, score in sorted_docs[:fetch_limit]]
            else:
                final_results = vector_results
            v_hits = len({_get_stable_id(doc) for doc, _ in vector_results})
            total_hits = len(final_results)
            if all_target_tags:
                for doc, _ in final_results:
                    is_match, overlap = _check_doc_tag_match(doc)
                    doc.metadata["tag_matched"] = is_match
                    doc.metadata["matched_tags_count"] = overlap
        else:

            if not kw_results and not structured_results:
                if vis_results:
                    k = getattr(settings, "HYBRID_RRF_K", 5)
                    w_v = getattr(settings, "HYBRID_RRF_WEIGHT_VECTOR", 1.0)
                    w_vis = getattr(settings, "HYBRID_RRF_WEIGHT_VISUAL", 1.0)
                    rrf_scores = {}
                    doc_map = {}
                    for rank, (doc, _dist) in enumerate(vector_results, 1):
                        doc_id = _get_stable_id(doc)
                        doc_map[doc_id] = doc
                        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_v / (k + rank)
                    for rank, (doc, _dist) in enumerate(vis_results, 1):
                        doc_id = _get_stable_id(doc)
                        doc_map[doc_id] = doc
                        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_vis / (k + rank)
                    sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
                    final_results = [(doc_map[doc_id], 1.0 / score if score > 0 else float('inf')) for doc_id, score in sorted_docs[:fetch_limit]]
                else:
                    final_results = vector_results
                v_hits = len({_get_stable_id(doc) for doc, _ in vector_results})
                total_hits = len(final_results)
                if all_target_tags:
                    for doc, _ in final_results:
                        is_match, overlap = _check_doc_tag_match(doc)
                        doc.metadata["tag_matched"] = is_match
                        doc.metadata["matched_tags_count"] = overlap
            else:
                # ----- L3: 融合 -----
                t0 = time.perf_counter()
                max_dist = getattr(settings, "HYBRID_VECTOR_MAX_DISTANCE", 0.8)
                filtered_vector_results = [(d, s) for d, s in vector_results if s < max_dist]
                k = getattr(settings, "HYBRID_RRF_K", 5)
                w_v = getattr(settings, "HYBRID_RRF_WEIGHT_VECTOR", 1.0)
                w_k = getattr(settings, "HYBRID_RRF_WEIGHT_KEYWORD", 1.0)
                w_s = getattr(settings, "HYBRID_RRF_WEIGHT_STRUCTURED", 1.0)
                w_vis = getattr(settings, "HYBRID_RRF_WEIGHT_VISUAL", 1.0)
                
                w_v = max(0.0, float(w_v))
                w_k = max(0.0, float(w_k))
                w_s = max(0.0, float(w_s))
                w_vis = max(0.0, float(w_vis))

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

                if w_vis > 0 and vis_results:
                    for rank, (doc, _dist) in enumerate(vis_results, 1):
                        doc_id = _get_stable_id(doc)
                        doc_map[doc_id] = doc
                        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + w_vis / (k + rank)

                if all_target_tags:
                    for doc_id, doc in doc_map.items():
                        is_match, overlap = _check_doc_tag_match(doc)
                        doc.metadata["tag_matched"] = is_match
                        if is_match:
                            doc.metadata["matched_tags_count"] = overlap
                            tag_boost = 2.0 * (overlap / max(1, len(all_target_tags)))
                            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + tag_boost
                        else:
                            doc.metadata["tag_matched"] = False

                # Sort by descending RRF score
                sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
                total_hits = len(sorted_docs)
                
                final_results = []
                for doc_id, score in sorted_docs[:fetch_limit]:
                    final_results.append((doc_map[doc_id], 1.0 / score if score > 0 else float('inf')))
                timings["fusion_leg"] = (time.perf_counter() - t0) * 1000.0

        if getattr(settings, "RERANK_ENABLED", False) and len(final_results) > 0:
            t0 = time.perf_counter()
            from backend.core.rerank_client import rerank
            try:
                docs_to_rerank = final_results[:fetch_limit]
                docs_content = [res[0].page_content for res in docs_to_rerank]

                rerank_results = await rerank(prompt, docs_content)

                if rerank_results is not None and len(rerank_results) > 0:
                    # Rerank succeeded: rebuild in new order by relevance_score
                    reranked_final = []
                    for item in rerank_results:
                        original_idx = item.get("index")
                        if original_idx is None or original_idx < 0 or original_idx >= len(docs_to_rerank):
                            logger.warning(f"Rerank result index {original_idx} out of range [0, {len(docs_to_rerank)})")
                            continue
                        score = item.get("relevance_score", 0.0)
                        doc = docs_to_rerank[original_idx][0]
                        reranked_final.append((doc, score))

                    # Apply relative drop-off (cliff gap) truncation to trim noisy long tail
                    min_keep = getattr(settings, "RERANK_MIN_KEEP", 2)
                    rel_gap = getattr(settings, "RERANK_REL_GAP_THRESHOLD", 0.40)
                    final_results = truncate_by_score_gap(
                        reranked_final,
                        min_keep=min_keep,
                        max_keep=window_size,
                        rel_gap_threshold=rel_gap,
                    )
                # else: rerank failed (None) or empty — keep original final_results
            except Exception as e:
                import logging
                logging.getLogger(settings.LOGGER_NAME).error(f"Rerank failed: {e}")
            finally:
                timings["rerank_leg"] = (time.perf_counter() - t0) * 1000.0

        if mmr_enabled and len(final_results) > window_size:
            t0 = time.perf_counter()
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
            timings["mmr_leg"] = (time.perf_counter() - t0) * 1000.0
            
        final_results = await asyncio.to_thread(_expand_context, final_results, window_size)
        if getattr(settings, "CONTEXT_DEOVERLAP_MERGE_ENABLED", True):
            final_results = await asyncio.to_thread(deoverlap_and_merge_adjacent_chunks, final_results)

        if all_target_tags and len(final_results) < window_size:
            # Layer 2: Soft-fallback recall top-up with unconstrained search
            try:
                fallback_results = await search_documents(
                    prompt=clean_prompt or prompt,
                    user_email=user_email,
                    include_sources=include_sources,
                    exclude_sources=exclude_sources,
                    window_size=window_size,
                    source_type=source_type,
                    user_id=user_id,
                    tags=None,
                    query_image_bytes=query_image_bytes,
                )
                existing_ids = {_get_stable_id(doc) for doc, _ in final_results}
                for fb_doc, fb_score in fallback_results:
                    fb_id = _get_stable_id(fb_doc)
                    if fb_id not in existing_ids:
                        fb_doc.metadata["tag_matched"] = False
                        fb_doc.metadata["tag_fallback"] = True
                        final_results.append((fb_doc, fb_score))
                        existing_ids.add(fb_id)
                        if len(final_results) >= window_size:
                            break
            except Exception as fb_err:
                logger.warning(f"Tag recall fallback top-up failed: {fb_err}")

        if lost_in_the_middle and len(final_results) > 2:
            final_results = arrange_lost_in_the_middle(final_results)

        _set_query_cache(query_hash, uid, final_results)
        return final_results
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        timings["total"] = latency_ms
        if getattr(settings, "SEARCH_TIMING_ENABLED", False):
            try:
                import json
                logger.info(f"search_timings: {json.dumps(timings)}")
            except Exception as e:
                pass
            
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
    """Apply link URL de-dupe policy and enrich visual asset URLs."""
    import urllib.parse
    results = []
    uniq_sources = set()
    for doc, score in docs_with_scores:
        source = doc.metadata.get("source", "")
        if source_type == "link" and len(uniq_sources) >= window_size:
            break
        if source_type == "link" and source in uniq_sources:
            continue

        img_path = doc.metadata.get("image_path")
        has_img = bool(
            img_path
            or (
                str(doc.metadata.get("filename") or "").lower().endswith(".pdf")
                and doc.metadata.get("page")
            )
        )
        img_url = None
        if img_path:
            img_url = f"/api/documents/assets/image?path={urllib.parse.quote(str(img_path))}"
        elif str(doc.metadata.get("filename") or "").lower().endswith(".pdf") and doc.metadata.get("page"):
            pdf_fn = doc.metadata.get("filename")
            page_no = doc.metadata.get("page")
            img_url = f"/api/documents/assets/image?pdf={urllib.parse.quote(str(pdf_fn))}&page={page_no}"

        doc.metadata["has_image"] = has_img
        doc.metadata["image_path"] = img_path
        doc.metadata["image_url"] = img_url

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
            try:
                res_rows = table.search(None).where(cond).select(["id", "page_content"]).limit(len(ids) + 10).to_list()
                for row in res_rows:
                    id_to_content[str(row["id"])] = str(row["page_content"])
            except Exception:
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


def deduplicate_overlap_text(text1: str, text2: str, max_check: int = 250) -> str:
    """
    If suffix of text1 matches prefix of text2, strip the duplicate prefix.
    Also handles complete substring containment.
    """
    t1 = text1.rstrip()
    t2 = text2.lstrip()
    if not t1:
        return t2
    if not t2:
        return t1
    if t2 in t1:
        return t1
    if t1 in t2:
        return t2

    limit = min(len(t1), len(t2), max_check)
    overlap_len = 0
    for l in range(limit, 8, -1):
        if t1.endswith(t2[:l]):
            overlap_len = l
            break

    if overlap_len > 0:
        return t1 + "\n" + t2[overlap_len:].lstrip()
    return t1 + "\n\n" + t2


def deoverlap_and_merge_adjacent_chunks(results: List) -> List:
    """
    Merge adjacent or overlapping chunks from the same chunk_group into a single Document.
    Deduplicates overlapping boundary text.
    """
    if not getattr(settings, "CONTEXT_DEOVERLAP_MERGE_ENABLED", True) or len(results) <= 1:
        return results

    try:
        from sqlalchemy.orm import Session
        from backend.database import sync_engine, ChunkMappingTable
        from langchain_core.documents import Document

        missing_ids = []
        for doc, _ in results:
            chunk_id = _get_stable_id(doc)
            c_group = doc.metadata.get("chunk_group")
            c_order = doc.metadata.get("chunk_order")
            if (c_group is None or c_order is None) and chunk_id:
                missing_ids.append(str(chunk_id))

        db_mappings = {}
        if missing_ids:
            with Session(sync_engine) as session:
                rows = session.query(ChunkMappingTable).filter(ChunkMappingTable.chunk_id.in_(missing_ids)).all()
                for r in rows:
                    db_mappings[r.chunk_id] = (r.chunk_group, r.chunk_order)

        doc_infos = []
        for item in results:
            doc, score = item[0], item[1]
            chunk_id = _get_stable_id(doc)
            c_group = doc.metadata.get("chunk_group")
            c_order = doc.metadata.get("chunk_order")
            if (c_group is None or c_order is None) and chunk_id in db_mappings:
                c_group, c_order = db_mappings[chunk_id]

            doc_infos.append({
                "item": item,
                "doc": doc,
                "score": score,
                "chunk_id": str(chunk_id) if chunk_id else None,
                "chunk_group": str(c_group) if c_group is not None else None,
                "chunk_order": int(c_order) if c_order is not None else None,
            })

        merged_results = []
        seen = set()

        for i, info_i in enumerate(doc_infos):
            if i in seen:
                continue

            grp = info_i["chunk_group"]
            order = info_i["chunk_order"]

            if grp is None or order is None:
                merged_results.append(info_i["item"])
                seen.add(i)
                continue

            cluster = [info_i]
            seen.add(i)

            for j in range(i + 1, len(doc_infos)):
                if j in seen:
                    continue
                info_j = doc_infos[j]
                if info_j["chunk_group"] == grp and info_j["chunk_order"] is not None:
                    if any(abs(m["chunk_order"] - info_j["chunk_order"]) <= 1 for m in cluster):
                        cluster.append(info_j)
                        seen.add(j)

            if len(cluster) == 1:
                merged_results.append(cluster[0]["item"])
            else:
                cluster.sort(key=lambda x: x["chunk_order"])
                merged_text = cluster[0]["doc"].page_content
                merged_meta = dict(cluster[0]["doc"].metadata)
                best_score = cluster[0]["score"]

                for member in cluster[1:]:
                    merged_text = deduplicate_overlap_text(merged_text, member["doc"].page_content)

                merged_meta["merged_chunks"] = [m["chunk_id"] for m in cluster if m["chunk_id"]]
                merged_meta["chunk_order_span"] = [cluster[0]["chunk_order"], cluster[-1]["chunk_order"]]
                merged_doc = Document(page_content=merged_text, metadata=merged_meta)
                merged_results.append((merged_doc, best_score))

        return merged_results
    except Exception as e:
        logger.warning(f"Fail-open in deoverlap_and_merge_adjacent_chunks: {e}")
        return results


def arrange_lost_in_the_middle(items: List) -> List:
    """
    Reorder items to combat Lost-in-the-Middle attention bias in LLMs.
    The highest-scoring items are placed at the beginning and the end of the context,
    with lower-scoring items placed in the middle.
    
    Given items sorted by score descending: [0, 1, 2, 3, 4]
    - Item 0 (best) -> index 0 (prompt head)
    - Item 1 (2nd)  -> index -1 (prompt tail)
    - Item 2 (3rd)  -> index 1
    - Item 3 (4th)  -> index -2
    - Item 4 (5th)  -> index 2
    """
    if len(items) <= 2:
        return list(items)

    result = [None] * len(items)
    left = 0
    right = len(items) - 1

    for idx, item in enumerate(items):
        if idx % 2 == 0:
            result[left] = item
            left += 1
        else:
            result[right] = item
            right -= 1

    return result


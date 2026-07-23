"""Document search orchestration."""
from __future__ import annotations

from typing import List, Optional, Tuple

from backend.vector_store.adapter import vector_db

vector_store = vector_db()


def search_documents(
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
    # Backends that accept user_id (Lance) will use it; others ignore via TypeError fallback
    try:
        return vector_store.fetch_documents(**kwargs, user_id=user_id)
    except TypeError:
        return vector_store.fetch_documents(
            include_sources,
            exclude_sources,
            window_size,
            user_email,
            prompt,
            source_type,
        )


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

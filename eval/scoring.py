def score_hits(hits: list[dict], relevant_pids: set[str], k_values: tuple = (5, 10)) -> dict:
    """
    Score a single query's retrieved hits against its ground truth relevant PIDs.
    
    hits: list of dicts, e.g. [{'pid': '123', 'rank': 1, ...}, ...]
          Assume hits are ordered by rank (or sorted by 'rank' field if present).
    relevant_pids: set of str representing ground truth relevant passage IDs.
    k_values: tuple of integers for Recall@k and Hit@k computation.
    """
    max_k = max(k_values) if k_values else 10
    
    # Initialize dynamic dictionary
    res = {
        "reciprocal_rank": 0.0,
        "n_rel_retrieved": 0,
        "n_rel_total": len(relevant_pids) if relevant_pids else 0,
    }
    for k in k_values:
        res[f"hit_at_{k}"] = False
        res[f"recall_at_{k}"] = 0.0
        
    if not relevant_pids:
        return res
        
    n_rel_total = len(relevant_pids)
    
    # Sort hits by rank just in case, treating 1-indexed ranks properly
    sorted_hits = sorted(hits, key=lambda x: x.get("rank", 9999))
    
    first_relevant_rank = None
    rel_in_top_k = {k: 0 for k in k_values}
    total_rel_retrieved = 0
    
    seen_rel = set()
    
    for i, hit in enumerate(sorted_hits):
        rank = hit.get("rank", i + 1)
        pid_val = hit.get("pid")
        
        # Prevent str(None) -> "None" bug and ignore empty/invalid PIDs
        if pid_val is None or str(pid_val).strip() in ("", "None"):
            continue
        pid = str(pid_val).strip()
        
        if pid in relevant_pids and pid not in seen_rel:
            seen_rel.add(pid)
            total_rel_retrieved += 1
            
            if first_relevant_rank is None and rank <= max_k:
                first_relevant_rank = rank
                
            for k in k_values:
                if rank <= k:
                    rel_in_top_k[k] += 1

    reciprocal_rank = (1.0 / first_relevant_rank) if first_relevant_rank is not None else 0.0
    res["reciprocal_rank"] = reciprocal_rank
    res["n_rel_retrieved"] = total_rel_retrieved
    
    for k in k_values:
        res[f"hit_at_{k}"] = rel_in_top_k[k] > 0
        res[f"recall_at_{k}"] = rel_in_top_k[k] / n_rel_total
        
    return res


def summarize(per_query_scores: list[dict], k_values: tuple = (5, 10)) -> dict:
    """
    Aggregate per-query scores into overall evaluation summary.
    """
    max_k = max(k_values) if k_values else 10
    res = {
        f"MRR@{max_k}": 0.0,
        "n_queries": 0,
        "n_no_hits": 0,
    }
    for k in k_values:
        res[f"Recall@{k}"] = 0.0
        
    if not per_query_scores:
        return res
        
    n_queries = len(per_query_scores)
    total_mrr = sum(s.get("reciprocal_rank", 0.0) for s in per_query_scores)
    
    res[f"MRR@{max_k}"] = total_mrr / n_queries
    res["n_queries"] = n_queries
    res["n_no_hits"] = sum(1 for s in per_query_scores if not s.get(f"hit_at_{max_k}", False))
    
    for k in k_values:
        total_rk = sum(s.get(f"recall_at_{k}", 0.0) for s in per_query_scores)
        res[f"Recall@{k}"] = total_rk / n_queries
        
    return res

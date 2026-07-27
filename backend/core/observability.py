from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, desc
from loguru import logger

from backend.database import sync_engine, QueryLogsTable


class ObsLogger:
    """Observability logger and statistics aggregator for RAG queries."""

    def __init__(self, engine=sync_engine):
        self.engine = engine
        self.fts5_zero_hit_streak = 0
        self.latency_streak = 0
        self.error_streak = 0
        self.last_alert_times = {
            "fts5_zero_hit": 0.0,
            "latency": 0.0,
            "error": 0.0,
        }
        try:
            QueryLogsTable.__table__.create(bind=self.engine, checkfirst=True)
            from backend.database import ApiCallCountsTable
            ApiCallCountsTable.__table__.create(bind=self.engine, checkfirst=True)
        except Exception as e:
            logger.warning(f"Failed to create observability tables: {e}")

    def reset_alert_streaks(self) -> None:
        """Reset all consecutive alert streak counters and timestamps."""
        self.fts5_zero_hit_streak = 0
        self.latency_streak = 0
        self.error_streak = 0
        self.last_alert_times = {
            "fts5_zero_hit": 0.0,
            "latency": 0.0,
            "error": 0.0,
        }

    def _check_alerts(self, latency_ms: float, fts5_hits: int, error: Optional[str]) -> None:
        import time
        import logging
        from backend.config import settings
        
        now = time.time()
        cooldown = getattr(settings, "OBS_ALERT_COOLDOWN_SECONDS", 300)
        
        def _emit_alert(msg: str, alert_key: str):
            if now - self.last_alert_times[alert_key] >= cooldown:
                logger.error(msg)
                logging.getLogger().error(msg)
                self.last_alert_times[alert_key] = now

        # 1. FTS5 zero hit streak
        if fts5_hits == 0:
            self.fts5_zero_hit_streak += 1
            threshold = getattr(settings, "OBS_ALERT_FTS5_ZERO_HIT_STREAK", 10)
            if self.fts5_zero_hit_streak >= threshold:
                _emit_alert(f"ALERT: FTS5 zero-hit streak >= {threshold}", "fts5_zero_hit")
        else:
            self.fts5_zero_hit_streak = 0
            
        # 2. Latency streak
        lat_thresh = getattr(settings, "OBS_ALERT_LATENCY_THRESHOLD_MS", 3000.0)
        if latency_ms > lat_thresh:
            self.latency_streak += 1
            threshold = getattr(settings, "OBS_ALERT_LATENCY_STREAK", 5)
            if self.latency_streak >= threshold:
                _emit_alert(f"ALERT: Latency streak >= {threshold}", "latency")
        else:
            self.latency_streak = 0
            
        # 3. Error streak
        if error is not None and error != "":
            self.error_streak += 1
            threshold = getattr(settings, "OBS_ALERT_ERROR_STREAK", 5)
            if self.error_streak >= threshold:
                _emit_alert(f"ALERT: Error streak >= {threshold}", "error")
        else:
            self.error_streak = 0

    def log(
        self,
        query: str,
        latency_ms: float,
        v_hits: int,
        fts5_hits: int,
        s_hits: int,
        total_hits: int,
        cache_hit: bool,
        error: Optional[str] = None,
    ) -> None:
        """Record a single query log entry into query_logs table."""
        try:
            QueryLogsTable.__table__.create(bind=self.engine, checkfirst=True)
            with Session(self.engine) as session:
                log_entry = QueryLogsTable(
                    query=query,
                    timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                    latency_ms=float(latency_ms),
                    v_hits=int(v_hits),
                    fts5_hits=int(fts5_hits),
                    s_hits=int(s_hits),
                    total_hits=int(total_hits),
                    cache_hit=bool(cache_hit),
                    error=str(error) if error else None,
                )
                session.add(log_entry)
                session.commit()
            self._check_alerts(float(latency_ms), int(fts5_hits), str(error) if error else None)
        except Exception as e:
            logger.warning(f"ObsLogger log failed (fail-open): {e}")

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent query logs ordered by timestamp DESC."""
        results = []
        try:
            QueryLogsTable.__table__.create(bind=self.engine, checkfirst=True)
            with Session(self.engine) as session:
                rows = (
                    session.query(QueryLogsTable)
                    .order_by(desc(QueryLogsTable.timestamp), desc(QueryLogsTable.id))
                    .limit(limit)
                    .all()
                )
                for row in rows:
                    results.append({
                        "id": row.id,
                        "query": row.query,
                        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                        "latency_ms": row.latency_ms,
                        "v_hits": row.v_hits,
                        "fts5_hits": row.fts5_hits,
                        "s_hits": row.s_hits,
                        "total_hits": row.total_hits,
                        "cache_hit": row.cache_hit,
                        "error": row.error,
                    })
        except Exception as e:
            logger.warning(f"ObsLogger get_recent failed: {e}")
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate statistics using direct SQL without loading table into memory."""
        default_stats = {
            "total_queries": 0,
            "avg_latency_ms": 0.0,
            "v_hit_rate": 0.0,
            "fts5_hit_rate": 0.0,
            "s_hit_rate": 0.0,
            "cache_hit_rate": 0.0,
            "error_rate": 0.0,
            "last_24h_queries": 0,
        }
        try:
            QueryLogsTable.__table__.create(bind=self.engine, checkfirst=True)
            with Session(self.engine) as session:
                # 1. Total queries and aggregate counts
                sql_agg = text("""
                    SELECT 
                        COUNT(*) as total_queries,
                        AVG(latency_ms) as avg_latency_ms,
                        SUM(CASE WHEN v_hits > 0 THEN 1.0 ELSE 0.0 END) as v_hit_count,
                        SUM(CASE WHEN fts5_hits > 0 THEN 1.0 ELSE 0.0 END) as fts5_hit_count,
                        SUM(CASE WHEN s_hits > 0 THEN 1.0 ELSE 0.0 END) as s_hit_count,
                        SUM(CASE WHEN cache_hit = 1 THEN 1.0 ELSE 0.0 END) as cache_hit_count,
                        SUM(CASE WHEN error IS NOT NULL AND error != '' THEN 1.0 ELSE 0.0 END) as error_count
                    FROM query_logs
                """)
                row = session.execute(sql_agg).mappings().first()
                if row and row["total_queries"] and row["total_queries"] > 0:
                    total = int(row["total_queries"])
                    avg_lat = float(row["avg_latency_ms"] or 0.0)
                    v_rate = float(row["v_hit_count"] or 0.0) / total
                    fts5_rate = float(row["fts5_hit_count"] or 0.0) / total
                    s_rate = float(row["s_hit_count"] or 0.0) / total
                    cache_rate = float(row["cache_hit_count"] or 0.0) / total
                    err_rate = float(row["error_count"] or 0.0) / total
                else:
                    total = 0
                    avg_lat = 0.0
                    v_rate = 0.0
                    fts5_rate = 0.0
                    s_rate = 0.0
                    cache_rate = 0.0
                    err_rate = 0.0

                # 2. Last 24h queries
                twenty_four_hours_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
                sql_24h = text("SELECT COUNT(*) as cnt FROM query_logs WHERE timestamp >= :t0")
                row_24h = session.execute(sql_24h, {"t0": twenty_four_hours_ago}).mappings().first()
                last_24h = int(row_24h["cnt"]) if row_24h and row_24h["cnt"] else 0

                return {
                    "total_queries": total,
                    "avg_latency_ms": round(avg_lat, 2),
                    "v_hit_rate": round(v_rate, 4),
                    "fts5_hit_rate": round(fts5_rate, 4),
                    "s_hit_rate": round(s_rate, 4),
                    "cache_hit_rate": round(cache_rate, 4),
                    "error_rate": round(err_rate, 4),
                    "last_24h_queries": last_24h,
                }
        except Exception as e:
            logger.warning(f"ObsLogger get_stats failed: {e}")
            return default_stats

    def increment_api_count(self, provider: str, call_type: str, count: int = 1) -> None:
        """Increment API call counter for a provider and call_type (embed / rerank / ocr)."""
        from backend.database import ApiCallCountsTable
        try:
            ApiCallCountsTable.__table__.create(bind=self.engine, checkfirst=True)
            with Session(self.engine) as session:
                row = (
                    session.query(ApiCallCountsTable)
                    .filter_by(provider=provider, call_type=call_type)
                    .first()
                )
                if row:
                    row.call_count += count
                else:
                    row = ApiCallCountsTable(
                        provider=provider,
                        call_type=call_type,
                        call_count=count,
                        last_reset=datetime.now(timezone.utc).replace(tzinfo=None),
                    )
                    session.add(row)
                session.commit()
        except Exception as e:
            logger.warning(f"ObsLogger increment_api_count failed (fail-open): {e}")

    def get_api_counts(self) -> List[Dict[str, Any]]:
        """Retrieve all API call counts."""
        results = []
        from backend.database import ApiCallCountsTable
        try:
            ApiCallCountsTable.__table__.create(bind=self.engine, checkfirst=True)
            with Session(self.engine) as session:
                rows = session.query(ApiCallCountsTable).all()
                for row in rows:
                    results.append({
                        "provider": row.provider,
                        "call_type": row.call_type,
                        "call_count": row.call_count,
                        "last_reset": row.last_reset.isoformat() if row.last_reset else None,
                    })
        except Exception as e:
            logger.warning(f"ObsLogger get_api_counts failed: {e}")
        return results

    def reset_api_counts(self) -> None:
        """Reset all API call counts to 0 and update last_reset timestamp."""
        from backend.database import ApiCallCountsTable
        try:
            ApiCallCountsTable.__table__.create(bind=self.engine, checkfirst=True)
            with Session(self.engine) as session:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                rows = session.query(ApiCallCountsTable).all()
                for row in rows:
                    row.call_count = 0
                    row.last_reset = now
                session.commit()
        except Exception as e:
            logger.warning(f"ObsLogger reset_api_counts failed: {e}")


def increment_api_count(provider: str, call_type: str, count: int = 1) -> None:
    """Convenience wrapper to increment API call count using default ObsLogger."""
    logger_inst = ObsLogger()
    logger_inst.increment_api_count(provider, call_type, count)

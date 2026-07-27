import html
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse

from backend.config import settings
from backend.core.observability import ObsLogger

obs_logger = ObsLogger()


def check_admin_enabled():
    if not getattr(settings, "ADMIN_ENABLED", True):
        raise HTTPException(status_code=404, detail="Admin interface is disabled")


router = APIRouter(tags=["admin"], dependencies=[Depends(check_admin_enabled)])


@router.get("/stats", response_model=None)
async def get_admin_stats():
    """Return RAG observability stats as plain JSON."""
    return obs_logger.get_stats()


@router.post("/reset-counts", response_model=None)
async def reset_admin_api_counts():
    """Reset all API call counts to zero."""
    obs_logger.reset_api_counts()
    return {"message": "API call counts reset successfully"}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def get_admin_page():
    """Return server-side rendered HTML dashboard for RAG observability."""
    stats = obs_logger.get_stats()
    recent_logs = obs_logger.get_recent(limit=100)
    api_counts = obs_logger.get_api_counts()

    # Calculate formatted percentages
    cache_rate_pct = f"{stats.get('cache_hit_rate', 0.0) * 100:.1f}%"
    v_rate_pct = f"{stats.get('v_hit_rate', 0.0) * 100:.1f}%"
    fts5_rate_pct = f"{stats.get('fts5_hit_rate', 0.0) * 100:.1f}%"
    s_rate_pct = f"{stats.get('s_hit_rate', 0.0) * 100:.1f}%"
    err_rate_pct = f"{stats.get('error_rate', 0.0) * 100:.1f}%"

    # Build rows HTML
    rows_html = []
    for log in recent_logs:
        ts = str(log.get("timestamp", ""))
        raw_q = str(log.get("query", ""))
        q_disp = html.escape(raw_q[:50]) + ("..." if len(raw_q) > 50 else "")
        lat = f"{log.get('latency_ms', 0.0):.1f}"
        vh = str(log.get("v_hits", 0))
        fh = str(log.get("fts5_hits", 0))
        sh = str(log.get("s_hits", 0))
        th = str(log.get("total_hits", 0))
        chit = log.get("cache_hit", False)
        chit_class = "badge-true" if chit else "badge-false"
        chit_disp = "Yes" if chit else "No"
        err = log.get("error")
        err_disp = f'<span class="error">{html.escape(str(err))}</span>' if err else "-"

        rows_html.append(f"""
        <tr>
            <td>{html.escape(ts)}</td>
            <td title="{html.escape(raw_q)}">{q_disp}</td>
            <td>{lat} ms</td>
            <td>V:{vh} / F:{fh} / S:{sh} (总:{th})</td>
            <td class="{chit_class}">{chit_disp}</td>
            <td>{err_disp}</td>
        </tr>
        """)

    table_body = "\n".join(rows_html) if rows_html else '<tr><td colspan="6" style="text-align:center; color:#888;">暂无查询记录</td></tr>'

    # Build API counts HTML
    api_rows_html = []
    for ac in api_counts:
        p_disp = html.escape(str(ac.get("provider", "")))
        c_disp = html.escape(str(ac.get("call_type", "")))
        cnt_disp = str(ac.get("call_count", 0))
        rst_disp = html.escape(str(ac.get("last_reset", "") or "-"))
        api_rows_html.append(f"""
        <tr>
            <td>{p_disp}</td>
            <td>{c_disp}</td>
            <td>{cnt_disp}</td>
            <td>{rst_disp}</td>
        </tr>
        """)
    api_table_body = "\n".join(api_rows_html) if api_rows_html else '<tr><td colspan="4" style="text-align:center; color:#888;">暂无 API 调用记录</td></tr>'

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="30">
    <title>Inquisitive RAG Observability Admin</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #121212; color: #e0e0e0; margin: 0; padding: 20px; }}
        .banner {{ background-color: #5c1616; color: #ff9999; padding: 14px 20px; border-radius: 6px; font-weight: bold; margin-bottom: 25px; border: 1px solid #8c2020; font-size: 15px; display: flex; align-items: center; }}
        .cards {{ display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 25px; }}
        .card {{ background-color: #1e1e1e; border: 1px solid #333; border-radius: 8px; padding: 16px 20px; flex: 1; min-width: 180px; }}
        .card h3 {{ margin: 0 0 10px 0; font-size: 14px; color: #aaaaaa; font-weight: 500; }}
        .card .value {{ font-size: 26px; font-weight: bold; color: #ffffff; }}
        .card .sub {{ font-size: 12px; color: #888888; margin-top: 6px; }}
        .section-title {{ font-size: 18px; margin-bottom: 15px; color: #dddddd; font-weight: 600; }}
        table {{ width: 100%; border-collapse: collapse; background-color: #1e1e1e; border-radius: 8px; overflow: hidden; border: 1px solid #333; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #2d2d2d; font-size: 14px; }}
        th {{ background-color: #252526; color: #cccccc; font-weight: 600; }}
        tr:hover {{ background-color: #282829; }}
        .badge-true {{ color: #4ee44e; font-weight: bold; }}
        .badge-false {{ color: #888888; }}
        .error {{ color: #ff6b6b; font-weight: 500; }}
        .footer {{ margin-top: 25px; text-align: center; font-size: 13px; color: #777777; }}
    </style>
</head>
<body>
    <div class="banner">⚠️ 此页面无需认证，请勿将 API 端口暴露至公网</div>

    <div class="cards">
        <div class="card">
            <h3>总查询数</h3>
            <div class="value">{stats.get('total_queries', 0)}</div>
            <div class="sub">过去 24 小时: {stats.get('last_24h_queries', 0)}</div>
        </div>
        <div class="card">
            <h3>平均延迟</h3>
            <div class="value">{stats.get('avg_latency_ms', 0.0)} <span style="font-size:16px;">ms</span></div>
            <div class="sub">全量历史聚合</div>
        </div>
        <div class="card">
            <h3>缓存命中率</h3>
            <div class="value">{cache_rate_pct}</div>
            <div class="sub">T1 Query Result Cache</div>
        </div>
        <div class="card">
            <h3>通道命中率</h3>
            <div class="value" style="font-size: 18px; line-height: 1.4;">
                V: {v_rate_pct}<br>FTS5: {fts5_rate_pct}<br>S: {s_rate_pct}
            </div>
        </div>
        <div class="card">
            <h3>错误率</h3>
            <div class="value" style="color: {'#ff6b6b' if stats.get('error_rate', 0.0) > 0 else '#ffffff'};">{err_rate_pct}</div>
            <div class="sub">执行异常占比</div>
        </div>
    </div>

    <div class="section-title">最近查询日志 (Top 100)</div>
    <table>
        <thead>
            <tr>
                <th>时间</th>
                <th>查询内容 (前 50 字)</th>
                <th>延迟</th>
                <th>路命中 (V / FTS5 / S / 总)</th>
                <th>Cache Hit</th>
                <th>Error</th>
            </tr>
        </thead>
        <tbody>
            {table_body}
        </tbody>
    </table>

    <div style="margin-top: 30px; display: flex; justify-content: space-between; align-items: center;">
        <div class="section-title" style="margin-bottom: 0;">API 调用计数器</div>
        <form method="post" action="/admin/reset-counts" style="margin: 0;">
            <button type="submit" style="background-color: #5c1616; color: #ff9999; border: 1px solid #8c2020; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-weight: 500;">手动重置计数</button>
        </form>
    </div>
    <table style="margin-top: 15px;">
        <thead>
            <tr>
                <th>提供商 (Provider)</th>
                <th>调用类型 (Call Type)</th>
                <th>累计调用次数 (Call Count)</th>
                <th>上次重置时间 (Last Reset)</th>
            </tr>
        </thead>
        <tbody>
            {api_table_body}
        </tbody>
    </table>

    <div class="footer">页面自动刷新中 (30s) • Inquisitive RAG Observability v1.4</div>
</body>
</html>"""
    return html_content

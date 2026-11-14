import { Hono } from 'hono';
import { getDb } from '../db/index.js';
import { authMiddleware, resolveBearerOrQueryUser, type AuthUser } from '../auth/middleware.js';
import { getOcrClient } from '../ai/ocr-client.js';
import { getSigLIP2 } from '../ai/siglip2.js';

export const adminRouter = new Hono();

function escapeHtml(raw: unknown): string {
  return String(raw ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// GET /admin/stats
adminRouter.get('/stats', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  if (!user.is_superuser) {
    return c.json({ detail: 'Superuser privileges required' }, 403);
  }

  const db = getDb();
  const agg = db
    .prepare(`
      SELECT 
        COUNT(*) as total_queries,
        AVG(latency_ms) as avg_latency_ms,
        SUM(CASE WHEN v_hits > 0 THEN 1.0 ELSE 0.0 END) as v_hit_count,
        SUM(CASE WHEN fts5_hits > 0 THEN 1.0 ELSE 0.0 END) as fts5_hit_count,
        SUM(CASE WHEN s_hits > 0 THEN 1.0 ELSE 0.0 END) as s_hit_count,
        SUM(CASE WHEN cache_hit = 1 THEN 1.0 ELSE 0.0 END) as cache_hit_count,
        SUM(CASE WHEN error IS NOT NULL AND error != '' THEN 1.0 ELSE 0.0 END) as error_count
      FROM query_logs
    `)
    .get() as {
    total_queries: number;
    avg_latency_ms: number | null;
    v_hit_count: number | null;
    fts5_hit_count: number | null;
    s_hit_count: number | null;
    cache_hit_count: number | null;
    error_count: number | null;
  } | undefined;

  const total = agg?.total_queries || 0;
  const avgLat = Number(agg?.avg_latency_ms || 0);
  const vRate = total > 0 ? Number(agg?.v_hit_count || 0) / total : 0;
  const fts5Rate = total > 0 ? Number(agg?.fts5_hit_count || 0) / total : 0;
  const sRate = total > 0 ? Number(agg?.s_hit_count || 0) / total : 0;
  const cacheRate = total > 0 ? Number(agg?.cache_hit_count || 0) / total : 0;
  const errRate = total > 0 ? Number(agg?.error_count || 0) / total : 0;

  const last24hRow = db
    .prepare("SELECT COUNT(*) as cnt FROM query_logs WHERE timestamp >= datetime('now', '-1 day')")
    .get() as { cnt: number } | undefined;
  const last24h = last24hRow?.cnt || 0;

  const resourceCountsRaw = db
    .prepare('SELECT type, COUNT(*) as c FROM resources GROUP BY type')
    .all() as Array<{ type: string; c: number }>;
  const byType: Record<string, number> = { file: 0, note: 0, link: 0 };
  for (const r of resourceCountsRaw) {
    byType[r.type] = Number(r.c || 0);
  }

  const chunkCount = (db.prepare('SELECT COUNT(*) as c FROM chunks').get() as { c: number }).c;
  const assetCount = (db.prepare('SELECT COUNT(*) as c FROM assets').get() as { c: number }).c;
  const tagCount = (db.prepare('SELECT COUNT(*) as c FROM tags').get() as { c: number }).c;
  const wikiCount = (db.prepare('SELECT COUNT(*) as c FROM wiki_pages').get() as { c: number }).c;
  const userCount = (db.prepare('SELECT COUNT(*) as c FROM users').get() as { c: number }).c;
  const apiCounts = db.prepare('SELECT provider, call_type, call_count, last_reset FROM api_call_counts').all();
  const jobCountsRaw = db
    .prepare('SELECT status, COUNT(*) as c FROM ingestion_jobs GROUP BY status')
    .all() as Array<{ status: string; c: number }>;
  const jobCounts: Record<string, number> = { pending: 0, running: 0, finished: 0, failed: 0, cancelled: 0 };
  for (const r of jobCountsRaw) {
    jobCounts[r.status] = Number(r.c || 0);
  }

  const ocrHealth = await getOcrClient().health();
  const siglip = getSigLIP2();
  let siglipVisionReady = siglip.isVisionSupported();
  if (!siglipVisionReady) {
    try {
      await siglip.init();
      siglipVisionReady = siglip.isVisionSupported();
    } catch {
      siglipVisionReady = false;
    }
  }

  return c.json({
    total_queries: total,
    avg_latency_ms: Math.round(avgLat * 100) / 100,
    v_hit_rate: Math.round(vRate * 10000) / 10000,
    fts5_hit_rate: Math.round(fts5Rate * 10000) / 10000,
    s_hit_rate: Math.round(sRate * 10000) / 10000,
    cache_hit_rate: Math.round(cacheRate * 10000) / 10000,
    error_rate: Math.round(errRate * 10000) / 10000,
    last_24h_queries: last24h,
    counts: {
      users: userCount,
      resources: byType['file']! + byType['note']! + byType['link']!,
      files: byType['file'],
      notes: byType['note'],
      links: byType['link'],
      chunks: chunkCount,
      assets: assetCount,
      tags: tagCount,
      wiki_pages: wikiCount,
      queries: total,
    },
    jobs: jobCounts,
    runtime: {
      ocr: ocrHealth,
      siglip2_vision: siglipVisionReady,
    },
    api_calls: apiCounts,
  });
});

// GET /admin/logs?limit=50
adminRouter.get('/logs', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  if (!user.is_superuser) {
    return c.json({ detail: 'Superuser privileges required' }, 403);
  }

  const rawLimit = parseInt(c.req.query('limit') || '50', 10) || 50;
  const limit = Math.max(1, Math.min(rawLimit, 200));
  const db = getDb();
  const logs = db
    .prepare('SELECT * FROM query_logs ORDER BY id DESC LIMIT ?')
    .all(limit) as Array<{
    id: number;
    query: string;
    timestamp: string;
    latency_ms: number;
    v_hits: number;
    fts5_hits: number;
    s_hits: number;
    total_hits: number;
    cache_hit: number;
    error: string | null;
  }>;

  return c.json({ logs });
});

// POST /admin/reset-counts
adminRouter.post('/reset-counts', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  if (!user.is_superuser) {
    return c.json({ detail: 'Superuser privileges required' }, 403);
  }

  const db = getDb();
  db.prepare('UPDATE api_call_counts SET call_count = 0, last_reset = CURRENT_TIMESTAMP').run();
  return c.json({ message: 'API call counts reset successfully' });
});

// GET /admin (Protected SSR Dashboard HTML with XSS escaping)
adminRouter.get('/', async (c) => {
  const user = await resolveBearerOrQueryUser(c);
  if (!user) {
    return c.json({ detail: 'Unauthorized' }, 401);
  }
  if (!user.is_superuser) {
    return c.json({ detail: 'Superuser privileges required' }, 403);
  }

  const db = getDb();
  const logs = db
    .prepare('SELECT * FROM query_logs ORDER BY id DESC LIMIT 50')
    .all() as Array<{
    id: number;
    query: string;
    timestamp: string;
    latency_ms: number;
    v_hits: number;
    fts5_hits: number;
    s_hits: number;
    total_hits: number;
    cache_hit: number;
    error: string | null;
  }>;

  const apiCounts = db
    .prepare('SELECT provider, call_type, call_count, last_reset FROM api_call_counts ORDER BY provider, call_type')
    .all() as Array<{ provider: string; call_type: string; call_count: number; last_reset: string | null }>;

  const rows = logs
    .map(
      (l) => `
    <tr>
      <td>${escapeHtml(l.timestamp)}</td>
      <td title="${escapeHtml(l.query)}">${escapeHtml(l.query.slice(0, 50))}</td>
      <td>${Number(l.latency_ms || 0).toFixed(1)} ms</td>
      <td>V:${Number(l.v_hits || 0)} / F:${Number(l.fts5_hits || 0)} / S:${Number(l.s_hits || 0)} (总:${Number(l.total_hits || 0)})</td>
      <td>${l.cache_hit ? 'Yes' : 'No'}</td>
      <td>${l.error ? escapeHtml(l.error) : '-'}</td>
    </tr>
  `
    )
    .join('');

  const apiRows = apiCounts
    .map(
      (a) => `
    <tr>
      <td>${escapeHtml(a.provider)}</td>
      <td>${escapeHtml(a.call_type)}</td>
      <td>${Number(a.call_count || 0)}</td>
      <td>${a.last_reset ? escapeHtml(a.last_reset) : '-'}</td>
    </tr>
  `
    )
    .join('');

  return c.html(`<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>wenjv Observability</title>
  <style>
    body { font-family: sans-serif; background: #121212; color: #eee; padding: 20px; }
    table { width: 100%; border-collapse: collapse; margin-top: 14px; margin-bottom: 24px; }
    th, td { border: 1px solid #333; padding: 8px 12px; text-align: left; }
    th { background: #222; }
  </style>
</head>
<body>
  <h1>wenjv Observability Dashboard</h1>
  <h2>API 调用统计</h2>
  <table>
    <thead>
      <tr><th>Provider</th><th>类型</th><th>次数</th><th>上次清零</th></tr>
    </thead>
    <tbody>${apiRows || '<tr><td colspan="4">暂无 API 调用记录</td></tr>'}</tbody>
  </table>
  <h2>最近检索日志</h2>
  <table>
    <thead>
      <tr><th>时间</th><th>查询</th><th>延迟</th><th>通道命中</th><th>Cache Hit</th><th>Error</th></tr>
    </thead>
    <tbody>${rows || '<tr><td colspan="6">暂无查询日志</td></tr>'}</tbody>
  </table>
</body>
</html>`);
});

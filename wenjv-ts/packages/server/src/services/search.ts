import crypto from 'node:crypto';
import { getDb } from '../db/index.js';
import { matchFts5 } from '../db/fts5.js';
import { getChunksByIds, type ChunkResourceType } from '../db/chunks.js';
import { getTextStore } from '../vector/text-store.js';
import { getEmbedder } from '../ai/bge-m3.js';
import { getReranker } from '../ai/reranker.js';
import { getEntityRefsByTags } from './tags.js';
import { config } from '../config.js';

export interface SearchHit {
  id: string;
  page_content: string;
  score: number;
  metadata: {
    id?: string | undefined;
    title?: string | undefined;
    filename?: string | undefined;
    source?: string | undefined;
    page?: string | undefined;
    source_type?: string | undefined;
    resource_id?: string | undefined;
    header_path?: string | undefined;
    chunk_order?: number | undefined;
    image_path?: string | undefined;
    image_url?: string | undefined;
    has_image?: boolean | undefined;
    tag_matched?: boolean | undefined;
  };
}

export interface SearchOptions {
  prompt: string;
  userId?: number | undefined;
  userEmail?: string | undefined;
  includeSources?: string[] | undefined;
  excludeSources?: string[] | undefined;
  windowSize?: number | undefined;
  sourceType?: ChunkResourceType | undefined;
  tags?: string[] | undefined;
}

function getUserContentWatermark(db: ReturnType<typeof getDb>, userId?: number): string {
  if (!userId) return 'anon';
  try {
    const rRow = db
      .prepare('SELECT COUNT(*) as cnt, MAX(updated_at) as ts FROM resources WHERE user_id = ?')
      .get(userId) as { cnt: number; ts: string | null } | undefined;
    const wRow = db
      .prepare('SELECT COUNT(*) as cnt, MAX(updated_at) as ts FROM wiki_pages WHERE user_id = ?')
      .get(userId) as { cnt: number; ts: string | null } | undefined;
    return `${rRow?.cnt || 0}:${rRow?.ts || ''}|${wRow?.cnt || 0}:${wRow?.ts || ''}`;
  } catch {
    return '0';
  }
}

export function computeQueryHash(options: SearchOptions, contentWatermark = ''): string {
  const normPrompt = (options.prompt || '').toLowerCase().trim().replace(/\s+/g, ' ');
  const data = {
    p: normPrompt,
    inc: options.includeSources ? [...options.includeSources].sort() : null,
    exc: options.excludeSources ? [...options.excludeSources].sort() : null,
    st: options.sourceType || null,
    w: options.windowSize || 5,
    tg: options.tags ? [...options.tags].sort() : null,
    wm: contentWatermark,
  };
  return crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex').slice(0, 32);
}

export async function searchDocuments(options: SearchOptions): Promise<SearchHit[]> {
  const startTime = Date.now();
  const db = getDb();
  const windowSize = options.windowSize || 5;
  const prompt = options.prompt || '';
  const userId = options.userId;

  // 1. Check query cache (content-watermark aware)
  const watermark = getUserContentWatermark(db, userId);
  const queryHash = computeQueryHash(options, watermark);
  if (userId) {
    const cachedRow = db
      .prepare('SELECT result_json, expires_at FROM query_result_cache WHERE query_hash = ? AND user_id = ?')
      .get(queryHash, userId) as { result_json: string; expires_at: string } | undefined;

    if (cachedRow && cachedRow.result_json) {
      const expDate = new Date(cachedRow.expires_at).getTime();
      if (Date.now() < expDate) {
        try {
          const hits = JSON.parse(cachedRow.result_json) as SearchHit[];
          const slicedHits = hits.slice(0, windowSize);
          const latencyMs = Date.now() - startTime;
          try {
            db.prepare(`
              INSERT INTO query_logs("query", latency_ms, v_hits, fts5_hits, s_hits, total_hits, cache_hit, error)
              VALUES (?, ?, 0, 0, 0, ?, 1, NULL)
            `).run(prompt, latencyMs, slicedHits.length);
          } catch {
            // ignore query log write errors
          }
          return slicedHits;
        } catch {
          // ignore corrupted cache entry
        }
      }
    }
  }

  // Optional relational tag pre-filter across resources & wiki pages
  const hasTagFilter = Boolean(options.tags && options.tags.length > 0 && userId);
  const tagEntityRefs =
    hasTagFilter && userId ? getEntityRefsByTags(db, userId, options.tags!) : null;
  if (hasTagFilter && (!tagEntityRefs || tagEntityRefs.length === 0)) {
    return [];
  }

  // 2. FTS5 Search (JOINed to authoritative chunks table)
  const ftsRows = matchFts5(db, prompt, {
    userId,
    resourceType: options.sourceType,
    includeSources: options.includeSources,
    entityRefs: tagEntityRefs,
    limit: 50,
  });

  // 3. Slim Dense Vector Search -> batch hydrate from SQLite `chunks`
  const embedder = getEmbedder();
  const queryVec = await embedder.embedQuery(prompt);
  const textStore = getTextStore();
  const vectorRows = await textStore.search(queryVec, {
    userId,
    resourceType: options.sourceType,
    entityRefs: tagEntityRefs,
    limit: 50,
  });

  const vectorChunkMap = getChunksByIds(
    db,
    vectorRows.map((v) => v.id),
    userId
  );

  // 4. Reciprocal Rank Fusion (RRF)
  const k = 60;
  const rrfScores = new Map<string, { score: number; content: string; meta: SearchHit['metadata'] }>();

  ftsRows.forEach((row, rank) => {
    const id = row.chunk_id;
    const rrf = 1.0 / (k + (rank + 1));
    const curr = rrfScores.get(id);
    if (curr) {
      curr.score += rrf;
    } else {
      rrfScores.set(id, {
        score: rrf,
        content: row.content,
        meta: {
          id,
          title: row.title,
          filename: row.source,
          source: row.source,
          page: String(row.page_number),
          source_type: row.resource_type,
          resource_id: String(row.entity_id),
          header_path: row.header_path,
          chunk_order: row.chunk_order,
          tag_matched: hasTagFilter || undefined,
        },
      });
    }
  });

  vectorRows.forEach((vRow, rank) => {
    const chunk = vectorChunkMap.get(vRow.id);
    if (!chunk) return;
    if (options.includeSources && options.includeSources.length > 0) {
      const incSet = new Set(options.includeSources.filter(Boolean));
      if (!incSet.has(chunk.source) && !incSet.has(chunk.title)) return;
    }

    const rrf = 1.0 / (k + (rank + 1));
    const curr = rrfScores.get(chunk.id);
    if (curr) {
      curr.score += rrf;
    } else {
      rrfScores.set(chunk.id, {
        score: rrf,
        content: chunk.content,
        meta: {
          id: chunk.id,
          title: chunk.title,
          filename: chunk.source,
          source: chunk.source,
          page: String(chunk.page_number),
          source_type: chunk.resource_type,
          resource_id: String(chunk.entity_id),
          header_path: chunk.header_path,
          chunk_order: chunk.chunk_order,
          tag_matched: hasTagFilter || undefined,
        },
      });
    }
  });

  let fusedHits: SearchHit[] = Array.from(rrfScores.entries()).map(([id, val]) => ({
    id,
    page_content: val.content,
    score: val.score,
    metadata: val.meta,
  }));

  if (options.excludeSources && options.excludeSources.length > 0) {
    const exc = new Set(options.excludeSources.map((s) => s.toLowerCase()));
    fusedHits = fusedHits.filter((h) => {
      const src = (h.metadata.source || h.metadata.filename || '').toLowerCase();
      return !exc.has(src);
    });
  }

  fusedHits.sort((a, b) => b.score - a.score);

  // 5. Reranking (if enabled)
  if (config.RERANK_ENABLED && fusedHits.length > 0) {
    const reranker = getReranker();
    const topCandidates = fusedHits.slice(0, 30);
    const candidateTexts = topCandidates.map((c) => c.page_content);
    try {
      const rerankRes = await reranker.rerank(prompt, candidateTexts);
      const rerankedList: SearchHit[] = [];
      for (const item of rerankRes) {
        const originalHit = topCandidates[item.index];
        if (originalHit) {
          rerankedList.push({
            ...originalHit,
            score: item.relevanceScore,
          });
        }
      }
      fusedHits = rerankedList;
    } catch (err) {
      // fail-open on reranker error: keep RRF order
      console.warn('[Search] Reranker failed, falling back to RRF order:', err instanceof Error ? err.message : String(err));
    }
  }

  const finalHits = fusedHits.slice(0, windowSize);
  const latencyMs = Date.now() - startTime;

  try {
    db.prepare(`
      INSERT INTO query_logs("query", latency_ms, v_hits, fts5_hits, s_hits, total_hits, cache_hit, error)
      VALUES (?, ?, ?, ?, 0, ?, 0, NULL)
    `).run(prompt, latencyMs, vectorRows.length, ftsRows.length, finalHits.length);
  } catch (err) {
    console.warn('[Search] Query log insert failed:', err instanceof Error ? err.message : String(err));
  }

  if (userId && finalHits.length > 0) {
    try {
      const nowIso = new Date().toISOString();
      const expiresAt = new Date(Date.now() + 300 * 1000).toISOString();
      db.prepare('DELETE FROM query_result_cache WHERE expires_at <= ?').run(nowIso);
      db.prepare(`
        INSERT OR REPLACE INTO query_result_cache(query_hash, user_id, result_json, expires_at)
        VALUES (?, ?, ?, ?)
      `).run(queryHash, userId, JSON.stringify(finalHits), expiresAt);
    } catch (err) {
      console.warn('[Search] Cache write failed:', err instanceof Error ? err.message : String(err));
    }
  }

  return finalHits;
}

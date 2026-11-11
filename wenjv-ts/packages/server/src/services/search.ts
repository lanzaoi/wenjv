import crypto from 'node:crypto';
import { getDb } from '../db/index.js';
import { matchFts5 } from '../db/fts5.js';
import { getDocumentStore } from '../vector/document-store.js';
import { getEmbedder } from '../ai/bge-m3.js';
import { getReranker } from '../ai/reranker.js';
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
    belongs_to?: string | undefined;
    link_id?: string | undefined;
    chunk_group?: string | undefined;
    chunk_order?: number | undefined;
    image_path?: string | undefined;
    image_url?: string | undefined;
    has_image?: boolean | undefined;
    tag_matched?: boolean | undefined;
    tag_fallback?: boolean | undefined;
  };
}

export interface SearchOptions {
  prompt: string;
  userId?: number | undefined;
  userEmail?: string | undefined;
  includeSources?: string[] | undefined;
  excludeSources?: string[] | undefined;
  windowSize?: number | undefined;
  sourceType?: string | undefined;
  tags?: string[] | undefined;
  lostInTheMiddle?: boolean | undefined;
}

export function computeQueryHash(options: SearchOptions): string {
  const normPrompt = (options.prompt || '').toLowerCase().trim().replace(/\s+/g, ' ');
  const data = {
    p: normPrompt,
    inc: options.includeSources?.sort() || null,
    exc: options.excludeSources?.sort() || null,
    st: options.sourceType || null,
    w: options.windowSize || 5,
    tg: options.tags?.sort() || null,
  };
  return crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex').slice(0, 32);
}

export async function searchDocuments(options: SearchOptions): Promise<SearchHit[]> {
  const startTime = Date.now();
  const db = getDb();
  const windowSize = options.windowSize || 5;
  const prompt = options.prompt || '';
  const userId = options.userId;

  // 1. Check query cache
  const queryHash = computeQueryHash(options);
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
            // ignore
          }
          return slicedHits;
        } catch {
          // ignore corrupted cache
        }
      }
    }
  }

  // 2. FTS5 Search
  const ftsRows = matchFts5(db, prompt, {
    userId,
    sourceType: options.sourceType,
    includeSources: options.includeSources,
    limit: 50,
  });

  // 3. Dense Vector Search
  const embedder = getEmbedder();
  const queryVec = await embedder.embedQuery(prompt);
  const docStore = getDocumentStore();
  const vectorRows = await docStore.search(queryVec, {
    userId,
    sourceType: options.sourceType,
    includeSources: options.includeSources,
    limit: 50,
  });

  // 4. Reciprocal Rank Fusion (RRF)
  const k = 60;
  const rrfScores = new Map<string, { score: number; content: string; meta: SearchHit['metadata'] }>();

  // Add FTS ranks
  ftsRows.forEach((row, rank) => {
    const id = row.chunk_id;
    const rrf = 1.0 / (k + (rank + 1));
    const curr = rrfScores.get(id);
    if (curr) {
      curr.score += rrf;
    } else {
      rrfScores.set(id, {
        score: rrf,
        content: row.page_content,
        meta: {
          id,
          title: row.title,
          filename: row.filename,
          source: row.belongs_to || row.filename,
          source_type: row.source_type || undefined,
          resource_id: row.resource_id || undefined,
          belongs_to: row.belongs_to || undefined,
          link_id: row.link_id || undefined,
        },
      });
    }
  });

  // Add Vector ranks
  vectorRows.forEach((row, rank) => {
    const id = row.id;
    const rrf = 1.0 / (k + (rank + 1));
    const curr = rrfScores.get(id);
    if (curr) {
      curr.score += rrf;
    } else {
      rrfScores.set(id, {
        score: rrf,
        content: row.page_content,
        meta: {
          id,
          title: row.title,
          filename: row.filename,
          source: row.source || row.filename,
          page: row.page,
          source_type: row.source_type,
          resource_id: row.resource_id,
          belongs_to: row.belongs_to,
          link_id: row.link_id,
          chunk_group: row.chunk_group,
          chunk_order: row.chunk_order,
          image_path: row.image_path,
          has_image: Boolean(row.image_path),
          image_url: row.image_path ? `/api/documents/assets/image?path=${encodeURIComponent(row.image_path)}` : undefined,
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

  // Filter excluded sources if specified
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
    } catch {
      // fail-open on reranker error: keep RRF order
    }
  }

  const finalHits = fusedHits.slice(0, windowSize);
  const latencyMs = Date.now() - startTime;

  // Log query
  try {
    db.prepare(`
      INSERT INTO query_logs("query", latency_ms, v_hits, fts5_hits, s_hits, total_hits, cache_hit, error)
      VALUES (?, ?, ?, ?, 0, ?, 0, NULL)
    `).run(prompt, latencyMs, vectorRows.length, ftsRows.length, finalHits.length);
  } catch {
    // ignore
  }

  // Save query cache
  if (userId && finalHits.length > 0) {
    try {
      const expiresAt = new Date(Date.now() + 300 * 1000).toISOString();
      db.prepare(`
        INSERT OR REPLACE INTO query_result_cache(query_hash, user_id, result_json, expires_at)
        VALUES (?, ?, ?, ?)
      `).run(queryHash, userId, JSON.stringify(finalHits), expiresAt);
    } catch {
      // ignore
    }
  }

  return finalHits;
}

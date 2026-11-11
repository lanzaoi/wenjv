import Database from 'better-sqlite3';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { sanitizeFtsQuery, matchFts5, insertFts5Batch, createFts5Table } from '../../../packages/server/src/db/fts5.js';

export async function runSqliteSpike(): Promise<void> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sqlite-spike-'));
  const dbPath = path.join(tmpDir, 'test.db');
  const db = new Database(dbPath);

  db.pragma('journal_mode = WAL');
  db.pragma('synchronous = NORMAL');
  db.pragma('busy_timeout = 5000');
  db.pragma('foreign_keys = ON');

  createFts5Table(db);

  const sampleRows = [
    { chunk_id: 'c1', title: '人工智能概述', filename: 'ai.md', page_content: '人工智能是未来科技的核心驱动力，涵盖深度学习与知识图谱。', user_id: '1', belongs_to: 'ai.md', source_type: 'file' },
    { chunk_id: 'c2', title: 'SQLite FTS5指南', filename: 'sqlite.txt', page_content: 'SQLite全文索引使用trigram分词器支持多语言搜索和子串查询。', user_id: '1', belongs_to: 'sqlite.txt', source_type: 'file' },
    { chunk_id: 'c3', title: 'TypeScript Best Practices', filename: 'ts.md', page_content: 'Writing type-safe enterprise applications with Node.js and TypeScript 5.', user_id: '1', belongs_to: 'ts.md', source_type: 'file' },
    { chunk_id: 'c4', title: '混合搜索架构', filename: 'hybrid.md', page_content: '通过RRF算法融合BM25全文检索与密集向量相似度评分。', user_id: '1', belongs_to: 'hybrid.md', source_type: 'file' },
  ];

  insertFts5Batch(db, sampleRows);

  const testQueries = [
    { query: '人工', expectedChunkId: 'c1' }, // 2-char Chinese (triggers LIKE fallback)
    { query: '人工智能', expectedChunkId: 'c1' }, // 4-char Chinese (FTS5 trigram)
    { query: 'TypeScript', expectedChunkId: 'c3' }, // English
    { query: 'Node.js 检索', expectedChunkId: 'c3' }, // mixed
    { query: 'SQLite && FTS5!!', expectedChunkId: 'c2' }, // special chars
    { query: 'RRF算法', expectedChunkId: 'c4' }, // mixed CJK + English
  ];

  for (const t of testQueries) {
    const hits = matchFts5(db, t.query, { limit: 5 });
    if (hits.length === 0) {
      throw new Error(`FTS query failed to match any rows: "${t.query}"`);
    }
    const found = hits.some((h: { chunk_id: string }) => h.chunk_id === t.expectedChunkId);
    if (!found) {
      throw new Error(`FTS query "${t.query}" did not find expected chunk "${t.expectedChunkId}"`);
    }
  }

  db.close();
  fs.rmSync(tmpDir, { recursive: true, force: true });
}

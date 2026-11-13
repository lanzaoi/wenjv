import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { getDb, closeDb } from '../../../packages/server/src/db/index.js';
import { replaceEntityChunks } from '../../../packages/server/src/db/chunks.js';
import { matchFts5 } from '../../../packages/server/src/db/fts5.js';

export async function runSqliteSpike(): Promise<void> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sqlite-spike-'));
  const dbPath = path.join(tmpDir, 'test.db');
  const db = getDb(dbPath);

  db.prepare(`
    INSERT INTO users(id, email, username, hashed_password)
    VALUES (1, 'spike@example.com', 'spike', 'hash')
  `).run();

  replaceEntityChunks(db, 1, 'resource', 100, [
    {
      id: 'c1',
      user_id: 1,
      entity_type: 'resource',
      entity_id: 100,
      resource_type: 'file',
      chunk_order: 0,
      title: '人工智能概述',
      source: 'ai.md',
      content: '人工智能是未来科技的核心驱动力，涵盖深度学习与知识图谱。',
    },
    {
      id: 'c2',
      user_id: 1,
      entity_type: 'resource',
      entity_id: 100,
      resource_type: 'file',
      chunk_order: 1,
      title: 'SQLite FTS5指南',
      source: 'sqlite.txt',
      content: 'SQLite全文索引使用trigram分词器支持多语言搜索和子串查询。',
    },
    {
      id: 'c3',
      user_id: 1,
      entity_type: 'resource',
      entity_id: 100,
      resource_type: 'file',
      chunk_order: 2,
      title: 'TypeScript Best Practices',
      source: 'ts.md',
      content: 'Writing type-safe enterprise applications with Node.js and TypeScript 5.',
    },
    {
      id: 'c4',
      user_id: 1,
      entity_type: 'resource',
      entity_id: 100,
      resource_type: 'file',
      chunk_order: 3,
      title: '混合搜索架构',
      source: 'hybrid.md',
      content: '通过RRF算法融合BM25全文检索与密集向量相似度评分。',
    },
  ]);

  const testQueries = [
    { query: '人工', expectedChunkId: 'c1' },
    { query: '人工智能', expectedChunkId: 'c1' },
    { query: 'TypeScript', expectedChunkId: 'c3' },
    { query: 'Node.js 检索', expectedChunkId: 'c3' },
    { query: 'SQLite && FTS5!!', expectedChunkId: 'c2' },
    { query: 'RRF算法', expectedChunkId: 'c4' },
  ];

  for (const t of testQueries) {
    const hits = matchFts5(db, t.query, { userId: 1, limit: 5 });
    if (hits.length === 0) {
      throw new Error(`FTS query failed to match any rows: "${t.query}"`);
    }
    const found = hits.some((h) => h.chunk_id === t.expectedChunkId);
    if (!found) {
      throw new Error(`FTS query "${t.query}" did not find expected chunk "${t.expectedChunkId}"`);
    }
  }

  closeDb();
  fs.rmSync(tmpDir, { recursive: true, force: true });
}

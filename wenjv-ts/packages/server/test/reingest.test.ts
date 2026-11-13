import fs from 'node:fs';
import path from 'node:path';
import Database from 'better-sqlite3';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { setupTestEnv, type TestEnv } from './helper.js';
import { getDb } from '../src/db/index.js';
import { hashPassword } from '../src/auth/password.js';
import { importV1SnapshotIntoV2, rebuildAllIndexes } from '../src/services/reingest.js';
import { getEntityTags } from '../src/services/tags.js';

describe('Schema v2 Re-ingestion & v1 Snapshot Import (S11)', () => {
  let env: TestEnv;

  beforeEach(() => {
    env = setupTestEnv();
  });

  afterEach(() => {
    env.cleanup();
  });

  it('imports read-only v1 snapshot into Schema v2 resources, relational tags, wiki, and rebuilds FTS5 + vector index', async () => {
    const legacyDir = path.join(env.tmpDir, 'legacy-v1');
    const legacyUploads = path.join(legacyDir, 'uploads');
    fs.mkdirSync(legacyUploads, { recursive: true });

    const mdPath = path.join(legacyUploads, 'guide-v1.md');
    fs.writeFileSync(mdPath, '# 迁移手册\n\nSchema v2 将多张孤立资源表合并为 resources。', 'utf8');
    const notePath = path.join(legacyUploads, 'note-v1.md');
    fs.writeFileSync(notePath, '# 随手记\n\n关系型 tags + entity_tags 支持 O(1) 重命名。', 'utf8');

    const v1DbPath = path.join(legacyDir, 'wenjv.db');
    const v1 = new Database(v1DbPath);
    v1.exec(`
      CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email VARCHAR NOT NULL UNIQUE,
        username VARCHAR,
        hashed_password VARCHAR NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT 1,
        is_superuser BOOLEAN NOT NULL DEFAULT 0,
        is_verified BOOLEAN NOT NULL DEFAULT 0
      );
      CREATE TABLE file_uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename VARCHAR NOT NULL,
        original_filename VARCHAR,
        file_path VARCHAR NOT NULL,
        file_url VARCHAR,
        status VARCHAR DEFAULT 'finished',
        content_type VARCHAR,
        error_message VARCHAR,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER NOT NULL,
        tags TEXT DEFAULT '[]'
      );
      CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url VARCHAR,
        title VARCHAR,
        filename VARCHAR NOT NULL,
        file_path VARCHAR NOT NULL,
        status VARCHAR DEFAULT 'finished',
        error_message VARCHAR,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER NOT NULL,
        tags TEXT DEFAULT '[]'
      );
      CREATE TABLE wiki_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        parent_id INTEGER,
        path VARCHAR NOT NULL,
        slug VARCHAR NOT NULL,
        title VARCHAR NOT NULL,
        content VARCHAR NOT NULL,
        summary VARCHAR DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        icon VARCHAR DEFAULT '',
        tags TEXT DEFAULT '[]',
        index_status VARCHAR DEFAULT 'indexed',
        revision_count INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      );
    `);

    const pwHash = await hashPassword('Password123!');
    v1.prepare('INSERT INTO users (id, email, username, hashed_password) VALUES (?, ?, ?, ?)').run(
      1,
      'legacy@example.com',
      'legacy',
      pwHash
    );
    v1.prepare(
      'INSERT INTO file_uploads (filename, original_filename, file_path, content_type, user_id, tags) VALUES (?, ?, ?, ?, ?, ?)'
    ).run('guide-v1.md', '迁移手册.md', mdPath, 'text/markdown', 1, JSON.stringify(['架构', '迁移']));
    v1.prepare(
      'INSERT INTO file_uploads (filename, original_filename, file_path, content_type, user_id, tags) VALUES (?, ?, ?, ?, ?, ?)'
    ).run('ghost-missing.pdf', '缺失文件.pdf', '/nonexistent/ghost-missing.pdf', 'application/pdf', 1, JSON.stringify(['无效']));
    v1.prepare(
      'INSERT INTO notes (title, filename, file_path, user_id, tags) VALUES (?, ?, ?, ?, ?)'
    ).run('标签说明', 'note-v1.md', notePath, 1, JSON.stringify(['架构']));
    v1.prepare(
      'INSERT INTO wiki_pages (id, user_id, parent_id, path, slug, title, content, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
    ).run(5, 1, null, '/', 'v2-wiki', 'Schema v2 知识页', '# Wiki\n统一 chunks_fts 外置内容触发器验证。', JSON.stringify(['WikiTag']));
    v1.close();

    const imported = importV1SnapshotIntoV2({
      v1DbPath,
      sourceUploadsDir: legacyUploads,
      copyFiles: true,
      skipMissing: true,
    });
    expect(imported.users).toBe(1);
    expect(imported.files).toBe(1);
    expect(imported.notes).toBe(1);
    expect(imported.wikiPages).toBe(1);
    expect(imported.copiedFiles).toBe(2);
    expect(imported.missingFiles).toBe(1);

    const rebuilt = await rebuildAllIndexes();
    expect(rebuilt.enqueuedResources).toBe(2);
    expect(rebuilt.enqueuedWikiPages).toBe(1);
    expect(rebuilt.succeeded).toBe(3);
    expect(rebuilt.failed).toBe(0);

    const db = getDb();
    const resourcesCount = (db.prepare('SELECT COUNT(*) as c FROM resources').get() as { c: number }).c;
    expect(resourcesCount).toBe(2);

    const chunksCount = (db.prepare('SELECT COUNT(*) as c FROM chunks').get() as { c: number }).c;
    expect(chunksCount).toBe(3);

    const ftsMatchCount = (
      db.prepare("SELECT COUNT(*) as c FROM chunks_fts WHERE chunks_fts MATCH '外置内容触发器'").get() as { c: number }
    ).c;
    expect(ftsMatchCount).toBe(1);

    expect(getEntityTags(db, 1, 'resource', 1)).toEqual(['架构', '迁移']);
    expect(getEntityTags(db, 1, 'wiki', 5)).toEqual(['WikiTag']);

    // Idempotent second rebuild also succeeds cleanly
    const secondRebuild = await rebuildAllIndexes();
    expect(secondRebuild.succeeded).toBe(3);
    expect((db.prepare('SELECT COUNT(*) as c FROM chunks').get() as { c: number }).c).toBe(3);
  });
});

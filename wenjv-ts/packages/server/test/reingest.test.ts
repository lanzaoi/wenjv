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

  it('detects and imports legacy v1 data via HTTP routes safely scoped to the authenticated user', async () => {
    // 1. Register current Option-2 user and create an existing Wiki page #1 (must NOT be overwritten!)
    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'active@example.com', password: 'Password123!' }),
    });
    const loginRes = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'active@example.com', password: 'Password123!' }),
    });
    const { access_token: token } = (await loginRes.json()) as { access_token: string };

    const existingWiki = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '现有新页面', content: '不能被旧库 ID=1 覆盖' }),
    });
    expect(existingWiki.status).toBe(201);

    // 2. Build isolated legacy v1 source directory with ID=1 & parent->child wiki hierarchy
    const legacyDir = path.join(env.tmpDir, 'mock-legacy-home');
    const legacyUploads = path.join(legacyDir, 'uploads');
    fs.mkdirSync(legacyUploads, { recursive: true });
    const fPath = path.join(legacyUploads, 'handbook.md');
    fs.writeFileSync(fPath, '# 操作指南\n\n批量导入内容验证。', 'utf8');

    const v1DbPath = path.join(legacyDir, 'wenjv.db');
    const v1 = new Database(v1DbPath);
    v1.exec(`
      CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR, hashed_password VARCHAR, is_superuser BOOLEAN DEFAULT 0);
      CREATE TABLE file_uploads (id INTEGER PRIMARY KEY, filename VARCHAR, original_filename VARCHAR, file_path VARCHAR, content_type VARCHAR, user_id INTEGER, tags TEXT);
      CREATE TABLE wiki_pages (id INTEGER PRIMARY KEY, user_id INTEGER, parent_id INTEGER, path VARCHAR, slug VARCHAR, title VARCHAR, content VARCHAR, tags TEXT);
      CREATE TABLE wiki_links (id INTEGER PRIMARY KEY, user_id INTEGER, source_page_id INTEGER, target_page_id INTEGER, target_title VARCHAR, alias VARCHAR, link_type VARCHAR, section_anchor VARCHAR);
    `);
    v1.prepare('INSERT INTO users (id, email, hashed_password, is_superuser) VALUES (99, ?, ?, 1)').run(
      'oldadmin@legacy.local',
      'hash'
    );
    v1.prepare('INSERT INTO file_uploads (filename, original_filename, file_path, content_type, user_id, tags) VALUES (?, ?, ?, ?, ?, ?)').run(
      'handbook.md',
      'handbook.md',
      fPath,
      'text/markdown',
      99,
      JSON.stringify(['旧库资料'])
    );
    v1.prepare('INSERT INTO wiki_pages (id, user_id, parent_id, path, slug, title, content, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(
      1,
      99,
      null,
      '/1/',
      'legacy-root',
      '旧版根页面',
      '引用 [[旧版子页面]]',
      JSON.stringify(['迁移'])
    );
    v1.prepare('INSERT INTO wiki_pages (id, user_id, parent_id, path, slug, title, content, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(
      2,
      99,
      1,
      '/1/2/',
      'legacy-child',
      '旧版子页面',
      '子页面正文',
      '[]'
    );
    v1.prepare(
      'INSERT INTO wiki_links (user_id, source_page_id, target_page_id, target_title, alias, link_type, section_anchor) VALUES (99, 1, 2, ?, ?, ?, ?)'
    ).run('旧版子页面', '', 'wikilink', '');
    v1.close();

    // 3. Test GET /resources/import-legacy/detect + POST local_v1
    const prevLegacyEnv = process.env['WENJV_LEGACY_DIR'];
    process.env['WENJV_LEGACY_DIR'] = legacyDir;
    try {
      const detectResp = await env.app.request('/resources/import-legacy/detect', {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(detectResp.status).toBe(200);
      const detectData = (await detectResp.json()) as {
        detected: boolean;
        preview: { files: number; wikiPages: number; foundOnDisk: number };
      };
      expect(detectData.detected).toBe(true);
      expect(detectData.preview.files).toBe(1);
      expect(detectData.preview.wikiPages).toBe(2);
      expect(detectData.preview.foundOnDisk).toBe(1);

      const importResp = await env.app.request('/resources/import-legacy', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: 'local_v1', skip_missing: true }),
      });
      expect(importResp.status).toBe(200);
      const importData = (await importResp.json()) as {
        status: string;
        stats: { files: number; wikiPages: number; wikiLinks: number; users: number };
        enqueued: number;
      };
      expect(importData.status).toBe('ok');
      expect(importData.stats.users).toBe(0); // Must NOT import foreign users into active runtime
      expect(importData.stats.files).toBe(1);
      expect(importData.stats.wikiPages).toBe(2);
      expect(importData.stats.wikiLinks).toBe(1);
      expect(importData.enqueued).toBe(3);

      // Existing wiki page #1 must remain intact, and new hierarchy remapped cleanly
      const treeResp = await env.app.request('/wiki/tree', {
        headers: { Authorization: `Bearer ${token}` },
      });
      const tree = (await treeResp.json()) as Array<{ title: string; children: Array<{ title: string }> }>;
      expect(tree.some((n) => n.title === '现有新页面')).toBe(true);
      const importedRoot = tree.find((n) => n.title === '旧版根页面');
      expect(importedRoot?.children[0]?.title).toBe('旧版子页面');

      // 4. Test multipart upload import of a backup wenjv.db + attachment file
      const fd = new FormData();
      fd.append('db', new File([fs.readFileSync(v1DbPath)], 'wenjv.db', { type: 'application/octet-stream' }));
      fd.append('files', new File([fs.readFileSync(fPath)], 'handbook.md', { type: 'text/markdown' }));
      const uploadResp = await env.app.request('/resources/import-legacy', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      expect(uploadResp.status).toBe(200);
      const uploadData = (await uploadResp.json()) as { stats: { files: number; wikiPages: number } };
      expect(uploadData.stats.files).toBe(1);
      expect(uploadData.stats.wikiPages).toBe(2);
    } finally {
      if (prevLegacyEnv === undefined) delete process.env['WENJV_LEGACY_DIR'];
      else process.env['WENJV_LEGACY_DIR'] = prevLegacyEnv;
    }
  });
});

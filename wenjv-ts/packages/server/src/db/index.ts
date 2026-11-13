import Database from 'better-sqlite3';
import fs from 'node:fs';
import path from 'node:path';
import { config } from '../config.js';
import { createFts5Table } from './fts5.js';

let _db: Database.Database | null = null;

export function getDb(dbPath?: string): Database.Database {
  if (_db && !dbPath) {
    return _db;
  }
  if (_db && dbPath) {
    try {
      _db.close();
    } catch {
      // ignore
    }
    _db = null;
  }

  const targetPath = dbPath || config.resolvedDbPath;
  const dir = path.dirname(targetPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const db = new Database(targetPath);
  db.pragma('journal_mode = WAL');
  db.pragma('synchronous = NORMAL');
  db.pragma('busy_timeout = 5000');
  db.pragma('foreign_keys = ON');
  db.pragma('cache_size = -64000');

  initTables(db);

  _db = db;
  return db;
}

export function closeDb(): void {
  if (_db) {
    try {
      _db.close();
    } catch {
      // ignore
    }
    _db = null;
  }
}

export function initTables(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email VARCHAR NOT NULL UNIQUE,
      username VARCHAR UNIQUE,
      hashed_password VARCHAR NOT NULL,
      is_active BOOLEAN NOT NULL DEFAULT 1,
      is_superuser BOOLEAN NOT NULL DEFAULT 0,
      is_verified BOOLEAN NOT NULL DEFAULT 0
    );

    -- Schema v2: Unified 3-in-1 resources (file / note / link)
    CREATE TABLE IF NOT EXISTS resources (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      type VARCHAR(16) NOT NULL CHECK (type IN ('file', 'note', 'link')),
      title VARCHAR NOT NULL,
      filename VARCHAR,
      original_filename VARCHAR,
      file_path VARCHAR,
      source_url VARCHAR,
      content_text TEXT,
      content_type VARCHAR,
      favicon VARCHAR,
      status VARCHAR(16) NOT NULL DEFAULT 'pending',
      error_message VARCHAR,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS ix_resources_user_type ON resources(user_id, type);
    CREATE INDEX IF NOT EXISTS ix_resources_user_status ON resources(user_id, status);
    CREATE INDEX IF NOT EXISTS ix_resources_user_filename ON resources(user_id, filename);

    -- Schema v2: Unified multimodal visual assets (resource / wiki / chat)
    CREATE TABLE IF NOT EXISTS assets (
      id VARCHAR(64) PRIMARY KEY,
      user_id INTEGER NOT NULL,
      owner_type VARCHAR(16) NOT NULL CHECK (owner_type IN ('resource', 'wiki', 'chat')),
      owner_id VARCHAR(128) NOT NULL,
      filename VARCHAR NOT NULL,
      file_path VARCHAR NOT NULL,
      mime_type VARCHAR NOT NULL,
      size INTEGER NOT NULL DEFAULT 0,
      caption TEXT NOT NULL DEFAULT '',
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS ix_assets_owner ON assets(user_id, owner_type, owner_id);
    CREATE INDEX IF NOT EXISTS ix_assets_path ON assets(file_path);

    -- Wiki core tables (tags normalized into tags + entity_tags)
    CREATE TABLE IF NOT EXISTS wiki_pages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      parent_id INTEGER,
      path VARCHAR(512) NOT NULL,
      slug VARCHAR(255) NOT NULL,
      title VARCHAR(255) NOT NULL,
      content VARCHAR NOT NULL,
      summary VARCHAR(512) NOT NULL DEFAULT '',
      sort_order INTEGER NOT NULL DEFAULT 0,
      icon VARCHAR(64) NOT NULL DEFAULT '',
      index_status VARCHAR(16) NOT NULL DEFAULT 'indexed',
      revision_count INTEGER NOT NULL DEFAULT 1,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT uq_wiki_user_slug UNIQUE (user_id, slug),
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
      FOREIGN KEY(parent_id) REFERENCES wiki_pages (id)
    );

    CREATE TABLE IF NOT EXISTS wiki_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      source_page_id INTEGER NOT NULL,
      target_page_id INTEGER,
      target_title VARCHAR(255) NOT NULL,
      alias VARCHAR(255) NOT NULL DEFAULT '',
      link_type VARCHAR(16) NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      section_anchor TEXT NOT NULL DEFAULT '',
      CONSTRAINT uq_wiki_link UNIQUE (user_id, source_page_id, target_title, alias, section_anchor, link_type),
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
      FOREIGN KEY(source_page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE,
      FOREIGN KEY(target_page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE
    );

    CREATE UNIQUE INDEX IF NOT EXISTS uq_wiki_link_nonnull
      ON wiki_links(user_id, source_page_id, target_title, COALESCE(alias, ''), COALESCE(section_anchor, ''), link_type);

    CREATE TABLE IF NOT EXISTS wiki_revisions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      page_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      rev_no INTEGER NOT NULL,
      title VARCHAR(255) NOT NULL,
      content VARCHAR NOT NULL,
      char_count INTEGER NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS wiki_aliases (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      page_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      alias_title VARCHAR(255) NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT uq_wiki_alias_user_title UNIQUE (user_id, alias_title),
      FOREIGN KEY(page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    -- Schema v2: Relational tags dictionary + polymorphic entity_tags
    CREATE TABLE IF NOT EXISTS tags (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      name VARCHAR(64) NOT NULL,
      color VARCHAR(16) NOT NULL DEFAULT '',
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT uq_tags_user_name UNIQUE (user_id, name),
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS entity_tags (
      tag_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      entity_type VARCHAR(16) NOT NULL CHECK (entity_type IN ('resource', 'wiki')),
      entity_id INTEGER NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (tag_id, entity_type, entity_id),
      FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS ix_entity_tags_lookup ON entity_tags(user_id, entity_type, entity_id);

    -- Schema v2: Authoritative chunk table (single source of truth for FTS5 & LanceDB hydration)
    CREATE TABLE IF NOT EXISTS chunks (
      id VARCHAR PRIMARY KEY,
      user_id INTEGER NOT NULL,
      entity_type VARCHAR(16) NOT NULL CHECK (entity_type IN ('resource', 'wiki')),
      entity_id INTEGER NOT NULL,
      resource_type VARCHAR(16) NOT NULL CHECK (resource_type IN ('file', 'note', 'link', 'wiki')),
      chunk_order INTEGER NOT NULL,
      page_number INTEGER NOT NULL DEFAULT 1,
      header_path TEXT NOT NULL DEFAULT '',
      title VARCHAR NOT NULL DEFAULT '',
      source VARCHAR NOT NULL DEFAULT '',
      content TEXT NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS ix_chunks_entity ON chunks(user_id, entity_type, entity_id, chunk_order);
    CREATE INDEX IF NOT EXISTS ix_chunks_source ON chunks(user_id, resource_type);

    -- Unified persistent ingestion jobs
    CREATE TABLE IF NOT EXISTS ingestion_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      entity_type VARCHAR(16) NOT NULL CHECK (entity_type IN ('resource', 'wiki')),
      entity_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      user_email VARCHAR NOT NULL,
      payload VARCHAR NOT NULL,
      status VARCHAR NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3,
      last_error VARCHAR,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME,
      started_at DATETIME,
      finished_at DATETIME,
      FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );

    CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_jobs_pending
      ON ingestion_jobs(entity_type, entity_id, user_id)
      WHERE status = 'pending';

    CREATE TABLE IF NOT EXISTS query_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      "query" TEXT NOT NULL,
      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
      latency_ms FLOAT NOT NULL,
      v_hits INTEGER NOT NULL,
      fts5_hits INTEGER NOT NULL,
      s_hits INTEGER NOT NULL,
      total_hits INTEGER NOT NULL,
      cache_hit BOOLEAN NOT NULL,
      error TEXT
    );

    CREATE TABLE IF NOT EXISTS api_call_counts (
      provider VARCHAR NOT NULL,
      call_type VARCHAR NOT NULL,
      call_count INTEGER NOT NULL DEFAULT 0,
      last_reset DATETIME,
      PRIMARY KEY (provider, call_type)
    );

    CREATE TABLE IF NOT EXISTS embed_cache (
      text_hash VARCHAR NOT NULL,
      model VARCHAR NOT NULL,
      vector BLOB NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
      PRIMARY KEY (text_hash, model)
    );

    CREATE TABLE IF NOT EXISTS query_result_cache (
      query_hash VARCHAR NOT NULL,
      user_id INTEGER NOT NULL,
      result_json TEXT NOT NULL,
      expires_at DATETIME NOT NULL,
      PRIMARY KEY (query_hash, user_id)
    );
  `);

  createFts5Table(db);
}

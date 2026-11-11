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

    CREATE TABLE IF NOT EXISTS file_uploads (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      filename VARCHAR,
      original_filename VARCHAR,
      file_path VARCHAR,
      file_url VARCHAR,
      status VARCHAR,
      content_type VARCHAR,
      error_message VARCHAR,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME,
      user_id INTEGER,
      tags TEXT DEFAULT '[]',
      FOREIGN KEY(user_id) REFERENCES users (id)
    );

    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url VARCHAR,
      title VARCHAR,
      favicon VARCHAR,
      status VARCHAR,
      error_message VARCHAR,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME,
      user_id INTEGER,
      tags TEXT DEFAULT '[]',
      FOREIGN KEY(user_id) REFERENCES users (id)
    );

    CREATE TABLE IF NOT EXISTS notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url VARCHAR,
      title VARCHAR,
      filename VARCHAR,
      file_path VARCHAR,
      status VARCHAR,
      error_message VARCHAR,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME,
      user_id INTEGER,
      tags TEXT DEFAULT '[]',
      FOREIGN KEY(user_id) REFERENCES users (id)
    );

    CREATE TABLE IF NOT EXISTS ingestion_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_type VARCHAR NOT NULL,
      resource_id INTEGER NOT NULL,
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
      FOREIGN KEY(user_id) REFERENCES users (id)
    );

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
      tags VARCHAR NOT NULL DEFAULT '[]',
      index_status VARCHAR(16) NOT NULL DEFAULT 'indexed',
      revision_count INTEGER NOT NULL DEFAULT 1,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT uq_wiki_user_slug UNIQUE (user_id, slug),
      FOREIGN KEY(user_id) REFERENCES users (id),
      FOREIGN KEY(parent_id) REFERENCES wiki_pages (id)
    );

    CREATE TABLE IF NOT EXISTS wiki_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      source_page_id INTEGER NOT NULL,
      target_page_id INTEGER,
      target_title VARCHAR(255) NOT NULL,
      alias VARCHAR(255),
      link_type VARCHAR(16) NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      section_anchor TEXT,
      CONSTRAINT uq_wiki_link UNIQUE (user_id, source_page_id, target_title, alias, link_type),
      FOREIGN KEY(user_id) REFERENCES users (id),
      FOREIGN KEY(source_page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE,
      FOREIGN KEY(target_page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE
    );

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
      FOREIGN KEY(user_id) REFERENCES users (id)
    );

    CREATE TABLE IF NOT EXISTS wiki_aliases (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      page_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      alias_title VARCHAR(255) NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT uq_wiki_alias_user_title UNIQUE (user_id, alias_title),
      FOREIGN KEY(page_id) REFERENCES wiki_pages (id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users (id)
    );

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

    CREATE TABLE IF NOT EXISTS chunk_mapping (
      chunk_id VARCHAR PRIMARY KEY,
      chunk_group VARCHAR NOT NULL,
      chunk_order INTEGER NOT NULL,
      resource_id VARCHAR
    );

    CREATE TABLE IF NOT EXISTS doc_embeddings (
      resource_id VARCHAR PRIMARY KEY,
      embedding BLOB NOT NULL,
      dims INTEGER NOT NULL,
      chunk_count INTEGER NOT NULL,
      updated_at DATETIME
    );
  `);

  createFts5Table(db);
}

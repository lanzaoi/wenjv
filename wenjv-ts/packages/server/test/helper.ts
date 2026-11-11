import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { getDb, closeDb } from '../src/db/index.js';
import { loadConfig } from '../src/config.js';
import { resetDocumentStore } from '../src/vector/document-store.js';
import { createApp } from '../src/main.js';
import type { Hono } from 'hono';

export interface TestEnv {
  tmpDir: string;
  app: Hono;
  cleanup: () => void;
}

export function setupTestEnv(): TestEnv {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wenjv-test-'));
  const dbPath = path.join(tmpDir, 'test.db');
  const lanceDir = path.join(tmpDir, 'lance_db');
  const uploadDir = path.join(tmpDir, 'uploads');
  const vaultDir = path.join(tmpDir, 'wiki_vault');

  process.env['WENJV_BASE_DIR'] = tmpDir;
  process.env['BASE_DIR'] = tmpDir;
  process.env['NODE_ENV'] = 'test';

  loadConfig({
    BASE_DIR: tmpDir,
    DB_PATH: dbPath,
    LANCE_DIR: lanceDir,
    UPLOAD_DIR: uploadDir,
    VAULT_DIR: vaultDir,
  });

  closeDb();
  resetDocumentStore();
  getDb(dbPath);

  const app = createApp();

  const cleanup = () => {
    closeDb();
    resetDocumentStore();
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  };

  return { tmpDir, app, cleanup };
}

import fs from 'node:fs';
import path from 'node:path';
import Database from 'better-sqlite3';
import { config } from '../config.js';
import { getDb } from '../db/index.js';
import { deleteEntityChunks } from '../db/chunks.js';
import { setEntityTags } from './tags.js';
import { claimNextJob, enqueueJob, executeJob } from './jobs.js';
import { getTextStore } from '../vector/text-store.js';
import { getVisualStore } from '../vector/visual-store.js';

export interface ImportV1Stats {
  users: number;
  files: number;
  notes: number;
  links: number;
  wikiPages: number;
  wikiRevisions: number;
  wikiLinks: number;
  wikiAliases: number;
  copiedFiles: number;
  missingFiles: number;
}

export interface RebuildStats {
  enqueuedResources: number;
  enqueuedWikiPages: number;
  processed: number;
  succeeded: number;
  failed: number;
  failures: Array<{ entityType: string; entityId: number; error: string }>;
}

function tableExists(db: Database.Database, name: string): boolean {
  const row = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name = ?")
    .get(name) as { name: string } | undefined;
  return Boolean(row);
}

function parseJsonTags(raw: unknown): string[] {
  if (!raw || typeof raw !== 'string') return [];
  const trimmed = raw.trim();
  if (!trimmed) return [];
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (Array.isArray(parsed)) {
      return parsed.map((item) => String(item).trim()).filter(Boolean);
    }
  } catch {
    return trimmed
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

function resolveSourceFile(
  rawFilePath: unknown,
  filename: unknown,
  sourceUploadsDir?: string
): string | null {
  const rawStr = typeof rawFilePath === 'string' ? rawFilePath.trim() : '';
  const nameStr = typeof filename === 'string' ? filename.trim() : '';

  const candidates: string[] = [];
  if (rawStr) {
    if (path.isAbsolute(rawStr)) {
      candidates.push(rawStr);
    } else {
      if (sourceUploadsDir) candidates.push(path.join(sourceUploadsDir, rawStr));
      candidates.push(path.join(config.resolvedUploadDir, rawStr));
    }
  }
  if (nameStr) {
    const base = path.basename(nameStr);
    if (sourceUploadsDir) {
      candidates.push(path.join(sourceUploadsDir, nameStr));
      candidates.push(path.join(sourceUploadsDir, base));
    }
    candidates.push(path.join(config.resolvedUploadDir, base));
  }

  for (const cand of candidates) {
    if (cand && fs.existsSync(cand) && fs.statSync(cand).isFile()) {
      return cand;
    }
  }
  return null;
}

function ensureTargetUploadFile(
  rawFilePath: unknown,
  filename: unknown,
  sourceUploadsDir: string | undefined,
  copyFiles: boolean,
  stats: ImportV1Stats
): { targetFilePath: string; targetFilename: string; foundOnDisk: boolean } {
  const fallbackName =
    typeof filename === 'string' && filename.trim()
      ? path.basename(filename.trim())
      : typeof rawFilePath === 'string' && rawFilePath.trim()
        ? path.basename(rawFilePath.trim())
        : 'resource.bin';

  const targetDir = config.resolvedUploadDir;
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }
  const destPath = path.join(targetDir, fallbackName);
  const srcPath = resolveSourceFile(rawFilePath, fallbackName, sourceUploadsDir);

  if (!srcPath) {
    stats.missingFiles++;
    return { targetFilePath: destPath, targetFilename: fallbackName, foundOnDisk: false };
  }

  if (copyFiles && path.resolve(srcPath) !== path.resolve(destPath)) {
    fs.copyFileSync(srcPath, destPath);
    stats.copiedFiles++;
    return { targetFilePath: destPath, targetFilename: fallbackName, foundOnDisk: true };
  }

  return { targetFilePath: srcPath, targetFilename: path.basename(srcPath), foundOnDisk: true };
}

/**
 * Import legacy v1 tables (`users`, `file_uploads`, `notes`, `links`, `wiki_*`) read-only
 * into a clean Schema v2 target database without mutating the source database.
 */
export function importV1SnapshotIntoV2(options: {
  v1DbPath: string;
  sourceUploadsDir?: string;
  copyFiles?: boolean;
  skipMissing?: boolean;
}): ImportV1Stats {
  const v1Db = new Database(options.v1DbPath, { readonly: true, fileMustExist: true });
  const targetDb = getDb();
  const copyFiles = options.copyFiles !== false;
  const skipMissing = Boolean(options.skipMissing);

  const stats: ImportV1Stats = {
    users: 0,
    files: 0,
    notes: 0,
    links: 0,
    wikiPages: 0,
    wikiRevisions: 0,
    wikiLinks: 0,
    wikiAliases: 0,
    copiedFiles: 0,
    missingFiles: 0,
  };

  try {
    const runTx = targetDb.transaction(() => {
      targetDb.pragma('defer_foreign_keys = ON');

      if (tableExists(v1Db, 'users')) {
        const users = v1Db.prepare('SELECT * FROM users ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        const insertUser = targetDb.prepare(`
          INSERT OR IGNORE INTO users (id, email, username, hashed_password, is_active, is_superuser, is_verified)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `);
        for (const u of users) {
          const r = insertUser.run(
            Number(u['id']),
            String(u['email']),
            u['username'] ? String(u['username']) : null,
            String(u['hashed_password']),
            u['is_active'] ? 1 : 0,
            u['is_superuser'] ? 1 : 0,
            u['is_verified'] ? 1 : 0
          );
          if (r.changes > 0) stats.users++;
        }
      }

      const insertResource = targetDb.prepare(`
        INSERT INTO resources (
          user_id, type, title, filename, original_filename, file_path,
          source_url, content_text, content_type, favicon, status, error_message,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
      `);

      if (tableExists(v1Db, 'file_uploads')) {
        const files = v1Db.prepare('SELECT * FROM file_uploads ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        for (const row of files) {
          const userId = Number(row['user_id']);
          const { targetFilePath, targetFilename, foundOnDisk } = ensureTargetUploadFile(
            row['file_path'],
            row['filename'],
            options.sourceUploadsDir,
            copyFiles,
            stats
          );
          if (skipMissing && !foundOnDisk) continue;
          const origName = row['original_filename'] ? String(row['original_filename']) : targetFilename;
          const res = insertResource.run(
            userId,
            'file',
            origName,
            targetFilename,
            origName,
            targetFilePath,
            row['file_url'] ? String(row['file_url']) : null,
            null,
            row['content_type'] ? String(row['content_type']) : null,
            null,
            'pending',
            null,
            row['created_at'] ? String(row['created_at']) : null,
            row['updated_at'] ? String(row['updated_at']) : null
          );
          const resourceId = Number(res.lastInsertRowid);
          const tags = parseJsonTags(row['tags']);
          if (tags.length > 0) {
            setEntityTags(targetDb, userId, 'resource', resourceId, tags);
          }
          stats.files++;
        }
      }

      if (tableExists(v1Db, 'notes')) {
        const notes = v1Db.prepare('SELECT * FROM notes ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        for (const row of notes) {
          const userId = Number(row['user_id']);
          const { targetFilePath, targetFilename, foundOnDisk } = ensureTargetUploadFile(
            row['file_path'],
            row['filename'],
            options.sourceUploadsDir,
            copyFiles,
            stats
          );
          if (skipMissing && !foundOnDisk) continue;
          const noteContent = fs.existsSync(targetFilePath) ? fs.readFileSync(targetFilePath, 'utf8') : '';
          const title = String(row['title'] || targetFilename || 'Untitled Note');
          const res = insertResource.run(
            userId,
            'note',
            title,
            targetFilename,
            targetFilename,
            targetFilePath,
            row['url'] ? String(row['url']) : null,
            noteContent,
            'text/markdown',
            null,
            'pending',
            null,
            row['created_at'] ? String(row['created_at']) : null,
            row['updated_at'] ? String(row['updated_at']) : null
          );
          const resourceId = Number(res.lastInsertRowid);
          const tags = parseJsonTags(row['tags']);
          if (tags.length > 0) {
            setEntityTags(targetDb, userId, 'resource', resourceId, tags);
          }
          stats.notes++;
        }
      }

      if (tableExists(v1Db, 'links')) {
        const links = v1Db.prepare('SELECT * FROM links ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        for (const row of links) {
          const userId = Number(row['user_id']);
          const url = String(row['url'] || '');
          const title = String(row['title'] || url || 'Link');
          const res = insertResource.run(
            userId,
            'link',
            title,
            null,
            null,
            null,
            url,
            null,
            'text/html',
            row['favicon'] ? String(row['favicon']) : null,
            'pending',
            null,
            row['created_at'] ? String(row['created_at']) : null,
            row['updated_at'] ? String(row['updated_at']) : null
          );
          const resourceId = Number(res.lastInsertRowid);
          const tags = parseJsonTags(row['tags']);
          if (tags.length > 0) {
            setEntityTags(targetDb, userId, 'resource', resourceId, tags);
          }
          stats.links++;
        }
      }

      if (tableExists(v1Db, 'wiki_pages')) {
        const pages = v1Db
          .prepare('SELECT * FROM wiki_pages ORDER BY length(path) ASC, id ASC')
          .all() as Array<Record<string, unknown>>;
        const insertWikiPage = targetDb.prepare(`
          INSERT OR REPLACE INTO wiki_pages (
            id, user_id, parent_id, path, slug, title, content, summary,
            sort_order, icon, index_status, revision_count, created_at, updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
        `);

        for (const p of pages) {
          const pageId = Number(p['id']);
          const userId = Number(p['user_id']);
          insertWikiPage.run(
            pageId,
            userId,
            p['parent_id'] !== null && p['parent_id'] !== undefined ? Number(p['parent_id']) : null,
            String(p['path'] || '/'),
            String(p['slug']),
            String(p['title']),
            String(p['content'] || ''),
            String(p['summary'] || ''),
            Number(p['sort_order'] || 0),
            String(p['icon'] || ''),
            'pending',
            Number(p['revision_count'] || 1),
            p['created_at'] ? String(p['created_at']) : null,
            p['updated_at'] ? String(p['updated_at']) : null
          );
          const tags = parseJsonTags(p['tags']);
          if (tags.length > 0) {
            setEntityTags(targetDb, userId, 'wiki', pageId, tags);
          }
          stats.wikiPages++;
        }
      }

      if (tableExists(v1Db, 'wiki_revisions')) {
        const revs = v1Db.prepare('SELECT * FROM wiki_revisions ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        const insertRev = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_revisions (id, page_id, user_id, rev_no, title, content, char_count, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        for (const r of revs) {
          const res = insertRev.run(
            Number(r['id']),
            Number(r['page_id']),
            Number(r['user_id']),
            Number(r['rev_no']),
            String(r['title']),
            String(r['content'] || ''),
            Number(r['char_count'] || 0),
            r['created_at'] ? String(r['created_at']) : null
          );
          if (res.changes > 0) stats.wikiRevisions++;
        }
      }

      if (tableExists(v1Db, 'wiki_links')) {
        const wLinks = v1Db.prepare('SELECT * FROM wiki_links ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        const insertWLink = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_links (
            id, user_id, source_page_id, target_page_id, target_title, alias, link_type, section_anchor, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        for (const l of wLinks) {
          const res = insertWLink.run(
            Number(l['id']),
            Number(l['user_id']),
            Number(l['source_page_id']),
            l['target_page_id'] !== null && l['target_page_id'] !== undefined ? Number(l['target_page_id']) : null,
            String(l['target_title']),
            String(l['alias'] || ''),
            String(l['link_type'] || 'wikilink'),
            String(l['section_anchor'] || ''),
            l['created_at'] ? String(l['created_at']) : null
          );
          if (res.changes > 0) stats.wikiLinks++;
        }
      }

      if (tableExists(v1Db, 'wiki_aliases')) {
        const aliases = v1Db.prepare('SELECT * FROM wiki_aliases ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        const insertAlias = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_aliases (id, page_id, user_id, alias_title, created_at)
          VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        for (const a of aliases) {
          const res = insertAlias.run(
            Number(a['id']),
            Number(a['page_id']),
            Number(a['user_id']),
            String(a['alias_title']),
            a['created_at'] ? String(a['created_at']) : null
          );
          if (res.changes > 0) stats.wikiAliases++;
        }
      }
    });

    runTx();
  } finally {
    v1Db.close();
  }

  return stats;
}

/**
 * Rebuild `chunks`, `chunks_fts`, `text_vectors`, and resource `assets` / `visual_vectors`
 * from authoritative `resources` and `wiki_pages` rows in Schema v2.
 */
export async function rebuildAllIndexes(options?: {
  includeLinks?: boolean;
  cleanExisting?: boolean;
}): Promise<RebuildStats> {
  const db = getDb();
  const cleanExisting = options?.cleanExisting !== false;
  const includeLinks = Boolean(options?.includeLinks);

  const userRows = db.prepare('SELECT id, email FROM users').all() as Array<{ id: number; email: string }>;
  const emailByUserId = new Map<number, string>();
  for (const u of userRows) {
    emailByUserId.set(u.id, u.email);
  }

  const resources = db
    .prepare('SELECT id, user_id, type FROM resources ORDER BY id ASC')
    .all() as Array<{ id: number; user_id: number; type: 'file' | 'note' | 'link' }>;
  const wikiPages = db
    .prepare('SELECT id, user_id FROM wiki_pages ORDER BY id ASC')
    .all() as Array<{ id: number; user_id: number }>;

  if (cleanExisting) {
    const textStore = getTextStore();
    const visualStore = getVisualStore();
    for (const r of resources) {
      deleteEntityChunks(db, 'resource', r.id, r.user_id);
      await textStore.deleteByEntity('resource', r.id, r.user_id);
      db.prepare("DELETE FROM assets WHERE owner_type = 'resource' AND owner_id = ? AND user_id = ?").run(
        String(r.id),
        r.user_id
      );
      await visualStore.deleteByOwner('resource', r.id, r.user_id);
    }
    for (const w of wikiPages) {
      deleteEntityChunks(db, 'wiki', w.id, w.user_id);
      await textStore.deleteByEntity('wiki', w.id, w.user_id);
    }
    db.prepare("DELETE FROM ingestion_jobs WHERE status IN ('pending', 'running')").run();
  }

  const stats: RebuildStats = {
    enqueuedResources: 0,
    enqueuedWikiPages: 0,
    processed: 0,
    succeeded: 0,
    failed: 0,
    failures: [],
  };

  for (const r of resources) {
    if (r.type === 'link' && !includeLinks) continue;
    enqueueJob({
      entity_type: 'resource',
      entity_id: r.id,
      user_id: r.user_id,
      user_email: emailByUserId.get(r.user_id) || `user-${r.user_id}`,
    });
    stats.enqueuedResources++;
  }

  for (const w of wikiPages) {
    enqueueJob({
      entity_type: 'wiki',
      entity_id: w.id,
      user_id: w.user_id,
      user_email: emailByUserId.get(w.user_id) || `user-${w.user_id}`,
    });
    stats.enqueuedWikiPages++;
  }

  while (true) {
    const job = claimNextJob();
    if (!job) break;
    stats.processed++;
    try {
      await executeJob(job);
      const updated = db.prepare('SELECT status, last_error FROM ingestion_jobs WHERE id = ?').get(job.id) as
        | { status: string; last_error: string | null }
        | undefined;
      if (updated?.status === 'failed') {
        stats.failed++;
        stats.failures.push({
          entityType: job.entity_type,
          entityId: job.entity_id,
          error: updated.last_error || 'unknown job failure',
        });
      } else {
        stats.succeeded++;
      }
    } catch (err: unknown) {
      stats.failed++;
      stats.failures.push({
        entityType: job.entity_type,
        entityId: job.entity_id,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return stats;
}

import fs from 'node:fs';
import path from 'node:path';
import Database from 'better-sqlite3';
import { config } from '../config.js';
import { getDb } from '../db/index.js';
import { deleteEntityChunks } from '../db/chunks.js';
import { setEntityTags } from './tags.js';
import { syncPageToVault } from './wiki.js';
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
  importedResourceIds: number[];
  importedWikiPageIds: number[];
}

export interface LegacyV1Inspection {
  isValidLegacyDb: boolean;
  files: number;
  notes: number;
  links: number;
  wikiPages: number;
  foundOnDisk: number;
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

function resolveUniqueTargetPath(targetDir: string, preferredName: string): string {
  const initial = path.join(targetDir, preferredName);
  if (!fs.existsSync(initial)) return initial;
  const parsed = path.parse(preferredName);
  return path.join(targetDir, `${parsed.name}-${Date.now().toString(36)}${parsed.ext}`);
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
  const srcPath = resolveSourceFile(rawFilePath, fallbackName, sourceUploadsDir);

  if (!srcPath) {
    stats.missingFiles++;
    return { targetFilePath: path.join(targetDir, fallbackName), targetFilename: fallbackName, foundOnDisk: false };
  }

  const destPath = copyFiles ? resolveUniqueTargetPath(targetDir, fallbackName) : srcPath;
  if (copyFiles && path.resolve(srcPath) !== path.resolve(destPath)) {
    fs.copyFileSync(srcPath, destPath);
    stats.copiedFiles++;
    return { targetFilePath: destPath, targetFilename: path.basename(destPath), foundOnDisk: true };
  }

  return { targetFilePath: srcPath, targetFilename: path.basename(srcPath), foundOnDisk: true };
}

/**
 * Inspect a legacy v1 SQLite database read-only before importing.
 */
export function inspectLegacyV1Source(v1DbPath: string, sourceUploadsDir?: string): LegacyV1Inspection {
  let v1Db: Database.Database | null = null;
  try {
    v1Db = new Database(v1DbPath, { readonly: true, fileMustExist: true });
    const hasFiles = tableExists(v1Db, 'file_uploads');
    const hasNotes = tableExists(v1Db, 'notes');
    const hasLinks = tableExists(v1Db, 'links');
    const hasWiki = tableExists(v1Db, 'wiki_pages');

    if (!hasFiles && !hasNotes && !hasLinks && !hasWiki) {
      return { isValidLegacyDb: false, files: 0, notes: 0, links: 0, wikiPages: 0, foundOnDisk: 0, missingFiles: 0 };
    }

    let foundOnDisk = 0;
    let missingFiles = 0;
    let filesCount = 0;
    let notesCount = 0;

    if (hasFiles) {
      const files = v1Db.prepare('SELECT file_path, filename FROM file_uploads').all() as Array<Record<string, unknown>>;
      filesCount = files.length;
      for (const f of files) {
        if (resolveSourceFile(f['file_path'], f['filename'], sourceUploadsDir)) foundOnDisk++;
        else missingFiles++;
      }
    }

    if (hasNotes) {
      const notes = v1Db.prepare('SELECT file_path, filename FROM notes').all() as Array<Record<string, unknown>>;
      notesCount = notes.length;
      for (const n of notes) {
        if (resolveSourceFile(n['file_path'], n['filename'], sourceUploadsDir)) foundOnDisk++;
        else missingFiles++;
      }
    }

    const linksCount = hasLinks
      ? ((v1Db.prepare('SELECT COUNT(*) as c FROM links').get() as { c: number })?.c || 0)
      : 0;
    const wikiCount = hasWiki
      ? ((v1Db.prepare('SELECT COUNT(*) as c FROM wiki_pages').get() as { c: number })?.c || 0)
      : 0;

    return {
      isValidLegacyDb: true,
      files: filesCount,
      notes: notesCount,
      links: linksCount,
      wikiPages: wikiCount,
      foundOnDisk,
      missingFiles,
    };
  } catch {
    return { isValidLegacyDb: false, files: 0, notes: 0, links: 0, wikiPages: 0, foundOnDisk: 0, missingFiles: 0 };
  } finally {
    v1Db?.close();
  }
}

/**
 * Import legacy v1 tables (`users`, `file_uploads`, `notes`, `links`, `wiki_*`) read-only
 * into a Schema v2 target database without mutating the source database.
 * When `targetUserId` is set (browser import), rows are safely mapped to that authenticated user
 * with fresh Wiki IDs and deduplicated slugs instead of touching `users` or overwriting existing IDs.
 */
export function importV1SnapshotIntoV2(options: {
  v1DbPath: string;
  sourceUploadsDir?: string;
  copyFiles?: boolean;
  skipMissing?: boolean;
  targetUserId?: number;
  targetUserEmail?: string;
}): ImportV1Stats {
  const v1Db = new Database(options.v1DbPath, { readonly: true, fileMustExist: true });
  const targetDb = getDb();
  const copyFiles = options.copyFiles !== false;
  const skipMissing = Boolean(options.skipMissing);
  const remapToUser = options.targetUserId !== undefined;

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
    importedResourceIds: [],
    importedWikiPageIds: [],
  };

  try {
    const hasLegacySchema =
      tableExists(v1Db, 'file_uploads') ||
      tableExists(v1Db, 'notes') ||
      tableExists(v1Db, 'links') ||
      tableExists(v1Db, 'wiki_pages');

    if (!hasLegacySchema) {
      throw new Error('上传的文件不是有效的旧版 wenjv.db 数据库');
    }

    const runTx = targetDb.transaction(() => {
      targetDb.pragma('defer_foreign_keys = ON');

      if (!remapToUser && tableExists(v1Db, 'users')) {
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
          const userId = remapToUser ? options.targetUserId! : Number(row['user_id']);
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
          stats.importedResourceIds.push(resourceId);
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
          const userId = remapToUser ? options.targetUserId! : Number(row['user_id']);
          const { targetFilePath, targetFilename, foundOnDisk } = ensureTargetUploadFile(
            row['file_path'],
            row['filename'],
            options.sourceUploadsDir,
            copyFiles,
            stats
          );
          const inlineFallback = typeof row['content'] === 'string' ? row['content'] : '';
          const noteContent = foundOnDisk && fs.existsSync(targetFilePath)
            ? fs.readFileSync(targetFilePath, 'utf8')
            : inlineFallback;
          if (skipMissing && !foundOnDisk && !noteContent) continue;
          const title = String(row['title'] || targetFilename || 'Untitled Note');
          const res = insertResource.run(
            userId,
            'note',
            title,
            targetFilename,
            targetFilename,
            foundOnDisk ? targetFilePath : null,
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
          stats.importedResourceIds.push(resourceId);
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
          const userId = remapToUser ? options.targetUserId! : Number(row['user_id']);
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
          stats.importedResourceIds.push(resourceId);
          const tags = parseJsonTags(row['tags']);
          if (tags.length > 0) {
            setEntityTags(targetDb, userId, 'resource', resourceId, tags);
          }
          stats.links++;
        }
      }

      const wikiIdMap = new Map<number, number>();
      const wikiPathMap = new Map<number, string>();

      if (tableExists(v1Db, 'wiki_pages')) {
        const pages = v1Db
          .prepare('SELECT * FROM wiki_pages ORDER BY length(path) ASC, id ASC')
          .all() as Array<Record<string, unknown>>;

        if (remapToUser) {
          const slugExistsStmt = targetDb.prepare('SELECT 1 FROM wiki_pages WHERE user_id = ? AND slug = ?');
          const insertRemappedWiki = targetDb.prepare(`
            INSERT INTO wiki_pages (
              user_id, parent_id, path, slug, title, content, summary,
              sort_order, icon, index_status, revision_count, created_at, updated_at
            ) VALUES (?, ?, '/', ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
          `);
          const updateWikiPath = targetDb.prepare('UPDATE wiki_pages SET path = ? WHERE id = ?');

          for (const p of pages) {
            const oldId = Number(p['id']);
            const userId = options.targetUserId!;
            const oldParentId = p['parent_id'] !== null && p['parent_id'] !== undefined ? Number(p['parent_id']) : null;
            const newParentId = oldParentId !== null ? (wikiIdMap.get(oldParentId) ?? null) : null;

            const baseSlug = String(p['slug'] || 'untitled');
            let finalSlug = baseSlug;
            let suffix = 1;
            while (slugExistsStmt.get(userId, finalSlug)) {
              finalSlug = `${baseSlug}-imp-${suffix++}`;
            }

            const title = String(p['title']);
            const content = String(p['content'] || '');
            const r = insertRemappedWiki.run(
              userId,
              newParentId,
              finalSlug,
              title,
              content,
              String(p['summary'] || ''),
              Number(p['sort_order'] || 0),
              String(p['icon'] || ''),
              'pending',
              Number(p['revision_count'] || 1),
              p['created_at'] ? String(p['created_at']) : null,
              p['updated_at'] ? String(p['updated_at']) : null
            );
            const newPageId = Number(r.lastInsertRowid);
            const parentPath = newParentId ? (wikiPathMap.get(newParentId) || '/') : '/';
            const newPath = `${parentPath}${newPageId}/`;
            updateWikiPath.run(newPath, newPageId);

            wikiIdMap.set(oldId, newPageId);
            wikiPathMap.set(oldId, newPath);
            stats.importedWikiPageIds.push(newPageId);

            const tags = parseJsonTags(p['tags']);
            if (tags.length > 0) {
              setEntityTags(targetDb, userId, 'wiki', newPageId, tags);
            }
            syncPageToVault(userId, finalSlug, title, content);
            stats.wikiPages++;
          }
        } else {
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
            wikiIdMap.set(pageId, pageId);
            stats.importedWikiPageIds.push(pageId);
            const tags = parseJsonTags(p['tags']);
            if (tags.length > 0) {
              setEntityTags(targetDb, userId, 'wiki', pageId, tags);
            }
            stats.wikiPages++;
          }
        }
      }

      if (tableExists(v1Db, 'wiki_revisions')) {
        const revs = v1Db.prepare('SELECT * FROM wiki_revisions ORDER BY id ASC').all() as Array<Record<string, unknown>>;
        const insertRevDirect = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_revisions (id, page_id, user_id, rev_no, title, content, char_count, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        const insertRevAuto = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_revisions (page_id, user_id, rev_no, title, content, char_count, created_at)
          VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        for (const r of revs) {
          const oldPageId = Number(r['page_id']);
          const mappedPageId = remapToUser ? wikiIdMap.get(oldPageId) : oldPageId;
          if (!mappedPageId) continue;
          const userId = remapToUser ? options.targetUserId! : Number(r['user_id']);
          const res = remapToUser
            ? insertRevAuto.run(
                mappedPageId,
                userId,
                Number(r['rev_no']),
                String(r['title']),
                String(r['content'] || ''),
                Number(r['char_count'] || 0),
                r['created_at'] ? String(r['created_at']) : null
              )
            : insertRevDirect.run(
                Number(r['id']),
                mappedPageId,
                userId,
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
        const insertWLinkDirect = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_links (
            id, user_id, source_page_id, target_page_id, target_title, alias, link_type, section_anchor, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        const insertWLinkAuto = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_links (
            user_id, source_page_id, target_page_id, target_title, alias, link_type, section_anchor, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        for (const l of wLinks) {
          const oldSourceId = Number(l['source_page_id']);
          const mappedSourceId = remapToUser ? wikiIdMap.get(oldSourceId) : oldSourceId;
          if (!mappedSourceId) continue;
          const oldTargetId =
            l['target_page_id'] !== null && l['target_page_id'] !== undefined ? Number(l['target_page_id']) : null;
          const mappedTargetId =
            oldTargetId === null ? null : remapToUser ? (wikiIdMap.get(oldTargetId) ?? null) : oldTargetId;
          const userId = remapToUser ? options.targetUserId! : Number(l['user_id']);
          const res = remapToUser
            ? insertWLinkAuto.run(
                userId,
                mappedSourceId,
                mappedTargetId,
                String(l['target_title']),
                String(l['alias'] || ''),
                String(l['link_type'] || 'wikilink'),
                String(l['section_anchor'] || ''),
                l['created_at'] ? String(l['created_at']) : null
              )
            : insertWLinkDirect.run(
                Number(l['id']),
                userId,
                mappedSourceId,
                mappedTargetId,
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
        const insertAliasDirect = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_aliases (id, page_id, user_id, alias_title, created_at)
          VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        const insertAliasAuto = targetDb.prepare(`
          INSERT OR IGNORE INTO wiki_aliases (page_id, user_id, alias_title, created_at)
          VALUES (?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        `);
        for (const a of aliases) {
          const oldPageId = Number(a['page_id']);
          const mappedPageId = remapToUser ? wikiIdMap.get(oldPageId) : oldPageId;
          if (!mappedPageId) continue;
          const userId = remapToUser ? options.targetUserId! : Number(a['user_id']);
          const res = remapToUser
            ? insertAliasAuto.run(
                mappedPageId,
                userId,
                String(a['alias_title']),
                a['created_at'] ? String(a['created_at']) : null
              )
            : insertAliasDirect.run(
                Number(a['id']),
                mappedPageId,
                userId,
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
 * Enqueue background ingestion jobs for newly imported resources & wiki pages.
 */
export function enqueueImportedEntities(userId: number, userEmail: string, stats: ImportV1Stats): number {
  let enqueued = 0;
  for (const resourceId of stats.importedResourceIds) {
    enqueueJob({
      entity_type: 'resource',
      entity_id: resourceId,
      user_id: userId,
      user_email: userEmail,
      payload: { reason: 'legacy_v1_import' },
    });
    enqueued++;
  }
  for (const wikiPageId of stats.importedWikiPageIds) {
    enqueueJob({
      entity_type: 'wiki',
      entity_id: wikiPageId,
      user_id: userId,
      user_email: userEmail,
      payload: { reason: 'legacy_v1_import' },
    });
    enqueued++;
  }
  return enqueued;
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

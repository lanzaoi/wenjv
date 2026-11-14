import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { getDb } from '../db/index.js';
import { config } from '../config.js';
import { enqueueJob } from './jobs.js';
import { validateSafeUrl } from './ssrf.js';
import { deleteEntityChunks } from '../db/chunks.js';
import { getTextStore } from '../vector/text-store.js';
import { deleteAssetsByOwner } from './assets.js';
import { setEntityTags, getEntityTagsMap, getEntityTags, deleteEntityTags, normalizeTagNames } from './tags.js';

export type ResourceType = 'file' | 'note' | 'link';

export class ResourceValidationError extends Error {
  readonly status = 400;
  constructor(message: string) {
    super(message);
    this.name = 'ResourceValidationError';
  }
}

export interface ResourceRow {
  id: number;
  user_id: number;
  type: ResourceType;
  title: string;
  filename: string | null;
  original_filename: string | null;
  file_path: string | null;
  source_url: string | null;
  content_text: string | null;
  content_type: string | null;
  favicon: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface ResourceRecord extends ResourceRow {
  tags: string[];
}

function hydrateResource(row: ResourceRow): ResourceRecord {
  const db = getDb();
  return {
    ...row,
    tags: getEntityTags(db, row.user_id, 'resource', row.id),
  };
}

function hydrateResources(userId: number, rows: ResourceRow[]): ResourceRecord[] {
  if (rows.length === 0) return [];
  const db = getDb();
  const tagMap = getEntityTagsMap(
    db,
    userId,
    'resource',
    rows.map((r) => r.id)
  );
  return rows.map((r) => ({
    ...r,
    tags: tagMap.get(r.id) || [],
  }));
}

export function saveUploadFile(params: {
  userId: number;
  userEmail: string;
  originalFilename: string;
  content: Buffer;
  contentType?: string;
  tags?: string[];
}): ResourceRecord {
  const db = getDb();
  const ext = path.extname(params.originalFilename).toLowerCase().replace('.', '');
  const baseExt = ext ? `.${ext}` : '';
  const safeName = path.basename(params.originalFilename, baseExt).replace(/[^a-zA-Z0-9_\-\u4e00-\u9fff]/g, '_');
  const uniqueId = crypto.randomUUID().slice(0, 8);
  const storedFilename = `${safeName}-${uniqueId}${baseExt}`;

  const uploadDir = config.resolvedUploadDir;
  if (!fs.existsSync(uploadDir)) {
    fs.mkdirSync(uploadDir, { recursive: true });
  }

  const filePath = path.join(uploadDir, storedFilename);
  fs.writeFileSync(filePath, params.content);

  let resourceId: number;
  try {
    const res = db
      .prepare(`
        INSERT INTO resources(
          user_id, type, title, filename, original_filename, file_path, content_type, status
        )
        VALUES (?, 'file', ?, ?, ?, ?, ?, 'pending')
      `)
      .run(
        params.userId,
        params.originalFilename,
        storedFilename,
        params.originalFilename,
        filePath,
        params.contentType || 'application/octet-stream'
      );

    resourceId = Number(res.lastInsertRowid);
    if (params.tags && params.tags.length > 0) {
      setEntityTags(db, params.userId, 'resource', resourceId, params.tags);
    }
  } catch (err) {
    try {
      if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
    } catch {
      // ignore cleanup error
    }
    throw err;
  }

  enqueueJob({
    entity_type: 'resource',
    entity_id: resourceId,
    user_id: params.userId,
    user_email: params.userEmail,
  });

  return getResource(params.userId, resourceId)!;
}

export function saveUserNote(params: {
  userId: number;
  userEmail: string;
  title: string;
  content: string;
  tags?: string[];
}): ResourceRecord {
  const db = getDb();
  const cleanTitle = (params.title || 'Untitled Note').trim() || 'Untitled Note';
  const safeTitle = cleanTitle.replace(/[^a-zA-Z0-9_\-\u4e00-\u9fff]/g, '_').slice(0, 100);
  const noteUid = crypto.randomUUID().slice(0, 8);
  const filename = `${safeTitle}-${noteUid}.md`;

  const uploadDir = config.resolvedUploadDir;
  if (!fs.existsSync(uploadDir)) {
    fs.mkdirSync(uploadDir, { recursive: true });
  }

  const filePath = path.join(uploadDir, filename);
  fs.writeFileSync(filePath, params.content, 'utf8');

  const res = db
    .prepare(`
      INSERT INTO resources(
        user_id, type, title, filename, file_path, content_text, content_type, status
      )
      VALUES (?, 'note', ?, ?, ?, ?, 'text/markdown', 'pending')
    `)
    .run(params.userId, cleanTitle, filename, filePath, params.content);

  const resourceId = Number(res.lastInsertRowid);
  if (params.tags && params.tags.length > 0) {
    setEntityTags(db, params.userId, 'resource', resourceId, params.tags);
  }

  enqueueJob({
    entity_type: 'resource',
    entity_id: resourceId,
    user_id: params.userId,
    user_email: params.userEmail,
  });

  return getResource(params.userId, resourceId)!;
}

export async function submitLink(params: {
  userId: number;
  userEmail: string;
  url: string;
  tags?: string[];
}): Promise<ResourceRecord> {
  const safeUrl = await validateSafeUrl(params.url);
  const db = getDb();

  const res = db
    .prepare(`
      INSERT INTO resources(
        user_id, type, title, source_url, content_type, status
      )
      VALUES (?, 'link', ?, ?, 'text/html', 'pending')
    `)
    .run(params.userId, safeUrl, safeUrl);

  const resourceId = Number(res.lastInsertRowid);
  if (params.tags && params.tags.length > 0) {
    setEntityTags(db, params.userId, 'resource', resourceId, params.tags);
  }

  enqueueJob({
    entity_type: 'resource',
    entity_id: resourceId,
    user_id: params.userId,
    user_email: params.userEmail,
  });

  return getResource(params.userId, resourceId)!;
}

export function listUserResources(
  userId: number,
  options: { type?: ResourceType | undefined; tag?: string | undefined; skip?: number | undefined; limit?: number | undefined } = {}
): { resources: ResourceRecord[]; total: number } {
  const db = getDb();
  const skip = Math.max(0, options.skip ?? 0);
  const limit = Math.min(200, Math.max(1, options.limit ?? 100));

  const whereParts: string[] = ['r.user_id = ?'];
  const params: (string | number)[] = [userId];
  let joinClause = '';

  if (options.type) {
    whereParts.push('r.type = ?');
    params.push(options.type);
  }
  if (options.tag) {
    const cleanTag = normalizeTagNames([options.tag])[0];
    if (cleanTag) {
      joinClause = `
        JOIN entity_tags et ON et.entity_type = 'resource' AND et.entity_id = r.id AND et.user_id = r.user_id
        JOIN tags t ON t.id = et.tag_id
      `;
      whereParts.push('t.name = ?');
      params.push(cleanTag);
    }
  }

  const whereSql = whereParts.join(' AND ');
  const countRow = db
    .prepare(`SELECT COUNT(DISTINCT r.id) AS total FROM resources r ${joinClause} WHERE ${whereSql}`)
    .get(...params) as { total: number };

  const rows = db
    .prepare(
      `SELECT DISTINCT r.* FROM resources r ${joinClause} WHERE ${whereSql} ORDER BY r.id DESC LIMIT ? OFFSET ?`
    )
    .all(...params, limit, skip) as ResourceRow[];

  return {
    resources: hydrateResources(userId, rows),
    total: Number(countRow.total || 0),
  };
}

export function getResource(userId: number, idOrFilename: number | string): ResourceRecord | null {
  const db = getDb();
  if (typeof idOrFilename === 'number' || /^\d+$/.test(String(idOrFilename))) {
    const row = db
      .prepare('SELECT * FROM resources WHERE id = ? AND user_id = ?')
      .get(Number(idOrFilename), userId) as ResourceRow | undefined;
    if (row) return hydrateResource(row);
  }

  const byName = db
    .prepare('SELECT * FROM resources WHERE filename = ? AND user_id = ?')
    .get(String(idOrFilename), userId) as ResourceRow | undefined;
  return byName ? hydrateResource(byName) : null;
}

export function updateResource(
  userId: number,
  userEmail: string,
  idOrFilename: number | string,
  patch: { title?: string | undefined; content?: string | undefined; tags?: string[] | undefined }
): ResourceRecord | null {
  const current = getResource(userId, idOrFilename);
  if (!current) return null;

  if (patch.content !== undefined && current.type !== 'note') {
    throw new ResourceValidationError('Only note resources support content updates');
  }

  const db = getDb();
  const nextTitle = patch.title !== undefined ? patch.title.trim() || current.title : current.title;
  const contentChanged = typeof patch.content === 'string' && patch.content !== current.content_text;

  if (typeof patch.content === 'string' && current.type === 'note') {
    if (current.file_path) {
      const dir = path.dirname(current.file_path);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(current.file_path, patch.content, 'utf8');
    }
    db.prepare(`
      UPDATE resources
      SET title = ?, content_text = ?, status = 'pending', updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND user_id = ?
    `).run(nextTitle, patch.content, current.id, userId);

    enqueueJob({
      entity_type: 'resource',
      entity_id: current.id,
      user_id: userId,
      user_email: userEmail,
    });
  } else if (patch.title !== undefined) {
    db.prepare('UPDATE resources SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?').run(
      nextTitle,
      current.id,
      userId
    );
  }

  if (patch.tags !== undefined) {
    setEntityTags(db, userId, 'resource', current.id, patch.tags);
  } else if (contentChanged && current.type === 'note') {
    // Re-index handles chunk updates automatically via enqueued job
  }

  return getResource(userId, current.id);
}

export function syncUserNotes(userId: number, userEmail: string): number {
  const { resources } = listUserResources(userId, { type: 'note', limit: 200 });
  for (const n of resources) {
    enqueueJob({
      entity_type: 'resource',
      entity_id: n.id,
      user_id: userId,
      user_email: userEmail,
    });
  }
  return resources.length;
}

export async function deleteUserResource(userId: number, idOrFilename: number | string): Promise<boolean> {
  const current = getResource(userId, idOrFilename);
  if (!current) return false;

  const db = getDb();
  if (current.file_path && fs.existsSync(current.file_path)) {
    try {
      fs.unlinkSync(current.file_path);
    } catch {
      // ignore disk file already missing
    }
  }

  deleteEntityChunks(db, 'resource', current.id, userId);
  deleteEntityTags(db, userId, 'resource', current.id);
  db.prepare('DELETE FROM ingestion_jobs WHERE entity_type = ? AND entity_id = ? AND user_id = ?').run(
    'resource',
    current.id,
    userId
  );
  db.prepare('DELETE FROM resources WHERE id = ? AND user_id = ?').run(current.id, userId);

  const textStore = getTextStore();
  await textStore.deleteByEntity('resource', current.id, userId);
  await deleteAssetsByOwner(userId, 'resource', current.id);

  return true;
}

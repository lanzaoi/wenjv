import { getDb } from '../db/index.js';
import { enqueueJob } from './jobs.js';
import { validateSafeUrl } from './ssrf.js';
import { deleteByResourceId } from '../db/fts5.js';
import { getDocumentStore } from '../vector/document-store.js';

export interface LinkRecord {
  id: number;
  url: string;
  title: string;
  favicon: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string | null;
  user_id: number;
  tags: string;
}

export async function submitLink(params: {
  userId: number;
  userEmail: string;
  url: string;
  tags?: string[];
}): Promise<LinkRecord> {
  const safeUrl = await validateSafeUrl(params.url);
  const db = getDb();
  const tagsJson = JSON.stringify(params.tags || []);

  const res = db
    .prepare(`
      INSERT INTO links(url, title, status, user_id, tags)
      VALUES (?, ?, 'pending', ?, ?)
    `)
    .run(safeUrl, safeUrl, params.userId, tagsJson);

  const linkId = Number(res.lastInsertRowid);
  enqueueJob({
    job_type: 'link',
    resource_id: linkId,
    user_id: params.userId,
    user_email: params.userEmail,
  });

  return db.prepare('SELECT * FROM links WHERE id = ?').get(linkId) as LinkRecord;
}

export function listUserLinks(userId: number): LinkRecord[] {
  const db = getDb();
  return db.prepare('SELECT * FROM links WHERE user_id = ? ORDER BY id DESC').all(userId) as LinkRecord[];
}

export async function deleteUserLink(userId: number, linkId: number): Promise<boolean> {
  const db = getDb();
  const link = db.prepare('SELECT * FROM links WHERE id = ? AND user_id = ?').get(linkId, userId) as LinkRecord | undefined;
  if (!link) return false;

  db.prepare('DELETE FROM links WHERE id = ?').run(linkId);
  deleteByResourceId(db, String(linkId), String(userId));

  const docStore = getDocumentStore();
  await docStore.deleteByResourceId(String(linkId), userId);
  await docStore.deleteByLinkId(String(linkId));

  return true;
}

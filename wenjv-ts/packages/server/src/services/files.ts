import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { getDb } from '../db/index.js';
import { config } from '../config.js';
import { enqueueJob } from './jobs.js';
import { deleteByResourceId, deleteByFilename } from '../db/fts5.js';
import { getDocumentStore } from '../vector/document-store.js';

export interface FileUploadRecord {
  id: number;
  filename: string;
  original_filename: string;
  file_path: string;
  file_url: string;
  status: string;
  content_type: string;
  error_message: string | null;
  created_at: string;
  updated_at: string | null;
  user_id: number;
  tags: string;
}

export interface NoteRecord {
  id: number;
  url: string;
  title: string;
  filename: string;
  file_path: string;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string | null;
  user_id: number;
  tags: string;
}

export function saveUploadFile(params: {
  userId: number;
  userEmail: string;
  originalFilename: string;
  content: Buffer;
  contentType?: string;
  tags?: string[];
}): FileUploadRecord {
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

  const tagsJson = JSON.stringify(params.tags || []);
  const fileUrl = `/file/${storedFilename}`;

  const res = db
    .prepare(`
      INSERT INTO file_uploads(
        filename, original_filename, file_path, file_url, status,
        content_type, user_id, tags
      )
      VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
    `)
    .run(
      storedFilename,
      params.originalFilename,
      filePath,
      fileUrl,
      params.contentType || 'application/octet-stream',
      params.userId,
      tagsJson
    );

  const fileId = Number(res.lastInsertRowid);
  enqueueJob({
    job_type: 'file',
    resource_id: fileId,
    user_id: params.userId,
    user_email: params.userEmail,
  });

  return db.prepare('SELECT * FROM file_uploads WHERE id = ?').get(fileId) as FileUploadRecord;
}

export function listUserFiles(userId: number): FileUploadRecord[] {
  const db = getDb();
  return db.prepare('SELECT * FROM file_uploads WHERE user_id = ? ORDER BY id DESC').all(userId) as FileUploadRecord[];
}

export function getFileRecord(userId: number, fileIdOrName: number | string): FileUploadRecord | null {
  const db = getDb();
  if (typeof fileIdOrName === 'number' || /^\d+$/.test(String(fileIdOrName))) {
    const row = db
      .prepare('SELECT * FROM file_uploads WHERE id = ? AND user_id = ?')
      .get(Number(fileIdOrName), userId) as FileUploadRecord | undefined;
    if (row) return row;
  }
  return (
    (db.prepare('SELECT * FROM file_uploads WHERE filename = ? AND user_id = ?').get(String(fileIdOrName), userId) as FileUploadRecord) ||
    null
  );
}

export async function deleteUserFile(userId: number, fileIdOrName: number | string): Promise<boolean> {
  const file = getFileRecord(userId, fileIdOrName);
  if (!file) return false;

  const db = getDb();
  if (file.file_path && fs.existsSync(file.file_path)) {
    try {
      fs.unlinkSync(file.file_path);
    } catch {
      // ignore
    }
  }

  db.prepare('DELETE FROM file_uploads WHERE id = ?').run(file.id);
  deleteByResourceId(db, String(file.id), String(userId));
  deleteByFilename(db, file.filename);

  const docStore = getDocumentStore();
  await docStore.deleteByResourceId(String(file.id), userId);
  await docStore.deleteByFilename(file.filename);

  return true;
}

export function saveUserNote(params: {
  userId: number;
  userEmail: string;
  title: string;
  content: string;
  tags?: string[];
}): NoteRecord {
  const db = getDb();
  const safeTitle = (params.title || 'Note').replace(/[^a-zA-Z0-9_\-\u4e00-\u9fff]/g, '_').slice(0, 100);
  const noteId = crypto.randomUUID().slice(0, 8);
  const filename = `${safeTitle}-${noteId}.md`;

  const uploadDir = config.resolvedUploadDir;
  if (!fs.existsSync(uploadDir)) {
    fs.mkdirSync(uploadDir, { recursive: true });
  }

  const filePath = path.join(uploadDir, filename);
  fs.writeFileSync(filePath, params.content, 'utf8');

  const tagsJson = JSON.stringify(params.tags || []);
  const res = db
    .prepare(`
      INSERT INTO notes(url, title, filename, file_path, status, user_id, tags)
      VALUES (?, ?, ?, ?, 'pending', ?, ?)
    `)
    .run(params.content, params.title, filename, filePath, params.userId, tagsJson);

  const newId = Number(res.lastInsertRowid);
  enqueueJob({
    job_type: 'note',
    resource_id: newId,
    user_id: params.userId,
    user_email: params.userEmail,
  });

  return db.prepare('SELECT * FROM notes WHERE id = ?').get(newId) as NoteRecord;
}

export function listUserNotes(userId: number): NoteRecord[] {
  const db = getDb();
  return db.prepare('SELECT * FROM notes WHERE user_id = ? ORDER BY id DESC').all(userId) as NoteRecord[];
}

export function getNoteRecord(userId: number, noteIdOrName: number | string): NoteRecord | null {
  const db = getDb();
  if (typeof noteIdOrName === 'number' || /^\d+$/.test(String(noteIdOrName))) {
    const idNum = Number(noteIdOrName);
    const byId = db.prepare('SELECT * FROM notes WHERE id = ? AND user_id = ?').get(idNum, userId) as NoteRecord | undefined;
    if (byId) return byId;
  }
  return (db.prepare('SELECT * FROM notes WHERE filename = ? AND user_id = ?').get(String(noteIdOrName), userId) as NoteRecord) || null;
}

export async function deleteUserNote(userId: number, noteIdOrName: number | string): Promise<boolean> {
  const note = getNoteRecord(userId, noteIdOrName);
  if (!note) return false;

  const db = getDb();
  if (note.file_path && fs.existsSync(note.file_path)) {
    try {
      fs.unlinkSync(note.file_path);
    } catch {
      // ignore
    }
  }

  db.prepare('DELETE FROM notes WHERE id = ?').run(note.id);
  deleteByResourceId(db, String(note.id), String(userId));
  deleteByFilename(db, note.filename);

  const docStore = getDocumentStore();
  await docStore.deleteByResourceId(String(note.id), userId);
  await docStore.deleteByFilename(note.filename);

  return true;
}

export function updateUserNote(
  userId: number,
  userEmail: string,
  noteIdOrName: number | string,
  content: string
): NoteRecord | null {
  const note = getNoteRecord(userId, noteIdOrName);
  if (!note) return null;

  if (note.file_path) {
    const dir = path.dirname(note.file_path);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(note.file_path, content, 'utf8');
  }

  const db = getDb();
  db.prepare('UPDATE notes SET url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(content, note.id);

  enqueueJob({
    job_type: 'note',
    resource_id: note.id,
    user_id: userId,
    user_email: userEmail,
  });

  return getNoteRecord(userId, note.id);
}

export function syncUserNotes(userId: number, userEmail: string): number {
  const notes = listUserNotes(userId);
  for (const n of notes) {
    enqueueJob({
      job_type: 'note',
      resource_id: n.id,
      user_id: userId,
      user_email: userEmail,
    });
  }
  return notes.length;
}

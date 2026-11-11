import fs from 'node:fs';
import path from 'node:path';
import { Hono } from 'hono';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { config } from '../config.js';
import {
  saveUploadFile,
  listUserFiles,
  deleteUserFile,
  saveUserNote,
  listUserNotes,
  getNoteRecord,
  getFileRecord,
  deleteUserNote,
  updateUserNote,
  syncUserNotes,
} from '../services/files.js';

export const filesRouter = new Hono();

// POST /file/upload
filesRouter.post('/upload', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const body = await c.req.parseBody();

  const fileEntries: File[] = [];
  for (const [key, val] of Object.entries(body)) {
    if (val instanceof File) {
      fileEntries.push(val);
    }
  }

  if (fileEntries.length === 0) {
    return c.json({ detail: 'No file uploaded' }, 400);
  }

  const results = [];
  for (const f of fileEntries) {
    const ext = path.extname(f.name).toLowerCase().replace('.', '');
    if (!config.ALLOWED_UPLOAD_EXTENSIONS.includes(ext)) {
      return c.json({ detail: `File type .${ext} not allowed` }, 400);
    }

    const arrayBuf = await f.arrayBuffer();
    const buffer = Buffer.from(arrayBuf);
    if (buffer.length > config.MAX_UPLOAD_BYTES) {
      return c.json({ detail: `File size exceeds limit of ${config.MAX_UPLOAD_BYTES} bytes` }, 400);
    }

    const record = saveUploadFile({
      userId: user.id,
      userEmail: user.email,
      originalFilename: f.name,
      content: buffer,
      contentType: f.type,
    });
    results.push(record);
  }

  return c.json(results.length === 1 ? results[0] : results, 201);
});

// GET /file/
filesRouter.get('/', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const files = listUserFiles(user.id);
  return c.json({
    files,
    total: files.length,
  });
});

// GET /file/status/:filename
filesRouter.get('/status/:filename', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const filename = c.req.param('filename') || '';
  const file = getFileRecord(user.id, filename);
  if (!file) {
    return c.json({ detail: 'File not found' }, 404);
  }
  return c.json({
    status: file.status,
    error_message: file.error_message,
  });
});

// DELETE /file/:id
filesRouter.delete('/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const idOrName = c.req.param('id') || '';
  const ok = await deleteUserFile(user.id, idOrName);
  if (!ok) {
    return c.json({ detail: 'File not found' }, 404);
  }
  return c.json({ status: 'deleted' });
});

// POST /file/note
filesRouter.post('/note', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();
  const title = String(json.title || 'Untitled Note');
  const content = String(json.content || '');
  const tags = Array.isArray(json.tags) ? json.tags : [];

  const record = saveUserNote({
    userId: user.id,
    userEmail: user.email,
    title,
    content,
    tags,
  });

  return c.json(record, 201);
});

// GET /file/note
filesRouter.get('/note', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const notes = listUserNotes(user.id);
  return c.json({
    notes,
    total: notes.length,
  });
});

// PUT /file/note/sync
filesRouter.put('/note/sync', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const count = syncUserNotes(user.id, user.email);
  return c.json({
    count,
    updated: true,
  });
});

// GET /file/note/:filename
filesRouter.get('/note/:filename', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const filename = c.req.param('filename') || '';
  const note = getNoteRecord(user.id, filename);
  if (!note) {
    return c.json({ detail: 'Note not found' }, 404);
  }

  let content = note.url;
  if (note.file_path && fs.existsSync(note.file_path)) {
    content = fs.readFileSync(note.file_path, 'utf8');
  }

  return c.json({
    ...note,
    content,
  });
});

// PATCH /file/note/:filename
filesRouter.patch('/note/:filename', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const filename = c.req.param('filename') || '';
  const json = await c.req.json();
  const content = typeof json.content === 'string' ? json.content : '';

  const updated = updateUserNote(user.id, user.email, filename, content);
  if (!updated) {
    return c.json({ detail: 'Note not found' }, 404);
  }
  return c.json({
    filename: updated.filename,
    updated: true,
  });
});

// DELETE /file/note/:filename
filesRouter.delete('/note/:filename', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const filename = c.req.param('filename') || '';
  const ok = await deleteUserNote(user.id, filename);
  if (!ok) {
    return c.json({ detail: 'Note not found' }, 404);
  }
  return c.json({ status: 'deleted' });
});

// GET /file/:filename
filesRouter.get('/:filename', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const filename = c.req.param('filename') || '';
  const file = getFileRecord(user.id, filename);
  if (!file) {
    return c.json({ detail: 'File not found' }, 404);
  }

  const filePath = file.file_path || path.join(config.resolvedUploadDir, filename);
  if (!fs.existsSync(filePath)) {
    return c.json({ detail: 'File not found on disk' }, 404);
  }

  const buffer = fs.readFileSync(filePath);
  return c.body(buffer, 200, {
    'Content-Type': file.content_type || 'application/octet-stream',
    'Content-Disposition': `inline; filename="${encodeURIComponent(file.original_filename)}"`,
  });
});

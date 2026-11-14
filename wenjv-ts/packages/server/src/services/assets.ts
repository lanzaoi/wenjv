import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import type Database from 'better-sqlite3';
import { getDb } from '../db/index.js';
import { config } from '../config.js';
import { SigLIP2Engine } from '../ai/siglip2.js';
import { getVisualStore, type AssetOwnerType } from '../vector/visual-store.js';

export interface AssetRecord {
  id: string;
  user_id: number;
  owner_type: AssetOwnerType;
  owner_id: string;
  filename: string;
  file_path: string;
  mime_type: string;
  size: number;
  caption: string;
  created_at: string;
}

export class AssetSecurityError extends Error {
  readonly status = 403;
  constructor(message: string) {
    super(message);
    this.name = 'AssetSecurityError';
  }
}

/**
 * Resolve a relative asset path inside `resolvedUploadDir` with path traversal
 * and symlink escape verification.
 */
export function resolveSafeUploadPath(relOrAbsPath: string): { absPath: string; relPath: string } {
  const uploadRoot = path.resolve(config.resolvedUploadDir);
  if (!fs.existsSync(uploadRoot)) {
    fs.mkdirSync(uploadRoot, { recursive: true });
  }
  const realRoot = fs.realpathSync(uploadRoot);

  const trimmed = String(relOrAbsPath || '').trim();
  const absCandidate = path.isAbsolute(trimmed)
    ? path.resolve(trimmed)
    : path.resolve(uploadRoot, trimmed.replace(/^\/+/, ''));

  if (!absCandidate.startsWith(uploadRoot + path.sep) && absCandidate !== uploadRoot) {
    throw new AssetSecurityError('Access denied: asset path outside upload directory');
  }

  if (fs.existsSync(absCandidate)) {
    const stat = fs.lstatSync(absCandidate);
    if (stat.isSymbolicLink()) {
      throw new AssetSecurityError('Access denied: symlink escape blocked');
    }
    const realTarget = fs.realpathSync(absCandidate);
    if (!realTarget.startsWith(realRoot + path.sep) && realTarget !== realRoot) {
      throw new AssetSecurityError('Access denied: realpath escape blocked');
    }
  }

  const relPath = path.relative(uploadRoot, absCandidate).replace(/\\/g, '/');
  return { absPath: absCandidate, relPath };
}

/** Register an asset in SQLite `assets` (and optionally index visual embedding in `visual_vectors`). */
export async function registerAsset(params: {
  id?: string;
  userId: number;
  ownerType: AssetOwnerType;
  ownerId: string | number;
  filename: string;
  relPath: string;
  absPath: string;
  mimeType: string;
  size: number;
  caption?: string;
  bytesForVisualIndex?: Buffer | undefined;
}): Promise<AssetRecord> {
  const db = getDb();
  const assetId = params.id || crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  const ownerIdStr = String(params.ownerId);

  db.prepare(`
    INSERT INTO assets(id, user_id, owner_type, owner_id, filename, file_path, mime_type, size, caption)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      filename = excluded.filename,
      file_path = excluded.file_path,
      mime_type = excluded.mime_type,
      size = excluded.size,
      caption = excluded.caption
  `).run(
    assetId,
    params.userId,
    params.ownerType,
    ownerIdStr,
    params.filename,
    params.relPath,
    params.mimeType,
    params.size,
    params.caption || ''
  );

  if (params.bytesForVisualIndex) {
    try {
      const siglip = new SigLIP2Engine();
      const vec = await siglip.embedImage(params.bytesForVisualIndex);
      const vStore = getVisualStore();
      await vStore.addVectors([
        {
          id: assetId,
          vector: vec,
          user_id: String(params.userId),
          owner_type: params.ownerType,
          owner_id: ownerIdStr,
        },
      ]);
    } catch {
      // Visual model optional in minimal/offline environments; DB asset record still persists cleanly
    }
  }

  return db.prepare('SELECT * FROM assets WHERE id = ?').get(assetId) as AssetRecord;
}

export function getAssetsByIds(db: Database.Database, ids: string[], userId: number): Map<string, AssetRecord> {
  const map = new Map<string, AssetRecord>();
  if (ids.length === 0) return map;

  const unique = Array.from(new Set(ids));
  const marks = unique.map(() => '?').join(',');
  const rows = db
    .prepare(`SELECT * FROM assets WHERE id IN (${marks}) AND user_id = ?`)
    .all(...unique, userId) as AssetRecord[];
  for (const r of rows) {
    map.set(r.id, r);
  }
  return map;
}

/** Resolve an image asset for serving, enforcing tenant ownership and traversal boundaries. */
export function resolveAuthorizedAsset(
  userId: number,
  query: { id?: string | undefined; path?: string | undefined }
): { absPath: string; mimeType: string; asset?: AssetRecord } | null {
  const db = getDb();

  if (query.id) {
    const asset = db.prepare('SELECT * FROM assets WHERE id = ?').get(query.id) as AssetRecord | undefined;
    if (!asset) return null;
    if (asset.user_id !== userId) {
      throw new AssetSecurityError('Access denied: cannot access another user asset');
    }
    const { absPath } = resolveSafeUploadPath(asset.file_path);
    if (!fs.existsSync(absPath) || !fs.statSync(absPath).isFile()) return null;
    return { absPath, mimeType: asset.mime_type, asset };
  }

  if (query.path) {
    const { absPath, relPath } = resolveSafeUploadPath(query.path);
    const asset = db.prepare('SELECT * FROM assets WHERE file_path = ? OR file_path = ?').get(relPath, query.path) as
      | AssetRecord
      | undefined;
    if (!asset) {
      return null;
    }
    if (asset.user_id !== userId) {
      throw new AssetSecurityError('Access denied: cannot access another user asset');
    }

    const parts = relPath.split('/');
    if (parts.length >= 3 && parts[0] === 'mm_assets' && parts[1] === 'sessions' && parts[2] !== String(userId)) {
      throw new AssetSecurityError("Access denied: cannot access another user's session asset");
    }

    if (!fs.existsSync(absPath) || !fs.statSync(absPath).isFile()) return null;

    const ext = path.extname(absPath).toLowerCase();
    const mimeTypes: Record<string, string> = {
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.webp': 'image/webp',
    };
    const mimeType = asset.mime_type || mimeTypes[ext] || '';
    if (!mimeType) return null;

    return { absPath, mimeType, asset };
  }

  return null;
}

export async function deleteAssetById(userId: number, assetId: string): Promise<boolean> {
  const db = getDb();
  const row = db.prepare('SELECT * FROM assets WHERE id = ? AND user_id = ?').get(assetId, userId) as
    | AssetRecord
    | undefined;
  if (!row) return false;

  try {
    const { absPath } = resolveSafeUploadPath(row.file_path);
    if (fs.existsSync(absPath)) fs.unlinkSync(absPath);
  } catch {
    // ignore missing/unreadable disk artifact during delete
  }

  db.prepare('DELETE FROM assets WHERE id = ? AND user_id = ?').run(assetId, userId);
  const vStore = getVisualStore();
  await vStore.deleteById(assetId, userId);
  return true;
}

export async function deleteAssetsByOwner(
  userId: number,
  ownerType: AssetOwnerType,
  ownerId: string | number
): Promise<void> {
  const db = getDb();
  const ownerStr = String(ownerId);
  const rows = db
    .prepare('SELECT * FROM assets WHERE user_id = ? AND owner_type = ? AND owner_id = ?')
    .all(userId, ownerType, ownerStr) as AssetRecord[];

  for (const r of rows) {
    try {
      const { absPath } = resolveSafeUploadPath(r.file_path);
      if (fs.existsSync(absPath)) fs.unlinkSync(absPath);
    } catch {
      // ignore missing/unreadable file during cascade delete
    }
  }

  db.prepare('DELETE FROM assets WHERE user_id = ? AND owner_type = ? AND owner_id = ?').run(
    userId,
    ownerType,
    ownerStr
  );
  const vStore = getVisualStore();
  await vStore.deleteByOwner(ownerType, ownerStr, userId);
}

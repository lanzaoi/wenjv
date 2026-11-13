import type Database from 'better-sqlite3';

export type ChunkEntityType = 'resource' | 'wiki';
export type ChunkResourceType = 'file' | 'note' | 'link' | 'wiki';

export interface ChunkRow {
  id: string;
  user_id: number;
  entity_type: ChunkEntityType;
  entity_id: number;
  resource_type: ChunkResourceType;
  chunk_order: number;
  page_number: number;
  header_path: string;
  title: string;
  source: string;
  content: string;
  created_at?: string;
}

export interface ChunkInsertInput {
  id: string;
  user_id: number;
  entity_type: ChunkEntityType;
  entity_id: number;
  resource_type: ChunkResourceType;
  chunk_order: number;
  page_number?: number;
  header_path?: string;
  title: string;
  source: string;
  content: string;
}

/**
 * Replace all chunks for an entity inside a transaction.
 * FTS5 sync triggers on `chunks` automatically keep `chunks_fts` in sync.
 */
export function replaceEntityChunks(
  db: Database.Database,
  userId: number,
  entityType: ChunkEntityType,
  entityId: number,
  rows: ChunkInsertInput[]
): void {
  const delStmt = db.prepare('DELETE FROM chunks WHERE entity_type = ? AND entity_id = ? AND user_id = ?');
  const insStmt = db.prepare(`
    INSERT INTO chunks(
      id, user_id, entity_type, entity_id, resource_type,
      chunk_order, page_number, header_path, title, source, content
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const runTx = db.transaction((items: ChunkInsertInput[]) => {
    delStmt.run(entityType, entityId, userId);
    for (const r of items) {
      insStmt.run(
        r.id,
        r.user_id,
        r.entity_type,
        r.entity_id,
        r.resource_type,
        r.chunk_order,
        r.page_number ?? 1,
        r.header_path || '',
        r.title || '',
        r.source || '',
        r.content || ''
      );
    }
  });

  runTx(rows);
}

/** Delete all chunks owned by an entity (triggers clean `chunks_fts` automatically). */
export function deleteEntityChunks(
  db: Database.Database,
  entityType: ChunkEntityType,
  entityId: number,
  userId?: number
): void {
  if (userId !== undefined) {
    db.prepare('DELETE FROM chunks WHERE entity_type = ? AND entity_id = ? AND user_id = ?').run(
      entityType,
      entityId,
      userId
    );
  } else {
    db.prepare('DELETE FROM chunks WHERE entity_type = ? AND entity_id = ?').run(entityType, entityId);
  }
}

/** Batch hydrate authoritative chunk rows by primary keys. */
export function getChunksByIds(db: Database.Database, ids: string[], userId?: number): Map<string, ChunkRow> {
  const map = new Map<string, ChunkRow>();
  if (ids.length === 0) return map;

  const unique = Array.from(new Set(ids));
  const inMarks = unique.map(() => '?').join(',');
  const sql =
    userId !== undefined
      ? `SELECT * FROM chunks WHERE id IN (${inMarks}) AND user_id = ?`
      : `SELECT * FROM chunks WHERE id IN (${inMarks})`;
  const params = userId !== undefined ? [...unique, userId] : unique;

  const rows = db.prepare(sql).all(...params) as ChunkRow[];
  for (const row of rows) {
    map.set(row.id, row);
  }
  return map;
}

/**
 * Small-to-Large helper: look up immediate neighbor chunks (chunk_order +/- 1)
 * using the composite entity index on `chunks`.
 */
export function getNeighborChunks(
  db: Database.Database,
  userId: number,
  entityType: ChunkEntityType,
  entityId: number,
  chunkOrder: number,
  radius = 1
): ChunkRow[] {
  return db
    .prepare(
      `SELECT * FROM chunks
       WHERE user_id = ? AND entity_type = ? AND entity_id = ?
         AND chunk_order BETWEEN ? AND ?
       ORDER BY chunk_order ASC`
    )
    .all(userId, entityType, entityId, Math.max(0, chunkOrder - radius), chunkOrder + radius) as ChunkRow[];
}

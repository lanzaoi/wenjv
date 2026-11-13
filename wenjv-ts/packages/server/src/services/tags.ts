import type Database from 'better-sqlite3';
import { getDb } from '../db/index.js';
import type { ChunkEntityType } from '../db/chunks.js';

export interface TagRecord {
  id: number;
  name: string;
  color: string;
  count: number;
  tag: string;
}

export interface EntityRef {
  entity_type: ChunkEntityType;
  entity_id: number;
}

export function normalizeTagNames(tags: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of tags) {
    const clean = String(raw || '').trim().replace(/^#+/, '').slice(0, 64);
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out;
}

/** Replace all tag associations for an entity atomically using normalized `tags` + `entity_tags`. */
export function setEntityTags(
  db: Database.Database,
  userId: number,
  entityType: ChunkEntityType,
  entityId: number,
  tagNames: string[]
): string[] {
  const cleanTags = normalizeTagNames(tagNames);

  const tx = db.transaction(() => {
    db.prepare('DELETE FROM entity_tags WHERE user_id = ? AND entity_type = ? AND entity_id = ?').run(
      userId,
      entityType,
      entityId
    );

    if (cleanTags.length === 0) return;

    const upsertTag = db.prepare(`
      INSERT INTO tags(user_id, name, color)
      VALUES (?, ?, '')
      ON CONFLICT(user_id, name) DO NOTHING
    `);
    const findTag = db.prepare('SELECT id FROM tags WHERE user_id = ? AND name = ?');
    const insertAssoc = db.prepare(`
      INSERT OR IGNORE INTO entity_tags(tag_id, user_id, entity_type, entity_id)
      VALUES (?, ?, ?, ?)
    `);

    for (const name of cleanTags) {
      upsertTag.run(userId, name);
      const row = findTag.get(userId, name) as { id: number } | undefined;
      if (row) {
        insertAssoc.run(row.id, userId, entityType, entityId);
      }
    }
  });

  tx();
  return cleanTags;
}

/** Delete all tag associations belonging to a deleted entity. */
export function deleteEntityTags(
  db: Database.Database,
  userId: number,
  entityType: ChunkEntityType,
  entityId: number
): void {
  db.prepare('DELETE FROM entity_tags WHERE user_id = ? AND entity_type = ? AND entity_id = ?').run(
    userId,
    entityType,
    entityId
  );
}

/** Batch hydrate tag names keyed by entity_id to avoid N+1 queries. */
export function getEntityTagsMap(
  db: Database.Database,
  userId: number,
  entityType: ChunkEntityType,
  entityIds: number[]
): Map<number, string[]> {
  const result = new Map<number, string[]>();
  if (entityIds.length === 0) return result;

  const unique = Array.from(new Set(entityIds));
  const inMarks = unique.map(() => '?').join(',');
  const rows = db
    .prepare(
      `SELECT et.entity_id, t.name
       FROM entity_tags et
       JOIN tags t ON t.id = et.tag_id
       WHERE et.user_id = ? AND et.entity_type = ? AND et.entity_id IN (${inMarks})
       ORDER BY t.name ASC`
    )
    .all(userId, entityType, ...unique) as Array<{ entity_id: number; name: string }>;

  for (const row of rows) {
    const arr = result.get(row.entity_id);
    if (arr) {
      arr.push(row.name);
    } else {
      result.set(row.entity_id, [row.name]);
    }
  }
  return result;
}

export function getEntityTags(
  db: Database.Database,
  userId: number,
  entityType: ChunkEntityType,
  entityId: number
): string[] {
  return getEntityTagsMap(db, userId, entityType, [entityId]).get(entityId) || [];
}

/** List all relational tags for a user with live usage counts across resources and wiki pages. */
export function getUserTags(userId: number, limit = 100): TagRecord[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT t.id, t.name, t.color, COUNT(et.tag_id) AS count
       FROM tags t
       LEFT JOIN entity_tags et ON et.tag_id = t.id AND et.user_id = t.user_id
       WHERE t.user_id = ?
       GROUP BY t.id
       ORDER BY count DESC, t.name ASC
       LIMIT ?`
    )
    .all(userId, limit) as Array<{ id: number; name: string; color: string; count: number }>;

  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    tag: r.name,
    color: r.color || '',
    count: Number(r.count || 0),
  }));
}

/** Update tags for a single entity if ownership checks out. */
export function updateEntityTags(
  userId: number,
  entityType: ChunkEntityType,
  entityId: number,
  tags: string[]
): string[] | null {
  const db = getDb();
  const table = entityType === 'wiki' ? 'wiki_pages' : 'resources';
  const owned = db.prepare(`SELECT id FROM ${table} WHERE id = ? AND user_id = ?`).get(entityId, userId) as
    | { id: number }
    | undefined;
  if (!owned) return null;

  return setEntityTags(db, userId, entityType, entityId, tags);
}

/** O(1) rename and/or recolor a tag globally across all tagged entities for this user. */
export function updateUserTag(
  userId: number,
  tagId: number,
  patch: { name?: string | undefined; color?: string | undefined }
): TagRecord | null {
  const db = getDb();
  const current = db.prepare('SELECT id, name, color FROM tags WHERE id = ? AND user_id = ?').get(tagId, userId) as
    | { id: number; name: string; color: string }
    | undefined;
  if (!current) return null;

  const cleanName = patch.name !== undefined ? normalizeTagNames([patch.name])[0] || '' : current.name;
  if (!cleanName) {
    throw new Error('Tag name cannot be empty');
  }
  const nextColor = patch.color !== undefined ? String(patch.color).trim().slice(0, 16) : current.color;

  const tx = db.transaction(() => {
    const duplicate = db
      .prepare('SELECT id FROM tags WHERE user_id = ? AND name = ? AND id != ?')
      .get(userId, cleanName, tagId) as { id: number } | undefined;

    if (duplicate) {
      // Merge associations into existing target tag then delete old tag
      db.prepare(`
        INSERT OR IGNORE INTO entity_tags(tag_id, user_id, entity_type, entity_id, created_at)
        SELECT ?, user_id, entity_type, entity_id, created_at
        FROM entity_tags
        WHERE tag_id = ? AND user_id = ?
      `).run(duplicate.id, tagId, userId);
      db.prepare('DELETE FROM tags WHERE id = ? AND user_id = ?').run(tagId, userId);
      if (patch.color !== undefined) {
        db.prepare('UPDATE tags SET color = ? WHERE id = ? AND user_id = ?').run(nextColor, duplicate.id, userId);
      }
      return duplicate.id;
    }

    db.prepare('UPDATE tags SET name = ?, color = ? WHERE id = ? AND user_id = ?').run(
      cleanName,
      nextColor,
      tagId,
      userId
    );
    return tagId;
  });

  const finalId = tx();
  const all = getUserTags(userId, 500);
  return all.find((t) => t.id === finalId) || null;
}

export function deleteUserTag(userId: number, tagId: number): boolean {
  const db = getDb();
  const res = db.prepare('DELETE FROM tags WHERE id = ? AND user_id = ?').run(tagId, userId);
  return res.changes > 0;
}

/** Resolve all entity references carrying ANY of the given tag names. */
export function getEntityRefsByTags(
  db: Database.Database,
  userId: number,
  tagNames: string[]
): EntityRef[] {
  const clean = normalizeTagNames(tagNames);
  if (clean.length === 0) return [];

  const marks = clean.map(() => '?').join(',');
  return db
    .prepare(
      `SELECT DISTINCT et.entity_type, et.entity_id
       FROM entity_tags et
       JOIN tags t ON t.id = et.tag_id
       WHERE et.user_id = ? AND t.name IN (${marks})`
    )
    .all(userId, ...clean) as EntityRef[];
}

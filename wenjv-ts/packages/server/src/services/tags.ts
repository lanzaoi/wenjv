import { getDb } from '../db/index.js';

export interface TagSummary {
  name: string;
  tag: string;
  count: number;
}

export function getUserTags(userId: number): TagSummary[] {
  const db = getDb();
  const tagCounts = new Map<string, number>();

  const queries = [
    'SELECT tags FROM file_uploads WHERE user_id = ?',
    'SELECT tags FROM notes WHERE user_id = ?',
    'SELECT tags FROM links WHERE user_id = ?',
    'SELECT tags FROM wiki_pages WHERE user_id = ?',
  ];

  for (const q of queries) {
    const rows = db.prepare(q).all(userId) as { tags: string }[];
    for (const r of rows) {
      if (!r.tags) continue;
      try {
        const list = JSON.parse(r.tags);
        if (Array.isArray(list)) {
          for (const t of list) {
            const clean = String(t).trim();
            if (clean) {
              tagCounts.set(clean, (tagCounts.get(clean) || 0) + 1);
            }
          }
        }
      } catch {
        // ignore json parse error
      }
    }
  }

  const result: TagSummary[] = Array.from(tagCounts.entries()).map(([tag, count]) => ({
    name: tag,
    tag,
    count,
  }));
  result.sort((a, b) => b.count - a.count);
  return result;
}

export function updateResourceTags(
  userId: number,
  sourceType: string,
  resourceId: number | string,
  tags: string[]
): boolean {
  const db = getDb();
  const tagsJson = JSON.stringify(tags);
  const idNum = Number(resourceId);

  if (sourceType === 'file') {
    const res = db
      .prepare('UPDATE file_uploads SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?')
      .run(tagsJson, idNum, userId);
    return res.changes > 0;
  }
  if (sourceType === 'note') {
    const res = db
      .prepare('UPDATE notes SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?')
      .run(tagsJson, idNum, userId);
    return res.changes > 0;
  }
  if (sourceType === 'link') {
    const res = db
      .prepare('UPDATE links SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?')
      .run(tagsJson, idNum, userId);
    return res.changes > 0;
  }
  if (sourceType === 'wiki') {
    const res = db
      .prepare('UPDATE wiki_pages SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?')
      .run(tagsJson, idNum, userId);
    return res.changes > 0;
  }

  return false;
}

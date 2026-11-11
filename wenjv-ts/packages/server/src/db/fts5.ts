import type Database from 'better-sqlite3';

export interface FtsMatchRow {
  chunk_id: string;
  title: string;
  filename: string;
  page_content: string;
  user_id: string | null;
  belongs_to: string | null;
  source_type: string | null;
  link_id: string | null;
  resource_id?: string | null;
  bm25_score: number;
}

export interface FtsInsertRow {
  chunk_id: string;
  title?: string | null;
  filename?: string | null;
  page_content?: string | null;
  user_id?: string | number | null;
  belongs_to?: string | null;
  source_type?: string | null;
  link_id?: string | null;
  resource_id?: string | null;
}

export interface MatchFts5Options {
  userId?: number | string | null | undefined;
  belongsTo?: string | null | undefined;
  limit?: number | undefined;
  includeSources?: string[] | null | undefined;
  sourceType?: string | null | undefined;
}

export function sanitizeFtsQuery(text: string): string {
  const cleaned = text.replace(/[^\p{L}\p{N}_\u4e00-\u9fff]/gu, ' ');
  const words = cleaned.split(/\s+/).filter((t) => t.length >= 1);
  if (words.length === 0) {
    return '';
  }

  const cjkParts: string[] = [];
  const asciiParts: string[] = [];

  for (const word of words) {
    if (/[\u4e00-\u9fff]/.test(word)) {
      const cjkChars = word.match(/[\u4e00-\u9fff]/g) || [];
      for (let i = 0; i <= cjkChars.length - 3; i++) {
        cjkParts.push(cjkChars.slice(i, i + 3).join(''));
      }
      const asciiWordChars = word.match(/[A-Za-z0-9]+/g) || [];
      cjkParts.push(...asciiWordChars);
    } else {
      asciiParts.push(`"${word}"`);
    }
  }

  const resultParts: string[] = [];
  if (cjkParts.length > 0) {
    const uniqueGrams = Array.from(new Set(cjkParts));
    const capped = uniqueGrams.slice(0, 50);
    resultParts.push('(' + capped.map((c) => `"${c}"`).join(' OR ') + ')');
  }
  if (asciiParts.length > 0) {
    resultParts.push('(' + asciiParts.join(' AND ') + ')');
  }

  return resultParts.join(' AND ');
}

export function createFts5Table(db: Database.Database): void {
  db.exec(`
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
      chunk_id UNINDEXED,
      title,
      filename,
      page_content,
      user_id UNINDEXED,
      belongs_to UNINDEXED,
      source_type UNINDEXED,
      link_id UNINDEXED,
      resource_id UNINDEXED,
      tokenize='trigram'
    );
  `);
}

export function insertFts5(db: Database.Database, row: FtsInsertRow): void {
  insertFts5Batch(db, [row]);
}

export function insertFts5Batch(db: Database.Database, rows: FtsInsertRow[]): void {
  if (rows.length === 0) return;

  const stmt = db.prepare(`
    INSERT INTO chunks_fts(
      chunk_id, title, filename, page_content,
      user_id, belongs_to, source_type, link_id, resource_id
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const runBatch = db.transaction((items: FtsInsertRow[]) => {
    for (const r of items) {
      stmt.run(
        r.chunk_id,
        r.title || '',
        r.filename || '',
        r.page_content || '',
        r.user_id !== undefined && r.user_id !== null ? String(r.user_id) : null,
        r.belongs_to || '',
        r.source_type !== undefined && r.source_type !== null ? String(r.source_type) : '',
        r.link_id !== undefined && r.link_id !== null ? String(r.link_id) : null,
        r.resource_id !== undefined && r.resource_id !== null ? String(r.resource_id) : null
      );
    }
  });

  runBatch(rows);
}

export function matchFts5(
  db: Database.Database,
  prompt: string,
  options: MatchFts5Options = {}
): FtsMatchRow[] {
  const {
    userId,
    belongsTo,
    limit = 50,
    includeSources,
    sourceType,
  } = options;

  const terms = sanitizeFtsQuery(prompt);
  let rows: FtsMatchRow[] = [];

  if (terms) {
    const whereParts: string[] = ['chunks_fts MATCH ?'];
    const params: (string | number)[] = [terms];

    if (userId !== undefined && userId !== null) {
      whereParts.push('user_id = ?');
      params.push(String(userId));
    }
    if (belongsTo !== undefined && belongsTo !== null) {
      whereParts.push('belongs_to = ?');
      params.push(belongsTo);
    }
    if (sourceType !== undefined && sourceType !== null) {
      whereParts.push('source_type = ?');
      params.push(String(sourceType));
    }
    if (includeSources && includeSources.length > 0) {
      const cleanSources = includeSources.filter(Boolean).map(String);
      if (cleanSources.length > 0) {
        const paramMarks = cleanSources.map(() => '?').join(',');
        whereParts.push(`(filename IN (${paramMarks}) OR title IN (${paramMarks}))`);
        params.push(...cleanSources, ...cleanSources);
      }
    }

    const where = whereParts.join(' AND ');
    const sql = `
      SELECT chunk_id, title, filename, page_content, user_id,
             belongs_to, source_type, link_id, resource_id,
             rank AS bm25_score
      FROM chunks_fts
      WHERE ${where}
      ORDER BY rank
      LIMIT ?
    `;
    params.push(limit);

    try {
      rows = db.prepare(sql).all(...params) as FtsMatchRow[];
    } catch {
      rows = [];
    }
  }

  // Fallback to LIKE substring search if FTS5 matched nothing
  if (rows.length === 0 && prompt && prompt.trim().length > 0) {
    const cleaned = prompt.replace(/[^\p{L}\p{N}_\u4e00-\u9fff]/gu, ' ');
    const cleanedWords = cleaned.split(/\s+/).map((w) => w.trim()).filter((w) => w.length > 0);

    if (cleanedWords.length > 0) {
      const fallbackWhere: string[] = [];
      const fallbackParams: (string | number)[] = [];

      const termConditions: string[] = [];
      for (const w of cleanedWords.slice(0, 5)) {
        termConditions.push('(page_content LIKE ? OR title LIKE ? OR filename LIKE ?)');
        fallbackParams.push(`%${w}%`, `%${w}%`, `%${w}%`);
      }
      fallbackWhere.push('(' + termConditions.join(' OR ') + ')');

      if (userId !== undefined && userId !== null) {
        fallbackWhere.push('user_id = ?');
        fallbackParams.push(String(userId));
      }
      if (belongsTo !== undefined && belongsTo !== null) {
        fallbackWhere.push('belongs_to = ?');
        fallbackParams.push(belongsTo);
      }
      if (sourceType !== undefined && sourceType !== null) {
        fallbackWhere.push('source_type = ?');
        fallbackParams.push(String(sourceType));
      }
      if (includeSources && includeSources.length > 0) {
        const cleanSources = includeSources.filter(Boolean).map(String);
        if (cleanSources.length > 0) {
          const paramMarks = cleanSources.map(() => '?').join(',');
          fallbackWhere.push(`(filename IN (${paramMarks}) OR title IN (${paramMarks}))`);
          fallbackParams.push(...cleanSources, ...cleanSources);
        }
      }

      const fWhere = fallbackWhere.join(' AND ');
      const fSql = `
        SELECT chunk_id, title, filename, page_content, user_id,
               belongs_to, source_type, link_id, resource_id,
               -1.0 AS bm25_score
        FROM chunks_fts
        WHERE ${fWhere}
        LIMIT ?
      `;
      fallbackParams.push(limit);

      try {
        rows = db.prepare(fSql).all(...fallbackParams) as FtsMatchRow[];
      } catch {
        rows = [];
      }
    }
  }

  return rows;
}

export function deleteByChunkId(db: Database.Database, chunkId: string): void {
  db.prepare('DELETE FROM chunks_fts WHERE chunk_id = ?').run(chunkId);
}

export function deleteByFilename(db: Database.Database, filename: string, belongsTo?: string | null): void {
  if (belongsTo) {
    db.prepare('DELETE FROM chunks_fts WHERE filename = ? AND belongs_to = ?').run(filename, belongsTo);
  } else {
    db.prepare('DELETE FROM chunks_fts WHERE filename = ?').run(filename);
  }
}

export function deleteByLinkId(db: Database.Database, linkId: string, belongsTo?: string | null): void {
  if (belongsTo) {
    db.prepare('DELETE FROM chunks_fts WHERE link_id = ? AND belongs_to = ?').run(linkId, belongsTo);
  } else {
    db.prepare('DELETE FROM chunks_fts WHERE link_id = ?').run(linkId);
  }
}

export function deleteByResourceId(db: Database.Database, resourceId: string, userId?: string | null): void {
  if (userId) {
    db.prepare('DELETE FROM chunks_fts WHERE resource_id = ? AND user_id = ?').run(String(resourceId), String(userId));
  } else {
    db.prepare('DELETE FROM chunks_fts WHERE resource_id = ?').run(String(resourceId));
  }
}

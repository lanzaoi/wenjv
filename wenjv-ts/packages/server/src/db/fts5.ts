import type Database from 'better-sqlite3';
import type { ChunkEntityType, ChunkResourceType } from './chunks.js';

export interface EntityFilterRef {
  entity_type: ChunkEntityType;
  entity_id: number;
}

export interface FtsMatchRow {
  chunk_id: string;
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
  bm25_score: number;
}

export interface MatchFts5Options {
  userId?: number | null | undefined;
  limit?: number | undefined;
  includeSources?: string[] | null | undefined;
  resourceType?: ChunkResourceType | null | undefined;
  entityType?: ChunkEntityType | null | undefined;
  entityRefs?: EntityFilterRef[] | null | undefined;
}

function escapeLikePattern(term: string): string {
  return term.replace(/[\\%_]/g, '\\$&');
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

/**
 * Create external-content FTS5 virtual table bound to `chunks` + sync triggers.
 * Eliminates dual-write drift and duplicated text storage.
 */
export function createFts5Table(db: Database.Database): void {
  db.exec(`
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
      title,
      source,
      content,
      content='chunks',
      content_rowid='rowid',
      tokenize='trigram'
    );

    CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
      INSERT INTO chunks_fts(rowid, title, source, content)
      VALUES (new.rowid, new.title, new.source, new.content);
    END;

    CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, title, source, content)
      VALUES ('delete', old.rowid, old.title, old.source, old.content);
    END;

    CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, title, source, content)
      VALUES ('delete', old.rowid, old.title, old.source, old.content);
      INSERT INTO chunks_fts(rowid, title, source, content)
      VALUES (new.rowid, new.title, new.source, new.content);
    END;
  `);
}

function appendCommonFilters(
  whereParts: string[],
  params: (string | number)[],
  options: MatchFts5Options
): boolean {
  if (options.userId !== undefined && options.userId !== null) {
    whereParts.push('c.user_id = ?');
    params.push(options.userId);
  }
  if (options.entityType) {
    whereParts.push('c.entity_type = ?');
    params.push(options.entityType);
  }
  if (options.resourceType) {
    whereParts.push('c.resource_type = ?');
    params.push(options.resourceType);
  }
  if (options.includeSources && options.includeSources.length > 0) {
    const cleanSources = options.includeSources.filter(Boolean).map(String);
    if (cleanSources.length > 0) {
      const marks = cleanSources.map(() => '?').join(',');
      whereParts.push(`(c.source IN (${marks}) OR c.title IN (${marks}))`);
      params.push(...cleanSources, ...cleanSources);
    }
  }
  if (options.entityRefs !== undefined && options.entityRefs !== null) {
    if (options.entityRefs.length === 0) {
      return false;
    }
    const refClauses: string[] = [];
    for (const ref of options.entityRefs) {
      refClauses.push('(c.entity_type = ? AND c.entity_id = ?)');
      params.push(ref.entity_type, ref.entity_id);
    }
    whereParts.push('(' + refClauses.join(' OR ') + ')');
  }
  return true;
}

export function matchFts5(
  db: Database.Database,
  prompt: string,
  options: MatchFts5Options = {}
): FtsMatchRow[] {
  const limit = options.limit ?? 50;
  const terms = sanitizeFtsQuery(prompt);
  let rows: FtsMatchRow[] = [];

  if (terms) {
    const whereParts: string[] = ['chunks_fts MATCH ?'];
    const params: (string | number)[] = [terms];
    if (!appendCommonFilters(whereParts, params, options)) {
      return [];
    }

    const sql = `
      SELECT c.id AS chunk_id, c.user_id, c.entity_type, c.entity_id, c.resource_type,
             c.chunk_order, c.page_number, c.header_path, c.title, c.source, c.content,
             f.rank AS bm25_score
      FROM chunks_fts f
      JOIN chunks c ON c.rowid = f.rowid
      WHERE ${whereParts.join(' AND ')}
      ORDER BY f.rank
      LIMIT ?
    `;
    params.push(limit);

    try {
      rows = db.prepare(sql).all(...params) as FtsMatchRow[];
    } catch {
      rows = [];
    }
  }

  // Fallback to LIKE substring search when trigram FTS5 returns nothing (e.g. 1-2 char CJK)
  if (rows.length === 0 && prompt && prompt.trim().length > 0) {
    const cleaned = prompt.replace(/[^\p{L}\p{N}_\u4e00-\u9fff]/gu, ' ');
    const cleanedWords = cleaned.split(/\s+/).map((w) => w.trim()).filter((w) => w.length > 0);

    if (cleanedWords.length > 0) {
      const fallbackWhere: string[] = [];
      const fallbackParams: (string | number)[] = [];

      const termConditions: string[] = [];
      for (const w of cleanedWords.slice(0, 5)) {
        const pat = `%${escapeLikePattern(w)}%`;
        termConditions.push("(c.content LIKE ? ESCAPE '\\' OR c.title LIKE ? ESCAPE '\\' OR c.source LIKE ? ESCAPE '\\')");
        fallbackParams.push(pat, pat, pat);
      }
      fallbackWhere.push('(' + termConditions.join(' OR ') + ')');

      if (!appendCommonFilters(fallbackWhere, fallbackParams, options)) {
        return [];
      }

      const fSql = `
        SELECT c.id AS chunk_id, c.user_id, c.entity_type, c.entity_id, c.resource_type,
               c.chunk_order, c.page_number, c.header_path, c.title, c.source, c.content,
               -1.0 AS bm25_score
        FROM chunks c
        WHERE ${fallbackWhere.join(' AND ')}
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

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { getDb } from '../db/index.js';
import { config } from '../config.js';
import { getEmbedder } from '../ai/bge-m3.js';
import { getDocumentStore } from '../vector/document-store.js';
import { insertFts5Batch, deleteByResourceId, deleteByChunkId } from '../db/fts5.js';
import { structureAwareChunk, RecursiveTextSplitter } from '../chunker/structure.js';
import { parsePdf } from '../parsers/pdf.js';
import { parseDocx } from '../parsers/docx.js';
import { parsePptx } from '../parsers/pptx.js';
import { parseHtml } from '../parsers/html.js';
import { parseText } from '../parsers/text.js';
import { safeFetch } from './ssrf.js';

export function generateDeterministicChunkId(
  resourceId: string,
  chunkOrder: number,
  textContent: string,
  headerPath = ''
): string {
  const contentSnippet = textContent ? Array.from(textContent).slice(0, 64).join('') : '';
  const seed = `${resourceId || '0'}:${headerPath}:${chunkOrder}:${contentSnippet}`;
  return crypto.createHash('sha256').update(seed, 'utf8').digest('hex').slice(0, 24);
}

export interface IngestionJobRecord {
  id: number;
  job_type: string;
  resource_id: number;
  user_id: number;
  user_email: string;
  payload: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export function enqueueJob(params: {
  job_type: string;
  resource_id: number;
  user_id: number;
  user_email: string;
  payload?: Record<string, unknown>;
  max_attempts?: number;
}): IngestionJobRecord {
  const db = getDb();
  const payloadStr = JSON.stringify(params.payload || {});

  // Deduplicate existing pending job
  const existing = db
    .prepare(
      'SELECT * FROM ingestion_jobs WHERE job_type = ? AND resource_id = ? AND user_id = ? AND status = ? ORDER BY id DESC LIMIT 1'
    )
    .get(params.job_type, params.resource_id, params.user_id, 'pending') as IngestionJobRecord | undefined;

  if (existing) {
    db.prepare('UPDATE ingestion_jobs SET payload = ?, user_email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(
      payloadStr,
      params.user_email,
      existing.id
    );
    return db.prepare('SELECT * FROM ingestion_jobs WHERE id = ?').get(existing.id) as IngestionJobRecord;
  }

  const res = db
    .prepare(`
      INSERT INTO ingestion_jobs(
        job_type, resource_id, user_id, user_email, payload, status, attempts, max_attempts
      )
      VALUES (?, ?, ?, ?, ?, 'pending', 0, ?)
    `)
    .run(
      params.job_type,
      params.resource_id,
      params.user_id,
      params.user_email,
      payloadStr,
      params.max_attempts || config.JOB_MAX_ATTEMPTS
    );

  return db.prepare('SELECT * FROM ingestion_jobs WHERE id = ?').get(Number(res.lastInsertRowid)) as IngestionJobRecord;
}

export function getJob(jobId: number): IngestionJobRecord | null {
  const db = getDb();
  const row = db.prepare('SELECT * FROM ingestion_jobs WHERE id = ?').get(jobId) as IngestionJobRecord | undefined;
  return row || null;
}

export function claimNextJob(): IngestionJobRecord | null {
  const db = getDb();
  // Preferred order: wiki, file, link, note
  const preferredTypes = ['wiki', 'file', 'link', 'note'];
  let candidate: IngestionJobRecord | undefined;

  for (const pType of preferredTypes) {
    candidate = db
      .prepare('SELECT * FROM ingestion_jobs WHERE status = ? AND job_type = ? ORDER BY id ASC LIMIT 1')
      .get('pending', pType) as IngestionJobRecord | undefined;
    if (candidate) break;
  }

  if (!candidate) {
    candidate = db
      .prepare('SELECT * FROM ingestion_jobs WHERE status = ? ORDER BY id ASC LIMIT 1')
      .get('pending') as IngestionJobRecord | undefined;
  }

  if (!candidate) return null;

  markResourceInProgress(candidate.job_type, candidate.resource_id);

  db.prepare(`
    UPDATE ingestion_jobs
    SET status = 'running',
        attempts = attempts + 1,
        started_at = CURRENT_TIMESTAMP,
        updated_at = CURRENT_TIMESTAMP,
        last_error = NULL
    WHERE id = ?
  `).run(candidate.id);

  return db.prepare('SELECT * FROM ingestion_jobs WHERE id = ?').get(candidate.id) as IngestionJobRecord;
}

export function reclaimStaleJobs(): number {
  const db = getDb();
  const staleThreshold = config.JOB_STALE_SECONDS;
  const staleRows = db
    .prepare(`
      SELECT * FROM ingestion_jobs
      WHERE status = 'running'
        AND (started_at IS NULL OR (unixepoch('now') - unixepoch(started_at)) > ?)
    `)
    .all(staleThreshold) as IngestionJobRecord[];

  for (const job of staleRows) {
    if (job.attempts >= job.max_attempts) {
      db.prepare(`
        UPDATE ingestion_jobs
        SET status = 'failed',
            last_error = COALESCE(last_error, '') || ' | stale timeout',
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
      `).run(job.id);
      markResourceFailed(job.job_type, job.resource_id, 'stale timeout');
    } else {
      db.prepare(`
        UPDATE ingestion_jobs
        SET status = 'pending',
            started_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
      `).run(job.id);
    }
  }

  return staleRows.length;
}

function markResourceInProgress(jobType: string, resourceId: number): void {
  const db = getDb();
  if (jobType === 'file') {
    db.prepare("UPDATE file_uploads SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(resourceId);
  } else if (jobType === 'note') {
    db.prepare("UPDATE notes SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(resourceId);
  } else if (jobType === 'link') {
    db.prepare("UPDATE links SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(resourceId);
  } else if (jobType === 'wiki') {
    db.prepare("UPDATE wiki_pages SET index_status = 'indexing', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(resourceId);
  }
}

function markResourceFailed(jobType: string, resourceId: number, errorMsg: string): void {
  const db = getDb();
  const err = errorMsg.slice(0, 500);
  if (jobType === 'file') {
    db.prepare('UPDATE file_uploads SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(
      'failed',
      err,
      resourceId
    );
  } else if (jobType === 'note') {
    db.prepare('UPDATE notes SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(
      'failed',
      err,
      resourceId
    );
  } else if (jobType === 'link') {
    db.prepare('UPDATE links SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(
      'failed',
      err,
      resourceId
    );
  } else if (jobType === 'wiki') {
    db.prepare('UPDATE wiki_pages SET index_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(
      'failed',
      resourceId
    );
  }
}

export async function executeJob(job: IngestionJobRecord): Promise<void> {
  const db = getDb();
  const embedder = getEmbedder();
  const docStore = getDocumentStore();
  const splitter = new RecursiveTextSplitter({ chunkSize: 1000, chunkOverlap: 150 });

  try {
    let title = '';
    let filename = '';
    let content = '';
    let sourceType = job.job_type;
    const resourceIdStr = String(job.resource_id);
    const userIdStr = String(job.user_id);
    let linkIdStr = '';
    let belongsTo = '';

    if (job.job_type === 'file') {
      const fileRow = db.prepare('SELECT * FROM file_uploads WHERE id = ?').get(job.resource_id) as Record<string, unknown> | undefined;
      if (!fileRow) throw new Error(`FileUpload ${job.resource_id} not found`);

      filename = String(fileRow['filename'] || '');
      title = String(fileRow['original_filename'] || filename);
      belongsTo = filename;
      const filePath = String(fileRow['file_path'] || path.join(config.resolvedUploadDir, filename));

      if (!fs.existsSync(filePath)) {
        throw new Error(`File on disk not found: ${filePath}`);
      }

      const buffer = fs.readFileSync(filePath);
      const ext = path.extname(filename).toLowerCase().replace('.', '');

      if (ext === 'pdf') {
        const parsed = await parsePdf(buffer);
        content = parsed.text;
      } else if (ext === 'docx') {
        const parsed = await parseDocx(buffer);
        content = parsed.text;
      } else if (ext === 'pptx') {
        const parsed = await parsePptx(buffer);
        content = parsed.text;
      } else if (ext === 'html' || ext === 'htm') {
        const parsed = parseHtml(buffer.toString('utf8'));
        content = parsed.text;
        if (parsed.title) title = parsed.title;
      } else {
        const parsed = parseText(buffer);
        content = parsed.text;
      }
    } else if (job.job_type === 'note') {
      const noteRow = db.prepare('SELECT * FROM notes WHERE id = ?').get(job.resource_id) as Record<string, unknown> | undefined;
      if (!noteRow) throw new Error(`Note ${job.resource_id} not found`);

      title = String(noteRow['title'] || 'Note');
      filename = String(noteRow['filename'] || `${title}.md`);
      belongsTo = filename;
      const filePath = String(noteRow['file_path'] || path.join(config.resolvedUploadDir, filename));

      if (fs.existsSync(filePath)) {
        content = fs.readFileSync(filePath, 'utf8');
      } else {
        content = String(noteRow['url'] || '');
      }
    } else if (job.job_type === 'link') {
      const linkRow = db.prepare('SELECT * FROM links WHERE id = ?').get(job.resource_id) as Record<string, unknown> | undefined;
      if (!linkRow) throw new Error(`Link ${job.resource_id} not found`);

      title = String(linkRow['title'] || linkRow['url'] || 'Link');
      const url = String(linkRow['url'] || '');
      linkIdStr = resourceIdStr;
      belongsTo = url;

      // Fetch webpage using SSRF-safe redirect validator
      const resp = await safeFetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; WenjvBot/1.0)' } });
      if (!resp.ok) throw new Error(`Failed to fetch url: HTTP ${resp.status}`);
      const htmlText = await resp.text();
      const parsed = parseHtml(htmlText);
      content = parsed.text;
      if (parsed.title) {
        title = parsed.title;
        db.prepare('UPDATE links SET title = ? WHERE id = ?').run(title, job.resource_id);
      }
    } else if (job.job_type === 'wiki') {
      const wikiRow = db.prepare('SELECT * FROM wiki_pages WHERE id = ?').get(job.resource_id) as Record<string, unknown> | undefined;
      if (!wikiRow) throw new Error(`WikiPage ${job.resource_id} not found`);

      title = String(wikiRow['title'] || 'Wiki Page');
      filename = `${String(wikiRow['slug'] || title)}.md`;
      belongsTo = filename;
      content = String(wikiRow['content'] || '');
      sourceType = 'wiki';
    } else {
      throw new Error(`Unknown job_type: ${job.job_type}`);
    }

    // Clean up existing chunks for this resource before re-indexing
    deleteByResourceId(db, resourceIdStr, userIdStr);
    await docStore.deleteByResourceId(resourceIdStr, userIdStr);

    if (content.trim()) {
      const chunks = structureAwareChunk(content, splitter);
      if (chunks.length > 0) {
        const textsToEmbed = chunks.map((c) => c.indexing_text);
        const vectors = await embedder.embedDocuments(textsToEmbed);

        const chunkGroup = resourceIdStr || crypto.randomUUID();
        const ftsRows = [];
        const vectorRows = [];

        for (let i = 0; i < chunks.length; i++) {
          const chunk = chunks[i]!;
          const chunkId = generateDeterministicChunkId(
            resourceIdStr,
            i,
            chunk.indexing_text,
            chunk.header_str
          );
          const vec = vectors[i] || new Array(1024).fill(0);

          ftsRows.push({
            chunk_id: chunkId,
            title,
            filename,
            page_content: chunk.indexing_text,
            user_id: userIdStr,
            belongs_to: belongsTo,
            source_type: sourceType,
            link_id: linkIdStr,
            resource_id: resourceIdStr,
          });

          vectorRows.push({
            id: chunkId,
            vector: vec,
            page_content: chunk.indexing_text,
            source: belongsTo,
            page: String(chunk.page_number || 1),
            title,
            filename,
            belongs_to: belongsTo,
            user_id: userIdStr,
            link_id: linkIdStr,
            file_id: job.job_type === 'file' ? resourceIdStr : '',
            source_type: sourceType,
            resource_id: resourceIdStr,
            chunk_group: chunkGroup,
            chunk_order: i,
            image_path: '',
          });

          // Insert chunk mapping
          db.prepare(`
            INSERT OR REPLACE INTO chunk_mapping(chunk_id, chunk_group, chunk_order, resource_id)
            VALUES (?, ?, ?, ?)
          `).run(chunkId, chunkGroup, i, resourceIdStr);
        }

        insertFts5Batch(db, ftsRows);
        await docStore.addDocuments(vectorRows);
      }
    }

    // Mark resource succeeded / finished
    if (job.job_type === 'file') {
      db.prepare("UPDATE file_uploads SET status = 'finished', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
        job.resource_id
      );
    } else if (job.job_type === 'note') {
      db.prepare("UPDATE notes SET status = 'finished', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
        job.resource_id
      );
    } else if (job.job_type === 'link') {
      db.prepare("UPDATE links SET status = 'finished', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
        job.resource_id
      );
    } else if (job.job_type === 'wiki') {
      db.prepare("UPDATE wiki_pages SET index_status = 'indexed', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
        job.resource_id
      );
    }

    // Mark job succeeded
    db.prepare(`
      UPDATE ingestion_jobs
      SET status = 'succeeded',
          finished_at = CURRENT_TIMESTAMP,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(job.id);
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    if (job.attempts >= job.max_attempts) {
      db.prepare(`
        UPDATE ingestion_jobs
        SET status = 'failed',
            last_error = ?,
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
      `).run(errorMsg, job.id);
      markResourceFailed(job.job_type, job.resource_id, errorMsg);
    } else {
      db.prepare(`
        UPDATE ingestion_jobs
        SET status = 'pending',
            last_error = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
      `).run(errorMsg, job.id);
    }
    throw err;
  }
}

let _runnerRunning = false;

export function startJobRunner(): void {
  if (_runnerRunning) return;
  _runnerRunning = true;

  // Reclaim stale jobs upon startup
  reclaimStaleJobs();

  const tick = async () => {
    if (!_runnerRunning) return;
    try {
      const job = claimNextJob();
      if (job) {
        await executeJob(job);
      }
    } catch {
      // ignore
    } finally {
      setTimeout(tick, config.JOB_POLL_INTERVAL_SECONDS * 1000);
    }
  };

  setTimeout(tick, 500);
}

export function stopJobRunner(): void {
  _runnerRunning = false;
}

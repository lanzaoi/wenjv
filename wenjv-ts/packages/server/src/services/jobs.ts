import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import sharp from 'sharp';
import { getDb } from '../db/index.js';
import { config } from '../config.js';
import { getEmbedder } from '../ai/bge-m3.js';
import { getTextStore } from '../vector/text-store.js';
import {
  replaceEntityChunks,
  deleteEntityChunks,
  type ChunkEntityType,
  type ChunkResourceType,
  type ChunkInsertInput,
} from '../db/chunks.js';
import { structureAwareChunk, RecursiveTextSplitter } from '../chunker/structure.js';
import { parsePdf } from '../parsers/pdf.js';
import { parseDocx } from '../parsers/docx.js';
import { parsePptx } from '../parsers/pptx.js';
import { parseHtml } from '../parsers/html.js';
import { parseText } from '../parsers/text.js';
import { safeFetch } from './ssrf.js';
import { registerAsset } from './assets.js';

export function generateDeterministicChunkId(
  entityType: ChunkEntityType,
  entityId: string | number,
  chunkOrder: number,
  textContent: string,
  headerPath = ''
): string {
  const contentSnippet = textContent ? Array.from(textContent).slice(0, 64).join('') : '';
  const seed = `${entityType}:${entityId || '0'}:${headerPath}:${chunkOrder}:${contentSnippet}`;
  return crypto.createHash('sha256').update(seed, 'utf8').digest('hex').slice(0, 24);
}

export interface IngestionJobRecord {
  id: number;
  entity_type: ChunkEntityType;
  entity_id: number;
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
  entity_type: ChunkEntityType;
  entity_id: number;
  user_id: number;
  user_email: string;
  payload?: Record<string, unknown>;
  max_attempts?: number;
}): IngestionJobRecord {
  const db = getDb();
  const payloadStr = JSON.stringify(params.payload || {});

  const runTx = db.transaction(() => {
    const existing = db
      .prepare(
        'SELECT * FROM ingestion_jobs WHERE entity_type = ? AND entity_id = ? AND user_id = ? AND status = ? ORDER BY id DESC LIMIT 1'
      )
      .get(params.entity_type, params.entity_id, params.user_id, 'pending') as IngestionJobRecord | undefined;

    if (existing) {
      db.prepare('UPDATE ingestion_jobs SET payload = ?, user_email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(
        payloadStr,
        params.user_email,
        existing.id
      );
      return db.prepare('SELECT * FROM ingestion_jobs WHERE id = ?').get(existing.id) as IngestionJobRecord;
    }

    try {
      const res = db
        .prepare(`
          INSERT INTO ingestion_jobs(
            entity_type, entity_id, user_id, user_email, payload, status, attempts, max_attempts
          )
          VALUES (?, ?, ?, ?, ?, 'pending', 0, ?)
        `)
        .run(
          params.entity_type,
          params.entity_id,
          params.user_id,
          params.user_email,
          payloadStr,
          params.max_attempts || config.JOB_MAX_ATTEMPTS
        );

      return db.prepare('SELECT * FROM ingestion_jobs WHERE id = ?').get(Number(res.lastInsertRowid)) as IngestionJobRecord;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/UNIQUE constraint/i.test(msg)) {
        const dup = db
          .prepare(
            'SELECT * FROM ingestion_jobs WHERE entity_type = ? AND entity_id = ? AND user_id = ? AND status = ? ORDER BY id DESC LIMIT 1'
          )
          .get(params.entity_type, params.entity_id, params.user_id, 'pending') as IngestionJobRecord | undefined;
        if (dup) return dup;
      }
      throw err;
    }
  });

  return runTx();
}

export function getJob(jobId: number): IngestionJobRecord | null {
  const db = getDb();
  const row = db.prepare('SELECT * FROM ingestion_jobs WHERE id = ?').get(jobId) as IngestionJobRecord | undefined;
  return row || null;
}

export function markEntityPending(entityType: ChunkEntityType, entityId: number): void {
  const db = getDb();
  if (entityType === 'wiki') {
    db.prepare("UPDATE wiki_pages SET index_status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
      entityId
    );
  } else {
    db.prepare("UPDATE resources SET status = 'pending', error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
      entityId
    );
  }
}

function markEntityInProgress(entityType: ChunkEntityType, entityId: number): void {
  const db = getDb();
  if (entityType === 'wiki') {
    db.prepare("UPDATE wiki_pages SET index_status = 'indexing', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
      entityId
    );
  } else {
    db.prepare("UPDATE resources SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(entityId);
  }
}

function markEntityFailed(entityType: ChunkEntityType, entityId: number, errorMsg: string): void {
  const db = getDb();
  const err = errorMsg.slice(0, 500);
  if (entityType === 'wiki') {
    db.prepare("UPDATE wiki_pages SET index_status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(entityId);
  } else {
    db.prepare("UPDATE resources SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
      err,
      entityId
    );
  }
}

function markEntityFinished(entityType: ChunkEntityType, entityId: number): void {
  const db = getDb();
  if (entityType === 'wiki') {
    db.prepare("UPDATE wiki_pages SET index_status = 'indexed', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(entityId);
  } else {
    db.prepare("UPDATE resources SET status = 'finished', error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(
      entityId
    );
  }
}

export function claimNextJob(): IngestionJobRecord | null {
  const db = getDb();
  const preferredTypes: ChunkEntityType[] = ['wiki', 'resource'];
  let candidate: IngestionJobRecord | undefined;

  for (const entityType of preferredTypes) {
    candidate = db
      .prepare('SELECT * FROM ingestion_jobs WHERE status = ? AND entity_type = ? ORDER BY id ASC LIMIT 1')
      .get('pending', entityType) as IngestionJobRecord | undefined;
    if (candidate) break;
  }

  if (!candidate) return null;

  markEntityInProgress(candidate.entity_type, candidate.entity_id);

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
      markEntityFailed(job.entity_type, job.entity_id, 'stale timeout');
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

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp']);

export async function executeJob(job: IngestionJobRecord): Promise<void> {
  const db = getDb();
  const embedder = getEmbedder();
  const textStore = getTextStore();
  const splitter = new RecursiveTextSplitter({ chunkSize: 1000, chunkOverlap: 150 });

  try {
    let title = '';
    let source = '';
    let content = '';
    let resourceType: ChunkResourceType = 'file';

    if (job.entity_type === 'resource') {
      const resRow = db.prepare('SELECT * FROM resources WHERE id = ?').get(job.entity_id) as
        | Record<string, unknown>
        | undefined;
      if (!resRow) throw new Error(`Resource ${job.entity_id} not found`);

      const type = String(resRow['type'] || 'file') as 'file' | 'note' | 'link';
      resourceType = type;

      if (type === 'file') {
        const filename = String(resRow['filename'] || '');
        title = String(resRow['title'] || resRow['original_filename'] || filename);
        source = filename;
        const filePath = String(resRow['file_path'] || path.join(config.resolvedUploadDir, filename));
        if (!fs.existsSync(filePath)) {
          throw new Error(`File on disk not found: ${filePath}`);
        }
        const buffer = fs.readFileSync(filePath);
        const ext = path.extname(filename).toLowerCase().replace('.', '');

        if (IMAGE_EXTENSIONS.has(ext)) {
          const stdBytes = await sharp(buffer)
            .rotate()
            .resize(1280, 1280, { fit: 'inside', withoutEnlargement: true })
            .jpeg({ quality: 85 })
            .toBuffer();

          const relPath = path.relative(config.resolvedUploadDir, filePath).replace(/\\/g, '/');
          await registerAsset({
            userId: job.user_id,
            ownerType: 'resource',
            ownerId: job.entity_id,
            filename,
            relPath,
            absPath: filePath,
            mimeType: String(resRow['content_type'] || 'image/jpeg'),
            size: buffer.length,
            caption: title,
            bytesForVisualIndex: stdBytes,
          });
          content = `图片资源: ${title} (${filename})`;
        } else if (ext === 'pdf') {
          content = (await parsePdf(buffer)).text;
        } else if (ext === 'docx') {
          content = (await parseDocx(buffer)).text;
        } else if (ext === 'pptx') {
          content = (await parsePptx(buffer)).text;
        } else if (ext === 'html' || ext === 'htm') {
          const parsed = parseHtml(buffer.toString('utf8'));
          content = parsed.text;
          if (parsed.title) title = parsed.title;
        } else {
          content = parseText(buffer).text;
        }
      } else if (type === 'note') {
        title = String(resRow['title'] || 'Note');
        const filename = String(resRow['filename'] || `${title}.md`);
        source = filename;
        const filePath = String(resRow['file_path'] || path.join(config.resolvedUploadDir, filename));
        content = fs.existsSync(filePath)
          ? fs.readFileSync(filePath, 'utf8')
          : String(resRow['content_text'] || '');
      } else if (type === 'link') {
        const url = String(resRow['source_url'] || '');
        title = String(resRow['title'] || url || 'Link');
        source = url;

        const resp = await safeFetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; WenjvBot/1.0)' } });
        if (!resp.ok) throw new Error(`Failed to fetch url: HTTP ${resp.status}`);
        const htmlText = await resp.text();
        const parsed = parseHtml(htmlText);
        content = parsed.text;
        if (parsed.title) {
          title = parsed.title;
          db.prepare('UPDATE resources SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?').run(
            title,
            job.entity_id
          );
        }
      }
    } else if (job.entity_type === 'wiki') {
      const wikiRow = db.prepare('SELECT * FROM wiki_pages WHERE id = ?').get(job.entity_id) as
        | Record<string, unknown>
        | undefined;
      if (!wikiRow) throw new Error(`WikiPage ${job.entity_id} not found`);

      title = String(wikiRow['title'] || 'Wiki Page');
      source = `${String(wikiRow['slug'] || title)}.md`;
      content = String(wikiRow['content'] || '');
      resourceType = 'wiki';
    } else {
      throw new Error(`Unknown entity_type: ${job.entity_type}`);
    }

    // Clear previous chunks (trigger cleans FTS5 automatically) and previous vectors
    deleteEntityChunks(db, job.entity_type, job.entity_id, job.user_id);
    await textStore.deleteByEntity(job.entity_type, job.entity_id, job.user_id);

    if (content.trim()) {
      const chunks = structureAwareChunk(content, splitter);
      if (chunks.length > 0) {
        const textsToEmbed = chunks.map((c) => c.indexing_text);
        const vectors = await embedder.embedDocuments(textsToEmbed);

        const chunkRows: ChunkInsertInput[] = [];
        const vectorRows = [];

        for (let i = 0; i < chunks.length; i++) {
          const chunk = chunks[i]!;
          const chunkId = generateDeterministicChunkId(
            job.entity_type,
            job.entity_id,
            i,
            chunk.indexing_text,
            chunk.header_str
          );
          const vec = vectors[i] || new Array(1024).fill(0);

          chunkRows.push({
            id: chunkId,
            user_id: job.user_id,
            entity_type: job.entity_type,
            entity_id: job.entity_id,
            resource_type: resourceType,
            chunk_order: i,
            page_number: chunk.page_number || 1,
            header_path: chunk.header_str || '',
            title,
            source,
            content: chunk.indexing_text,
          });

          vectorRows.push({
            id: chunkId,
            vector: vec,
            user_id: job.user_id,
            entity_type: job.entity_type,
            entity_id: job.entity_id,
            resource_type: resourceType,
          });
        }

        replaceEntityChunks(db, job.user_id, job.entity_type, job.entity_id, chunkRows);
        await textStore.addVectors(vectorRows);
      }
    }

    markEntityFinished(job.entity_type, job.entity_id);

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
      markEntityFailed(job.entity_type, job.entity_id, errorMsg);
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

  reclaimStaleJobs();

  const tick = async () => {
    if (!_runnerRunning) return;
    try {
      const job = claimNextJob();
      if (job) {
        await executeJob(job);
      }
    } catch {
      // ignore background tick error; job retry state already recorded
    } finally {
      setTimeout(tick, config.JOB_POLL_INTERVAL_SECONDS * 1000);
    }
  };

  setTimeout(tick, 500);
}

export function stopJobRunner(): void {
  _runnerRunning = false;
}

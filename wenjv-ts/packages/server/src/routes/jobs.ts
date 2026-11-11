import { Hono } from 'hono';
import { getDb } from '../db/index.js';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { getJob, enqueueJob, type IngestionJobRecord } from '../services/jobs.js';

export const jobsRouter = new Hono();

// GET /jobs
jobsRouter.get('/', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const db = getDb();
  const rows = db
    .prepare('SELECT * FROM ingestion_jobs WHERE user_id = ? ORDER BY id DESC LIMIT 50')
    .all(user.id) as IngestionJobRecord[];
  return c.json(rows);
});

// GET /jobs/:id
jobsRouter.get('/:id', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const job = getJob(id);
  if (!job || job.user_id !== user.id) {
    return c.json({ detail: 'Job not found' }, 404);
  }
  return c.json(job);
});

// POST /jobs/:id/retry
jobsRouter.post('/:id/retry', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const job = getJob(id);
  if (!job || job.user_id !== user.id) {
    return c.json({ detail: 'Job not found' }, 404);
  }

  if (job.status !== 'failed' && job.status !== 'cancelled') {
    return c.json({ detail: `Cannot retry job in status '${job.status}'` }, 409);
  }

  const db = getDb();
  if (job.job_type === 'file') {
    db.prepare("UPDATE file_uploads SET status = 'pending', error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(job.resource_id);
  } else if (job.job_type === 'note') {
    db.prepare("UPDATE notes SET status = 'pending', error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(job.resource_id);
  } else if (job.job_type === 'link') {
    db.prepare("UPDATE links SET status = 'pending', error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(job.resource_id);
  } else if (job.job_type === 'wiki') {
    db.prepare("UPDATE wiki_pages SET index_status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(job.resource_id);
  }

  db.prepare(`
    UPDATE ingestion_jobs
    SET status = 'pending',
        attempts = 0,
        last_error = NULL,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
  `).run(id);

  return c.json({ status: 'pending', job_id: id });
});

import { Hono } from 'hono';
import { getDb } from '../db/index.js';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { getJob, markEntityPending, type IngestionJobRecord } from '../services/jobs.js';

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

  markEntityPending(job.entity_type, job.entity_id);

  const db = getDb();
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

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Hono } from 'hono';
import { serve } from '@hono/node-server';
import { cors } from 'hono/cors';
import { config } from './config.js';
import { getDb } from './db/index.js';
import { startJobRunner } from './services/jobs.js';
import { authRouter } from './routes/auth.js';
import { filesRouter } from './routes/files.js';
import { jobsRouter } from './routes/jobs.js';
import { linksRouter } from './routes/links.js';
import { documentsRouter } from './routes/documents.js';
import { chatRouter } from './routes/chat.js';
import { wikiRouter } from './routes/wiki.js';
import { adminRouter } from './routes/admin.js';

export function createApp(): Hono {
  const app = new Hono();

  // Initialize SQLite database tables
  getDb();

  // Normalize trailing slashes: e.g. /file/?skip=0 -> /file?skip=0
  app.use('*', async (c, next) => {
    const url = new URL(c.req.url);
    if (url.pathname.length > 1 && url.pathname.endsWith('/')) {
      url.pathname = url.pathname.slice(0, -1);
      return app.fetch(new Request(url.toString(), c.req.raw));
    }
    await next();
  });

  // Enable CORS
  app.use(
    '*',
    cors({
      origin: '*',
      allowMethods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
      allowHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
      exposeHeaders: ['Content-Length', 'Content-Disposition'],
      maxAge: 86400,
    })
  );

  // Root & Health
  app.get('/', (c) => c.json({ message: 'wenjv API 运行中' }));
  app.get('/ping', (c) => c.json({ message: 'pong' }));
  app.get('/health', async (c) => {
    let dbStatus = 'unreachable';
    let dbError: string | undefined;
    try {
      const db = getDb();
      db.prepare('SELECT 1').get();
      dbStatus = 'connected';
    } catch (err: unknown) {
      dbError = err instanceof Error ? err.message : String(err);
    }

    let vsStatus = 'unreachable';
    let vsError: string | undefined;
    try {
      const lanceDir = config.resolvedLanceDir;
      if (fs.existsSync(lanceDir)) {
        const lancedb = await import('@lancedb/lancedb');
        const ldb = await lancedb.connect(lanceDir);
        const tables = await ldb.tableNames();
        if (tables.includes(config.VECTOR_STORE_COLLECTION_NAME)) {
          vsStatus = 'ready';
        } else {
          vsStatus = 'table_missing';
        }
      } else {
        vsStatus = 'ready';
      }
    } catch (err: unknown) {
      vsError = err instanceof Error ? err.message : String(err);
    }

    const res: Record<string, unknown> = {
      status: dbStatus === 'connected' ? 'ok' : 'degraded',
      db: dbStatus,
      vector_store: vsStatus,
    };
    if (dbError) res['db_error'] = dbError;
    if (vsError) res['vector_store_error'] = vsError;
    return c.json(res);
  });

  // Mount routers
  app.route('/auth', authRouter);
  app.route('/file', filesRouter);
  app.route('/jobs', jobsRouter);
  app.route('/links', linksRouter);

  // Both prefixed and unprefixed for backward compatibility
  app.route('/documents', documentsRouter);
  app.route('/api/documents', documentsRouter);

  app.route('/chat', chatRouter);
  app.route('/api/chat', chatRouter);

  app.route('/wiki', wikiRouter);
  app.route('/api/wiki', wikiRouter);

  app.route('/admin', adminRouter);

  return app;
}

export function startServer(): void {
  const app = createApp();
  startJobRunner();

  console.log(`Starting wenjv TypeScript server on http://${config.HOST}:${config.PORT}...`);
  serve({
    fetch: app.fetch,
    port: config.PORT,
    hostname: config.HOST,
  });
}

// Start if run directly
const isDirectEntry =
  Boolean(process.argv[1]) &&
  path.resolve(process.argv[1]!) === fileURLToPath(import.meta.url);

if (isDirectEntry && process.env['NODE_ENV'] !== 'test' && !process.env['VITEST']) {
  startServer();
}

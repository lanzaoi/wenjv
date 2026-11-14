import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Hono, type Context } from 'hono';
import { serve } from '@hono/node-server';
import { cors } from 'hono/cors';
import { config } from './config.js';
import { getDb } from './db/index.js';
import { startJobRunner } from './services/jobs.js';
import { authRouter } from './routes/auth.js';
import { resourcesRouter } from './routes/resources.js';
import { searchRouter } from './routes/search.js';
import { tagsRouter } from './routes/tags.js';
import { assetsRouter } from './routes/assets.js';
import { jobsRouter } from './routes/jobs.js';
import { chatRouter } from './routes/chat.js';
import { wikiRouter } from './routes/wiki.js';
import { adminRouter } from './routes/admin.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const STATIC_MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
};

function resolveWebDistDir(): string | null {
  if (process.env['SERVE_STATIC'] === 'false') return null;
  const candidates = [
    process.env['WENJV_WEB_DIST'],
    path.resolve(__dirname, '../../web/dist'),
    path.resolve(__dirname, '../../../web/dist'),
  ].filter((p): p is string => Boolean(p));

  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, 'index.html'))) {
      return dir;
    }
  }
  return null;
}

function wantsHtmlBrowserNav(c: Context): boolean {
  if (c.req.method !== 'GET' && c.req.method !== 'HEAD') return false;
  const accept = c.req.header('accept') || '';
  return accept.includes('text/html');
}

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
  const webDistDir = resolveWebDistDir();
  const sendSpaIndex = (c: Context): Response => {
    const html = fs.readFileSync(path.join(webDistDir!, 'index.html'));
    return new Response(html, {
      status: 200,
      headers: {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-cache',
      },
    });
  };

  if (webDistDir) {
    app.use('*', async (c, next) => {
      if (c.req.method !== 'GET' && c.req.method !== 'HEAD') {
        await next();
        return;
      }
      const reqPath = new URL(c.req.url).pathname;
      if (reqPath.startsWith('/api/') || reqPath.startsWith('/assets/image')) {
        await next();
        return;
      }
      const rel = reqPath.replace(/^\/+/, '');
      if (rel) {
        const candidate = path.resolve(webDistDir, rel);
        const safePrefix = webDistDir + path.sep;
        if (candidate.startsWith(safePrefix) && fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
          const ext = path.extname(candidate).toLowerCase();
          const mime = STATIC_MIME[ext] || 'application/octet-stream';
          const cacheControl = reqPath.startsWith('/assets/')
            ? 'public, max-age=31536000, immutable'
            : 'public, max-age=3600';
          return new Response(fs.readFileSync(candidate), {
            status: 200,
            headers: {
              'Content-Type': mime,
              'Cache-Control': cacheControl,
            },
          });
        }
      }
      if (
        (reqPath === '/' || reqPath === '/admin') &&
        wantsHtmlBrowserNav(c) &&
        !c.req.header('authorization') &&
        !c.req.query('token')
      ) {
        return sendSpaIndex(c);
      }
      await next();
    });
  }

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

  // Mount unified Schema v2 routers
  app.route('/auth', authRouter);
  app.route('/resources', resourcesRouter);
  app.route('/search', searchRouter);
  app.route('/tags', tagsRouter);
  app.route('/assets', assetsRouter);
  app.route('/jobs', jobsRouter);
  app.route('/chat', chatRouter);
  app.route('/wiki', wikiRouter);
  app.route('/admin', adminRouter);

  // Prefix-safe /api aliases for direct API clients without proxy path rewrite
  app.route('/api/auth', authRouter);
  app.route('/api/resources', resourcesRouter);
  app.route('/api/search', searchRouter);
  app.route('/api/tags', tagsRouter);
  app.route('/api/assets', assetsRouter);
  app.route('/api/jobs', jobsRouter);
  app.route('/api/chat', chatRouter);
  app.route('/api/wiki', wikiRouter);
  app.route('/api/admin', adminRouter);

  if (webDistDir) {
    app.notFound((c) => {
      const reqPath = new URL(c.req.url).pathname;
      if (wantsHtmlBrowserNav(c) && !reqPath.startsWith('/api/')) {
        return sendSpaIndex(c);
      }
      return c.json({ detail: 'Not Found' }, 404);
    });
  }

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

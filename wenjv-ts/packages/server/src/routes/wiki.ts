import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import sharp from 'sharp';
import { getDb } from '../db/index.js';
import { matchFts5 } from '../db/fts5.js';
import { authMiddleware, type AuthUser } from '../auth/middleware.js';
import { streamChatCompletions, type ChatMessage } from '../ai/llm-chat.js';
import { registerAsset } from '../services/assets.js';
import { config } from '../config.js';
import {
  ConflictError,
  getWikiTree,
  getWikiPage,
  createWikiPage,
  updateWikiPage,
  deleteWikiPage,
  moveWikiPage,
  getWikiRevisions,
  rollbackWikiPage,
  getWikiGraph,
  findUnlinkedMentions,
  findPlainMentionRange,
} from '../services/wiki.js';

export const wikiRouter = new Hono();

// GET /wiki/tree
wikiRouter.get('/tree', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const tree = getWikiTree(user.id);
  return c.json(tree);
});

// POST /wiki/pages
wikiRouter.post('/pages', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const json = await c.req.json();

  const title = String(json.title || '').trim();
  if (!title) {
    return c.json({ detail: 'Missing title' }, 400);
  }

  const content = String(json.content || '');
  const parentId = json.parent_id !== undefined && json.parent_id !== null ? Number(json.parent_id) : null;
  const icon = json.icon ? String(json.icon) : undefined;
  const tags = Array.isArray(json.tags) ? json.tags : undefined;

  try {
    const page = createWikiPage({
      userId: user.id,
      userEmail: user.email,
      title,
      content,
      parentId,
      icon,
      tags,
    });
    return c.json(page, 201);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});

// GET /wiki/pages/:id
wikiRouter.get('/pages/:id', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const page = getWikiPage(user.id, id);
  if (!page) {
    return c.json({ detail: 'Wiki page not found' }, 404);
  }
  return c.json(page);
});

// PUT /wiki/pages/:id
wikiRouter.put('/pages/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const json = await c.req.json();
  const expectedRevNo =
    json.expected_rev_no !== undefined && json.expected_rev_no !== null
      ? Number(json.expected_rev_no)
      : undefined;

  try {
    const page = updateWikiPage({
      userId: user.id,
      userEmail: user.email,
      pageId: id,
      title: json.title !== undefined ? String(json.title) : undefined,
      content: json.content !== undefined ? String(json.content) : undefined,
      icon: json.icon !== undefined ? String(json.icon) : undefined,
      tags: Array.isArray(json.tags) ? json.tags : undefined,
      expectedRevNo,
    });
    return c.json(page);
  } catch (err: unknown) {
    if (err instanceof ConflictError) {
      return c.json({ detail: err.message }, 409);
    }
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});

// DELETE /wiki/pages/:id
wikiRouter.delete('/pages/:id', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const ok = await deleteWikiPage(user.id, id);
  if (!ok) {
    return c.json({ detail: 'Wiki page not found' }, 404);
  }
  return c.body(null, 204);
});

// POST /wiki/pages/:id/move
wikiRouter.post('/pages/:id/move', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const json = await c.req.json();

  const targetParentId =
    json.target_parent_id !== undefined && json.target_parent_id !== null ? Number(json.target_parent_id) : null;
  const sortOrder = json.sort_order !== undefined ? Number(json.sort_order) : 0;

  try {
    const page = moveWikiPage(user.id, user.email, id, targetParentId, sortOrder);
    return c.json(page);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});

// GET /wiki/pages/:id/revisions
wikiRouter.get('/pages/:id/revisions', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const revisions = getWikiRevisions(user.id, id);
  return c.json(revisions);
});

// POST /wiki/pages/:id/rollback/:rev
wikiRouter.post('/pages/:id/rollback/:rev', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const rev = parseInt(c.req.param('rev') || '0', 10);

  try {
    const page = rollbackWikiPage(user.id, user.email, id, rev);
    return c.json(page);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: msg }, 400);
  }
});

// POST /wiki/pages/:id/assets
wikiRouter.post('/pages/:id/assets', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const page = getWikiPage(user.id, id);
  if (!page) {
    return c.json({ detail: 'Wiki page not found' }, 404);
  }

  const body = await c.req.parseBody();
  const file = body['file'];
  if (!file || !(file instanceof File)) {
    return c.json({ detail: 'Missing image file' }, 400);
  }

  const origName = file.name || 'image.jpg';
  const ext = path.extname(origName).toLowerCase();
  const allowed = ['.jpg', '.jpeg', '.png', '.webp'];
  if (!allowed.includes(ext)) {
    return c.json({ detail: 'Invalid image extension' }, 400);
  }

  const arrayBuf = await file.arrayBuffer();
  const rawBytes = Buffer.from(arrayBuf);
  if (rawBytes.length > config.MAX_UPLOAD_BYTES) {
    return c.json({ detail: 'File size exceeds limit' }, 413);
  }

  let stdBytes: Buffer;
  try {
    stdBytes = await sharp(rawBytes)
      .rotate()
      .resize(1280, 1280, { fit: 'inside', withoutEnlargement: true })
      .jpeg({ quality: 85 })
      .toBuffer();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return c.json({ detail: `Invalid image: ${msg}` }, 400);
  }

  const assetId = crypto.randomUUID().slice(0, 12);
  const filename = `${assetId}.jpg`;
  const resId = String(page.id);
  const targetDir = path.join(config.resolvedUploadDir, 'mm_assets', resId);
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }

  const savedPath = path.join(targetDir, filename);
  fs.writeFileSync(savedPath, stdBytes);

  const safeTitle = origName.replace(/[\[\]\|]/g, '').trim() || 'image.jpg';
  const relPath = `mm_assets/${resId}/${filename}`;
  const asset = await registerAsset({
    id: assetId,
    userId: user.id,
    ownerType: 'wiki',
    ownerId: page.id,
    filename: origName,
    relPath,
    absPath: savedPath,
    mimeType: 'image/jpeg',
    size: stdBytes.length,
    caption: safeTitle,
    bytesForVisualIndex: stdBytes,
  });

  const markdownTag = `![[visual:${resId}/${filename}|${safeTitle}]]`;

  return c.json({
    id: asset.id,
    asset_id: filename,
    resource_id: resId,
    saved_path: savedPath,
    markdown_tag: markdownTag,
  });
});

function computeRevisionDiff(
  contentA: string,
  contentB: string
): Array<{ type: 'add' | 'del' | 'same'; content: string }> {
  const linesA = contentA.split('\n');
  const linesB = contentB.split('\n');

  const m = linesA.length;
  const n = linesB.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));

  for (let i = 0; i < m; i++) {
    for (let j = 0; j < n; j++) {
      if (linesA[i] === linesB[j]) {
        dp[i + 1]![j + 1] = dp[i]![j]! + 1;
      } else {
        dp[i + 1]![j + 1] = Math.max(dp[i + 1]![j]!, dp[i]![j + 1]!);
      }
    }
  }

  let i = m;
  let j = n;
  const reversed: Array<{ type: 'add' | 'del' | 'same'; content: string }> = [];
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && linesA[i - 1] === linesB[j - 1]) {
      reversed.push({ type: 'same', content: linesA[i - 1]! });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i]![j - 1]! >= dp[i - 1]![j]!)) {
      reversed.push({ type: 'add', content: linesB[j - 1]! });
      j--;
    } else if (i > 0) {
      reversed.push({ type: 'del', content: linesA[i - 1]! });
      i--;
    }
  }

  return reversed.reverse();
}

// GET /wiki/pages/:id/diff
wikiRouter.get('/pages/:id/diff', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const fromRev = parseInt(c.req.query('from_rev') || '0', 10);
  const toRev = parseInt(c.req.query('to_rev') || '0', 10);

  const page = getWikiPage(user.id, id);
  if (!page) {
    return c.json({ detail: 'Wiki page not found' }, 404);
  }

  const db = getDb();
  const revA = db
    .prepare('SELECT content FROM wiki_revisions WHERE user_id = ? AND page_id = ? AND rev_no = ?')
    .get(user.id, id, fromRev) as { content: string } | undefined;
  const revB = db
    .prepare('SELECT content FROM wiki_revisions WHERE user_id = ? AND page_id = ? AND rev_no = ?')
    .get(user.id, id, toRev) as { content: string } | undefined;

  if (!revA || !revB) {
    return c.json({ detail: 'Specified revisions not found' }, 404);
  }

  const diffLines = computeRevisionDiff(revA.content || '', revB.content || '');
  return c.json({
    from_rev: fromRev,
    to_rev: toRev,
    diff_lines: diffLines,
  });
});

// GET /wiki/pages/:id/unlinked-mentions
wikiRouter.get('/pages/:id/unlinked-mentions', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const page = getWikiPage(user.id, id);
  if (!page) {
    return c.json({ detail: 'Wiki page not found' }, 404);
  }

  return c.json(findUnlinkedMentions(user.id, page));
});

// POST /wiki/pages/:id/link-mention
wikiRouter.post('/pages/:id/link-mention', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const page = getWikiPage(user.id, id);
  if (!page) {
    return c.json({ detail: 'Wiki page not found' }, 404);
  }

  const json = await c.req.json();
  const sourcePageId = Number(json.source_page_id);
  const sourcePage = getWikiPage(user.id, sourcePageId);
  if (!sourcePage) {
    return c.json({ detail: 'Source page not found' }, 404);
  }

  const lines = (sourcePage.content || '').split('\n');
  let inFence = false;
  let replaced = false;
  const newLines: string[] = [];

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      newLines.push(line);
      continue;
    }
    if (!inFence && !replaced) {
      const range = findPlainMentionRange(line, page.title);
      if (range) {
        const [start, end] = range;
        const matchedText = line.slice(start, end);
        const linkText = matchedText === page.title ? `[[${page.title}]]` : `[[${page.title}|${matchedText}]]`;
        newLines.push(line.slice(0, start) + linkText + line.slice(end));
        replaced = true;
        continue;
      }
    }
    newLines.push(line);
  }

  if (!replaced) {
    return c.json({ detail: 'Mention not found or already linked' }, 400);
  }

  updateWikiPage({
    userId: user.id,
    userEmail: user.email,
    pageId: sourcePageId,
    content: newLines.join('\n'),
    expectedRevNo: sourcePage.revision_count,
  });

  return c.json({ status: 'ok', message: `Linked mention in page ${sourcePageId}` });
});

// POST /wiki/pages/:id/copilot
wikiRouter.post('/pages/:id/copilot', authMiddleware, async (c) => {
  const user = c.get('user') as AuthUser;
  const id = parseInt(c.req.param('id') || '0', 10);
  const page = getWikiPage(user.id, id);
  if (!page) {
    return c.json({ detail: 'Wiki page not found' }, 404);
  }

  const json = await c.req.json();
  const question = String(json.question || '').trim();
  if (!question) {
    return c.json({ detail: 'Missing question' }, 400);
  }

  return streamSSE(c, async (stream) => {
    const messages: ChatMessage[] = [
      {
        role: 'system',
        content: `You are an AI Copilot for Wiki page "${page.title}". Answer the user's question accurately using the page context.\n\nWiki Page Content:\n${page.content}`,
      },
      {
        role: 'user',
        content: question,
      },
    ];

    try {
      for await (const token of streamChatCompletions({ model: config.CHAT_MODEL, messages })) {
        await stream.writeSSE({
          data: JSON.stringify({ type: 'token', content: token }),
        });
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      await stream.writeSSE({
        data: JSON.stringify({ type: 'error', error: errMsg }),
      });
    }

    await stream.writeSSE({
      data: JSON.stringify({ type: 'done' }),
    });
  });
});

// GET /wiki/graph
wikiRouter.get('/graph', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const graph = getWikiGraph(user.id);
  return c.json(graph);
});

// GET /wiki/search
wikiRouter.get('/search', authMiddleware, (c) => {
  const user = c.get('user') as AuthUser;
  const q = (c.req.query('q') || '').trim();
  if (!q) {
    return c.json([]);
  }

  const db = getDb();
  const results: Array<{
    id: number;
    title: string;
    slug: string;
    path: string;
    icon: string;
    snippet: string;
    match_source: 'title' | 'content';
  }> = [];
  const seenIds = new Set<number>();

  // 1. Search title prefix/fuzzy
  const titleMatches = db
    .prepare('SELECT id, title, slug, path, icon, content FROM wiki_pages WHERE user_id = ? AND title LIKE ? ORDER BY updated_at DESC LIMIT 15')
    .all(user.id, `%${q}%`) as Array<{ id: number; title: string; slug: string; path: string; icon: string | null; content: string }>;

  for (const p of titleMatches) {
    seenIds.add(p.id);
    results.push({
      id: p.id,
      title: p.title,
      slug: p.slug,
      path: p.path,
      icon: p.icon || '',
      snippet: (p.content || '').slice(0, 100),
      match_source: 'title',
    });
  }

  // 2. Search content via FTS5 if fewer than 15
  if (results.length < 15) {
    try {
      const ftsHits = matchFts5(db, q, {
        userId: user.id,
        resourceType: 'wiki',
        limit: 15 - results.length,
      });

      for (const hit of ftsHits) {
        const resId = Number(hit.entity_id);
        if (resId && !seenIds.has(resId)) {
          seenIds.add(resId);
          results.push({
            id: resId,
            title: hit.title || 'Untitled',
            slug: hit.source ? hit.source.replace(/\.md$/, '') : '',
            path: '',
            icon: '',
            snippet: (hit.content || '').slice(0, 120),
            match_source: 'content',
          });
        }
      }
    } catch {
      // ignore
    }
  }

  return c.json(results);
});

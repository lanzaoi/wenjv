import fs from 'node:fs';
import path from 'node:path';
import { getDb } from '../db/index.js';
import { config } from '../config.js';
import { enqueueJob } from './jobs.js';
import { deleteByResourceId } from '../db/fts5.js';
import { getDocumentStore } from '../vector/document-store.js';

export interface WikiPageRecord {
  id: number;
  user_id: number;
  parent_id: number | null;
  path: string;
  slug: string;
  title: string;
  content: string;
  summary: string;
  sort_order: number;
  icon: string;
  tags: string;
  index_status: string;
  revision_count: number;
  created_at: string;
  updated_at: string;
}

export interface WikiTreeNode {
  id: number;
  title: string;
  slug: string;
  parent_id: number | null;
  path: string;
  icon: string;
  sort_order: number;
  index_status: string;
  children: WikiTreeNode[];
}

export interface WikiLinkNode {
  kind: 'wikilink' | 'visual';
  raw: string;
  target: string;
  alias: string | null;
  anchor: string | null;
  start: number;
  end: number;
}

export function generateSlug(title: string): string {
  let slug = title.trim().toLowerCase().replace(/[^\p{L}\p{N}_\-\u4e00-\u9fff]+/gu, '-');
  slug = slug.replace(/-+/g, '-').replace(/^-|-$/g, '');
  return slug || 'untitled';
}

export function parseWikilinks(content: string): WikiLinkNode[] {
  if (!content) return [];
  const nodes: WikiLinkNode[] = [];
  const linkRe = /\[\[([^\[\]|#\n]+)(?:#([^\[\]|\n]+))?(?:\|([^\[\]\n]+))?\]\]/g;
  const lines = content.split('\n');
  let currentOffset = 0;
  let inCodeFence = false;

  for (const line of lines) {
    const lineLen = line.length + 1; // including newline
    if (/^\s*```/.test(line)) {
      inCodeFence = !inCodeFence;
      currentOffset += lineLen;
      continue;
    }

    if (!inCodeFence) {
      let match: RegExpExecArray | null;
      while ((match = linkRe.exec(line)) !== null) {
        const raw = match[0];
        const rawTarget = match[1]?.trim() || '';
        const rawAnchor = match[2]?.trim() || null;
        const rawAlias = match[3]?.trim() || null;

        const lineMatchStart = match.index;
        let isVisual = false;
        let matchedRaw = raw;
        let actualStart = currentOffset + lineMatchStart;

        if (lineMatchStart > 0 && line[lineMatchStart - 1] === '!') {
          isVisual = true;
          matchedRaw = '!' + raw;
          actualStart -= 1;
        }

        let target = rawTarget;
        if (rawTarget.toLowerCase().startsWith('visual:')) {
          isVisual = true;
          target = rawTarget.slice(7).trim();
        }

        nodes.push({
          kind: isVisual ? 'visual' : 'wikilink',
          raw: matchedRaw,
          target,
          alias: rawAlias,
          anchor: rawAnchor,
          start: actualStart,
          end: currentOffset + match.index + raw.length,
        });
      }
    }

    currentOffset += lineLen;
  }

  return nodes;
}

export function syncPageToVault(userId: number, slug: string, title: string, content: string): void {
  try {
    const safeSlug = generateSlug(slug);
    const vaultDir = path.join(config.resolvedVaultDir, String(userId));
    if (!fs.existsSync(vaultDir)) {
      fs.mkdirSync(vaultDir, { recursive: true });
    }
    const filePath = path.join(vaultDir, `${safeSlug}.md`);
    const frontmatter = `---\ntitle: ${JSON.stringify(title)}\nslug: ${JSON.stringify(slug)}\n---\n\n`;
    fs.writeFileSync(filePath, frontmatter + content, 'utf8');
  } catch {
    // ignore vault write error
  }
}

export function removePageFromVault(userId: number, slug: string): void {
  try {
    const safeSlug = generateSlug(slug);
    const filePath = path.join(config.resolvedVaultDir, String(userId), `${safeSlug}.md`);
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
  } catch {
    // ignore
  }
}

export function getWikiTree(userId: number): WikiTreeNode[] {
  const db = getDb();
  const pages = db
    .prepare('SELECT * FROM wiki_pages WHERE user_id = ? ORDER BY parent_id ASC NULLS FIRST, sort_order ASC, id ASC')
    .all(userId) as WikiPageRecord[];

  const nodesById = new Map<number, WikiTreeNode>();
  const roots: WikiTreeNode[] = [];

  for (const p of pages) {
    const node: WikiTreeNode = {
      id: p.id,
      title: p.title,
      slug: p.slug,
      parent_id: p.parent_id,
      path: p.path,
      icon: p.icon || '',
      sort_order: p.sort_order,
      index_status: p.index_status,
      children: [],
    };
    nodesById.set(p.id, node);
  }

  for (const p of pages) {
    const node = nodesById.get(p.id)!;
    if (p.parent_id && nodesById.has(p.parent_id)) {
      nodesById.get(p.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

export function getWikiPage(userId: number, pageId: number): WikiPageRecord | null {
  const db = getDb();
  return (db.prepare('SELECT * FROM wiki_pages WHERE id = ? AND user_id = ?').get(pageId, userId) as WikiPageRecord) || null;
}

export interface CreateWikiPageParams {
  userId: number;
  userEmail: string;
  title: string;
  content: string;
  parentId?: number | null | undefined;
  icon?: string | undefined;
  tags?: string[] | undefined;
}

export function createWikiPage(params: CreateWikiPageParams): WikiPageRecord {
  const db = getDb();
  const slug = generateSlug(params.title);

  // Compute materialized path
  let parentPath = '/';
  if (params.parentId) {
    const parent = db.prepare('SELECT path FROM wiki_pages WHERE id = ? AND user_id = ?').get(params.parentId, params.userId) as
      | { path: string }
      | undefined;
    if (parent) {
      parentPath = parent.path;
    }
  }

  const tagsJson = JSON.stringify(params.tags || []);
  const res = db
    .prepare(`
      INSERT INTO wiki_pages(
        user_id, parent_id, path, slug, title, content, summary, sort_order, icon, tags, index_status, revision_count
      )
      VALUES (?, ?, ?, ?, ?, ?, '', 0, ?, ?, 'pending', 1)
    `)
    .run(
      params.userId,
      params.parentId || null,
      parentPath,
      slug,
      params.title,
      params.content,
      params.icon || '',
      tagsJson
    );

  const pageId = Number(res.lastInsertRowid);
  const fullPath = `${parentPath}${pageId}/`;
  db.prepare('UPDATE wiki_pages SET path = ? WHERE id = ?').run(fullPath, pageId);

  // Revision 1
  db.prepare(`
    INSERT INTO wiki_revisions(page_id, user_id, rev_no, title, content, char_count)
    VALUES (?, ?, 1, ?, ?, ?)
  `).run(pageId, params.userId, params.title, params.content, params.content.length);

  // Sync to vault
  syncPageToVault(params.userId, slug, params.title, params.content);

  // Update links
  updatePageLinks(params.userId, pageId, params.content);

  // Enqueue wiki indexing job
  enqueueJob({
    job_type: 'wiki',
    resource_id: pageId,
    user_id: params.userId,
    user_email: params.userEmail,
  });

  return getWikiPage(params.userId, pageId)!;
}

export interface UpdateWikiPageParams {
  userId: number;
  userEmail: string;
  pageId: number;
  title?: string | undefined;
  content?: string | undefined;
  icon?: string | undefined;
  tags?: string[] | undefined;
}

export function updateWikiPage(params: UpdateWikiPageParams): WikiPageRecord {
  const db = getDb();
  const current = getWikiPage(params.userId, params.pageId);
  if (!current) throw new Error('Wiki page not found');

  const newTitle = params.title !== undefined ? params.title : current.title;
  const newContent = params.content !== undefined ? params.content : current.content;
  const newIcon = params.icon !== undefined ? params.icon : current.icon;
  const newTags = params.tags !== undefined ? JSON.stringify(params.tags) : current.tags;
  const contentChanged = newContent !== current.content || newTitle !== current.title;

  let revCount = current.revision_count;
  if (contentChanged) {
    revCount += 1;
    // Cap revisions to last 10
    db.prepare(`
      INSERT INTO wiki_revisions(page_id, user_id, rev_no, title, content, char_count)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(params.pageId, params.userId, revCount, newTitle, newContent, newContent.length);

    db.prepare(`
      DELETE FROM wiki_revisions
      WHERE page_id = ? AND rev_no < ?
    `).run(params.pageId, revCount - 10);
  }

  db.prepare(`
    UPDATE wiki_pages
    SET title = ?,
        content = ?,
        icon = ?,
        tags = ?,
        revision_count = ?,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ? AND user_id = ?
  `).run(newTitle, newContent, newIcon, newTags, revCount, params.pageId, params.userId);

  syncPageToVault(params.userId, current.slug, newTitle, newContent);
  updatePageLinks(params.userId, params.pageId, newContent);

  if (contentChanged) {
    enqueueJob({
      job_type: 'wiki',
      resource_id: params.pageId,
      user_id: params.userId,
      user_email: params.userEmail,
    });
  }

  return getWikiPage(params.userId, params.pageId)!;
}

export async function deleteWikiPage(userId: number, pageId: number): Promise<boolean> {
  const db = getDb();
  const current = getWikiPage(userId, pageId);
  if (!current) return false;

  removePageFromVault(userId, current.slug);

  db.prepare('DELETE FROM wiki_revisions WHERE page_id = ?').run(pageId);
  db.prepare('DELETE FROM wiki_links WHERE source_page_id = ? OR target_page_id = ?').run(pageId, pageId);
  db.prepare('DELETE FROM wiki_aliases WHERE page_id = ?').run(pageId);
  db.prepare('DELETE FROM wiki_pages WHERE id = ? AND user_id = ?').run(pageId, userId);

  deleteByResourceId(db, String(pageId), String(userId));
  const docStore = getDocumentStore();
  await docStore.deleteByResourceId(String(pageId), userId);

  return true;
}

export function moveWikiPage(userId: number, pageId: number, targetParentId: number | null, sortOrder = 0): WikiPageRecord {
  const db = getDb();
  const current = getWikiPage(userId, pageId);
  if (!current) throw new Error('Wiki page not found');

  if (targetParentId === pageId) {
    throw new Error('Cannot move page to itself');
  }

  let newParentPath = '/';
  if (targetParentId) {
    const targetParent = getWikiPage(userId, targetParentId);
    if (!targetParent) throw new Error('Target parent page not found');
    if (targetParent.path.includes(`/${pageId}/`)) {
      throw new Error('Cycle detected: cannot move page into its own descendant');
    }
    newParentPath = targetParent.path;
  }

  const newPath = `${newParentPath}${pageId}/`;
  const oldPath = current.path;

  db.prepare(`
    UPDATE wiki_pages
    SET parent_id = ?, path = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ? AND user_id = ?
  `).run(targetParentId, newPath, sortOrder, pageId, userId);

  // Update descendant paths
  const descendants = db.prepare('SELECT id, path FROM wiki_pages WHERE user_id = ? AND path LIKE ?').all(userId, `${oldPath}%`) as { id: number; path: string }[];
  for (const d of descendants) {
    const updatedDescPath = d.path.replace(oldPath, newPath);
    db.prepare('UPDATE wiki_pages SET path = ? WHERE id = ?').run(updatedDescPath, d.id);
  }

  return getWikiPage(userId, pageId)!;
}

export function getWikiRevisions(userId: number, pageId: number): Array<{ rev_no: number; title: string; char_count: number; created_at: string }> {
  const db = getDb();
  return db
    .prepare('SELECT rev_no, title, char_count, created_at FROM wiki_revisions WHERE page_id = ? AND user_id = ? ORDER BY rev_no DESC')
    .all(pageId, userId) as Array<{ rev_no: number; title: string; char_count: number; created_at: string }>;
}

export function rollbackWikiPage(userId: number, userEmail: string, pageId: number, revNo: number): WikiPageRecord {
  const db = getDb();
  const rev = db
    .prepare('SELECT title, content FROM wiki_revisions WHERE page_id = ? AND user_id = ? AND rev_no = ?')
    .get(pageId, userId, revNo) as { title: string; content: string } | undefined;

  if (!rev) throw new Error(`Revision ${revNo} not found`);

  return updateWikiPage({
    userId,
    userEmail,
    pageId,
    title: rev.title,
    content: rev.content,
  });
}

function updatePageLinks(userId: number, pageId: number, content: string): void {
  const db = getDb();
  const links = parseWikilinks(content);
  db.prepare('DELETE FROM wiki_links WHERE source_page_id = ? AND user_id = ?').run(pageId, userId);

  const insertStmt = db.prepare(`
    INSERT OR IGNORE INTO wiki_links(user_id, source_page_id, target_page_id, target_title, alias, link_type, section_anchor)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);

  for (const l of links) {
    if (l.kind === 'wikilink') {
      const targetPage = db
        .prepare('SELECT id FROM wiki_pages WHERE user_id = ? AND (title = ? OR slug = ?)')
        .get(userId, l.target, generateSlug(l.target)) as { id: number } | undefined;

      insertStmt.run(
        userId,
        pageId,
        targetPage ? targetPage.id : null,
        l.target,
        l.alias || null,
        'wikilink',
        l.anchor || null
      );
    }
  }
}

export function getWikiGraph(userId: number): { nodes: Array<{ id: number; title: string; slug: string }>; links: Array<{ source: number; target: number; label: string }> } {
  const db = getDb();
  const pages = db.prepare('SELECT id, title, slug FROM wiki_pages WHERE user_id = ?').all(userId) as Array<{ id: number; title: string; slug: string }>;
  const rawLinks = db
    .prepare('SELECT source_page_id, target_page_id, target_title FROM wiki_links WHERE user_id = ? AND target_page_id IS NOT NULL')
    .all(userId) as Array<{ source_page_id: number; target_page_id: number; target_title: string }>;

  const links = rawLinks.map((l) => ({
    source: l.source_page_id,
    target: l.target_page_id,
    label: l.target_title,
  }));

  return { nodes: pages, links };
}

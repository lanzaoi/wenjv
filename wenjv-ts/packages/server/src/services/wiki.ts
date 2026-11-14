import fs from 'node:fs';
import path from 'node:path';
import { getDb } from '../db/index.js';
import { config } from '../config.js';
import { enqueueJob } from './jobs.js';
import { deleteEntityChunks } from '../db/chunks.js';
import { getTextStore } from '../vector/text-store.js';
import { setEntityTags, getEntityTags, deleteEntityTags } from './tags.js';
import { deleteAssetsByOwner } from './assets.js';
import { getResource, deleteUserResource } from './resources.js';

export class ConflictError extends Error {
  readonly status = 409;
  constructor(message: string) {
    super(message);
    this.name = 'ConflictError';
  }
}

export class NotFoundError extends Error {
  readonly status = 404;
  constructor(message: string) {
    super(message);
    this.name = 'NotFoundError';
  }
}

export class ValidationError extends Error {
  readonly status = 400;
  constructor(message: string) {
    super(message);
    this.name = 'ValidationError';
  }
}

export class VaultSecurityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'VaultSecurityError';
  }
}

export interface WikiBacklinkItem {
  source_page_id: number;
  source_title: string;
  target_title: string;
  alias: string;
  section_anchor: string;
}

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
  tags: string[];
  backlinks?: WikiBacklinkItem[];
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

export function normalizeTitle(title: string): string {
  return String(title || '')
    .replace(/[\r\n\t]+/g, ' ')
    .trim();
}

export function generateSlug(title: string): string {
  let slug = String(title || '')
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_\-\u4e00-\u9fff]+/gu, '-');
  slug = slug.replace(/-+/g, '-').replace(/^-|-$/g, '');
  return slug || 'untitled';
}

export function escapeLike(input: string): string {
  return input.replace(/[\\%_]/g, (ch) => `\\${ch}`);
}

export function parseWikilinks(content: string): WikiLinkNode[] {
  if (!content) return [];
  const nodes: WikiLinkNode[] = [];
  const linkRe = /\[\[([^\[\]|#\n]+)(?:#([^\[\]|\n]*))?(?:\|([^\[\]\n]*))?\]\]/g;
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
      linkRe.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = linkRe.exec(line)) !== null) {
        const raw = match[0];
        const rawTarget = (match[1] ?? '').trim();
        const rawAnchor = match[2] !== undefined ? match[2].trim() : null;
        const rawAlias = match[3] !== undefined ? match[3].trim() : null;

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

export function rewriteLinksInContent(
  content: string,
  oldTitle: string,
  newTitle: string
): { content: string; changed: boolean } {
  if (!content || oldTitle === newTitle) {
    return { content, changed: false };
  }

  const nodes = parseWikilinks(content);
  const replacements: Array<{ start: number; end: number; text: string }> = [];

  for (const node of nodes) {
    if (node.kind !== 'wikilink') continue;
    if (node.target !== oldTitle) continue;

    const inner = node.raw.slice(2, -2);
    const suffixIdx = inner.search(/[#|]/);
    const suffix = suffixIdx >= 0 ? inner.slice(suffixIdx) : '';
    replacements.push({
      start: node.start,
      end: node.end,
      text: `[[${newTitle}${suffix}]]`,
    });
  }

  if (replacements.length === 0) {
    return { content, changed: false };
  }

  let out = '';
  let cursor = 0;
  for (const rep of replacements) {
    out += content.slice(cursor, rep.start) + rep.text;
    cursor = rep.end;
  }
  out += content.slice(cursor);

  return { content: out, changed: out !== content };
}

function resolveSafeVaultFile(userId: number, slug: string): { vaultDir: string; filePath: string } {
  const rawSlug = String(slug || '').trim();
  if (!rawSlug || rawSlug === '.' || rawSlug === '..' || rawSlug.includes('/') || rawSlug.includes('\\')) {
    throw new VaultSecurityError(`Unsafe wiki vault slug rejected (path traversal): ${rawSlug}`);
  }

  const safeSlug = generateSlug(rawSlug);
  const vaultRoot = path.resolve(config.resolvedVaultDir);
  if (!fs.existsSync(vaultRoot)) {
    fs.mkdirSync(vaultRoot, { recursive: true });
  }

  const userVaultDir = path.resolve(vaultRoot, String(userId));
  if (!userVaultDir.startsWith(vaultRoot + path.sep)) {
    throw new VaultSecurityError('Vault user directory escapes root');
  }
  if (!fs.existsSync(userVaultDir)) {
    fs.mkdirSync(userVaultDir, { recursive: true });
  }

  const userDirStat = fs.lstatSync(userVaultDir);
  if (userDirStat.isSymbolicLink()) {
    throw new VaultSecurityError('Vault user directory cannot be a symlink');
  }

  const realRoot = fs.realpathSync(vaultRoot);
  const realUserDir = fs.realpathSync(userVaultDir);
  if (!realUserDir.startsWith(realRoot + path.sep) && realUserDir !== realRoot) {
    throw new VaultSecurityError('Vault user directory realpath escapes root');
  }

  const filePath = path.resolve(userVaultDir, `${safeSlug}.md`);
  if (!filePath.startsWith(userVaultDir + path.sep)) {
    throw new VaultSecurityError('Vault target file escapes user vault directory');
  }

  if (fs.existsSync(filePath)) {
    const stat = fs.lstatSync(filePath);
    if (stat.isSymbolicLink()) {
      throw new VaultSecurityError(`Refusing vault operation on symlink target: ${filePath}`);
    }
  }

  return { vaultDir: userVaultDir, filePath };
}

export function syncPageToVault(userId: number, slug: string, title: string, content: string): void {
  const { filePath } = resolveSafeVaultFile(userId, slug);
  const frontmatter = `---\ntitle: ${JSON.stringify(title)}\nslug: ${JSON.stringify(slug)}\n---\n\n`;
  fs.writeFileSync(filePath, frontmatter + content, 'utf8');
}

export function removePageFromVault(userId: number, slug: string): void {
  const { filePath } = resolveSafeVaultFile(userId, slug);
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
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

function getWikiBacklinks(db: ReturnType<typeof getDb>, userId: number, pageId: number): WikiBacklinkItem[] {
  return db
    .prepare(`
      SELECT DISTINCT
        wl.source_page_id AS source_page_id,
        wp.title AS source_title,
        wl.target_title AS target_title,
        wl.alias AS alias,
        wl.section_anchor AS section_anchor
      FROM wiki_links wl
      JOIN wiki_pages wp ON wp.id = wl.source_page_id AND wp.user_id = wl.user_id
      WHERE wl.user_id = ?
        AND wl.target_page_id = ?
        AND wl.link_type = 'wikilink'
        AND wl.source_page_id != ?
      ORDER BY wp.title ASC
    `)
    .all(userId, pageId, pageId) as WikiBacklinkItem[];
}

export function getWikiPage(userId: number, pageId: number): WikiPageRecord | null {
  const db = getDb();
  const row = db.prepare('SELECT * FROM wiki_pages WHERE id = ? AND user_id = ?').get(pageId, userId) as
    | Omit<WikiPageRecord, 'tags' | 'backlinks'>
    | undefined;
  if (!row) return null;
  return {
    ...row,
    tags: getEntityTags(db, userId, 'wiki', row.id),
    backlinks: getWikiBacklinks(db, userId, row.id),
  };
}

export interface CreateWikiPageParams {
  userId: number;
  userEmail: string;
  title: string;
  content: string;
  parentId?: number | null | undefined;
  icon?: string | undefined;
  tags?: string[] | undefined;
  deduplicateSlug?: boolean | undefined;
}

function ensureUniqueSlug(userId: number, baseSlug: string): string {
  const db = getDb();
  const clean = baseSlug || 'untitled';
  let candidate = clean;
  let counter = 2;
  while (db.prepare('SELECT 1 FROM wiki_pages WHERE user_id = ? AND slug = ?').get(userId, candidate)) {
    candidate = `${clean}-${counter}`;
    counter += 1;
  }
  return candidate;
}

export function createWikiPage(params: CreateWikiPageParams): WikiPageRecord {
  const db = getDb();
  const cleanTitle = normalizeTitle(params.title);
  if (!cleanTitle) {
    throw new Error('Wiki page title cannot be empty');
  }
  const baseSlug = generateSlug(cleanTitle);
  const slug = params.deduplicateSlug ? ensureUniqueSlug(params.userId, baseSlug) : baseSlug;

  let parentPath = '/';
  if (params.parentId !== undefined && params.parentId !== null) {
    if (!Number.isSafeInteger(params.parentId) || params.parentId <= 0) {
      throw new ValidationError('Invalid parent_id');
    }
    const parent = db
      .prepare('SELECT id, path FROM wiki_pages WHERE id = ? AND user_id = ?')
      .get(params.parentId, params.userId) as { id: number; path: string } | undefined;
    if (!parent) {
      throw new NotFoundError(`Parent page ${params.parentId} not found`);
    }
    parentPath = parent.path;
  }

  const res = db
    .prepare(`
      INSERT INTO wiki_pages(
        user_id, parent_id, path, slug, title, content, summary, sort_order, icon, index_status, revision_count
      )
      VALUES (?, ?, ?, ?, ?, ?, '', 0, ?, 'pending', 1)
    `)
    .run(
      params.userId,
      params.parentId || null,
      parentPath,
      slug,
      cleanTitle,
      params.content,
      params.icon || ''
    );

  const pageId = Number(res.lastInsertRowid);
  const fullPath = `${parentPath}${pageId}/`;
  db.prepare('UPDATE wiki_pages SET path = ? WHERE id = ?').run(fullPath, pageId);

  if (params.tags && params.tags.length > 0) {
    setEntityTags(db, params.userId, 'wiki', pageId, params.tags);
  }

  db.prepare(`
    INSERT INTO wiki_revisions(page_id, user_id, rev_no, title, content, char_count)
    VALUES (?, ?, 1, ?, ?, ?)
  `).run(pageId, params.userId, cleanTitle, params.content, params.content.length);

  syncPageToVault(params.userId, slug, cleanTitle, params.content);
  updatePageLinks(params.userId, pageId, params.content);

  // Backfill any pending unresolved wikilinks that already pointed to this new title/slug
  db.prepare(`
    UPDATE wiki_links
    SET target_page_id = ?
    WHERE user_id = ?
      AND target_page_id IS NULL
      AND link_type = 'wikilink'
      AND (target_title = ? OR target_title = ?)
  `).run(pageId, params.userId, cleanTitle, slug);

  enqueueJob({
    entity_type: 'wiki',
    entity_id: pageId,
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
  expectedRevNo?: number | undefined;
}

function recordRevisionAndSync(
  userId: number,
  pageId: number,
  revCount: number,
  title: string,
  content: string
): void {
  const db = getDb();
  db.prepare(`
    INSERT INTO wiki_revisions(page_id, user_id, rev_no, title, content, char_count)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(pageId, userId, revCount, title, content, content.length);

  db.prepare(`
    DELETE FROM wiki_revisions
    WHERE page_id = ? AND rev_no < ?
  `).run(pageId, revCount - 10);
}

export function updateWikiPage(params: UpdateWikiPageParams): WikiPageRecord {
  const db = getDb();
  const current = getWikiPage(params.userId, params.pageId);
  if (!current) throw new Error('Wiki page not found');

  if (params.expectedRevNo !== undefined && current.revision_count !== params.expectedRevNo) {
    throw new ConflictError(
      `Conflict: page has been modified (current rev: ${current.revision_count}, expected: ${params.expectedRevNo}).`
    );
  }

  const newTitle = params.title !== undefined ? normalizeTitle(params.title) : current.title;
  if (!newTitle) {
    throw new Error('Wiki page title cannot be empty');
  }
  const newContent = params.content !== undefined ? params.content : current.content;
  const newIcon = params.icon !== undefined ? params.icon : current.icon;
  const titleChanged = newTitle !== current.title;
  const contentChanged = newContent !== current.content || titleChanged;

  const jobsToEnqueue: Array<{ entityId: number; payload?: Record<string, unknown> }> = [];

  const runTx = db.transaction(() => {
    let revCount = current.revision_count;
    if (contentChanged) {
      revCount += 1;
      recordRevisionAndSync(params.userId, params.pageId, revCount, newTitle, newContent);
    }

    db.prepare(`
      UPDATE wiki_pages
      SET title = ?,
          content = ?,
          icon = ?,
          revision_count = ?,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND user_id = ?
    `).run(newTitle, newContent, newIcon, revCount, params.pageId, params.userId);

    if (params.tags !== undefined) {
      setEntityTags(db, params.userId, 'wiki', params.pageId, params.tags);
    }

    updatePageLinks(params.userId, params.pageId, newContent);

    if (titleChanged) {
      // Check alias collision with another page for the same user
      const conflictingAlias = db
        .prepare('SELECT page_id FROM wiki_aliases WHERE user_id = ? AND alias_title = ?')
        .get(params.userId, current.title) as { page_id: number } | undefined;

      if (!conflictingAlias) {
        db.prepare(`
          INSERT OR IGNORE INTO wiki_aliases(page_id, user_id, alias_title)
          VALUES (?, ?, ?)
        `).run(params.pageId, params.userId, current.title);
      }

      // Update wiki_links target_title strictly for this tenant & target page
      db.prepare(`
        UPDATE wiki_links
        SET target_title = ?
        WHERE user_id = ? AND target_page_id = ? AND link_type = 'wikilink'
      `).run(newTitle, params.userId, params.pageId);

      // Rewrite links in all tenant-owned source pages pointing to this page
      const sourcePages = db
        .prepare(`
          SELECT DISTINCT wp.*
          FROM wiki_pages wp
          JOIN wiki_links wl ON wl.source_page_id = wp.id
          WHERE wp.user_id = ? AND wl.user_id = ? AND wl.target_page_id = ?
        `)
        .all(params.userId, params.userId, params.pageId) as WikiPageRecord[];

      for (const src of sourcePages) {
        if (src.id === params.pageId) continue;
        const { content: rewritten, changed } = rewriteLinksInContent(src.content || '', current.title, newTitle);
        if (!changed) continue;

        const nextSrcRev = src.revision_count + 1;
        recordRevisionAndSync(params.userId, src.id, nextSrcRev, src.title, rewritten);
        db.prepare(`
          UPDATE wiki_pages
          SET content = ?, revision_count = ?, updated_at = CURRENT_TIMESTAMP
          WHERE id = ? AND user_id = ?
        `).run(rewritten, nextSrcRev, src.id, params.userId);

        updatePageLinks(params.userId, src.id, rewritten);
        syncPageToVault(params.userId, src.slug, src.title, rewritten);
        jobsToEnqueue.push({ entityId: src.id, payload: { reason: 'title_rename_rewrite' } });
      }
    }
  });

  runTx();
  syncPageToVault(params.userId, current.slug, newTitle, newContent);

  if (contentChanged) {
    enqueueJob({
      entity_type: 'wiki',
      entity_id: params.pageId,
      user_id: params.userId,
      user_email: params.userEmail,
    });
  }

  for (const j of jobsToEnqueue) {
    enqueueJob({
      entity_type: 'wiki',
      entity_id: j.entityId,
      user_id: params.userId,
      user_email: params.userEmail,
      ...(j.payload ? { payload: j.payload } : {}),
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
  deleteEntityTags(db, userId, 'wiki', pageId);
  db.prepare('DELETE FROM wiki_pages WHERE id = ? AND user_id = ?').run(pageId, userId);

  deleteEntityChunks(db, 'wiki', pageId, userId);
  const textStore = getTextStore();
  await textStore.deleteByEntity('wiki', pageId, userId);
  await deleteAssetsByOwner(userId, 'wiki', pageId);

  return true;
}

export function moveWikiPage(
  userId: number,
  userEmail: string,
  pageId: number,
  targetParentId: number | null,
  sortOrder = 0
): WikiPageRecord {
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
  const affectedIds: number[] = [pageId];

  const runMoveTx = db.transaction(() => {
    db.prepare(`
      UPDATE wiki_pages
      SET parent_id = ?, path = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND user_id = ?
    `).run(targetParentId, newPath, sortOrder, pageId, userId);

    // Update all strict descendant paths using escaped LIKE prefix
    const escapedOldPrefix = `${escapeLike(oldPath)}%`;
    const descendants = db
      .prepare("SELECT id, path FROM wiki_pages WHERE user_id = ? AND id != ? AND path LIKE ? ESCAPE '\\'")
      .all(userId, pageId, escapedOldPrefix) as { id: number; path: string }[];

    const updateDesc = db.prepare('UPDATE wiki_pages SET path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?');
    for (const d of descendants) {
      const updatedDescPath = d.path.startsWith(oldPath)
        ? `${newPath}${d.path.slice(oldPath.length)}`
        : d.path;
      updateDesc.run(updatedDescPath, d.id, userId);
      affectedIds.push(d.id);
    }
  });

  runMoveTx();

  for (const id of affectedIds) {
    enqueueJob({
      entity_type: 'wiki',
      entity_id: id,
      user_id: userId,
      user_email: userEmail,
      payload: { reason: 'tree_move_breadcrumb_sync', moved_root_id: pageId },
    });
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

function resolveTargetPageId(userId: number, targetTitle: string): number | null {
  const db = getDb();
  const direct = db
    .prepare('SELECT id FROM wiki_pages WHERE user_id = ? AND (title = ? OR slug = ?)')
    .get(userId, targetTitle, generateSlug(targetTitle)) as { id: number } | undefined;
  if (direct) return direct.id;

  const alias = db
    .prepare('SELECT page_id FROM wiki_aliases WHERE user_id = ? AND alias_title = ?')
    .get(userId, targetTitle) as { page_id: number } | undefined;
  return alias ? alias.page_id : null;
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
    const targetPageId = l.kind === 'wikilink' ? resolveTargetPageId(userId, l.target) : null;
    insertStmt.run(
      userId,
      pageId,
      targetPageId,
      l.target,
      l.alias ?? '',
      l.kind,
      l.anchor ?? ''
    );
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

function computeExcludedSpans(line: string): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  const patterns = [
    /!?\[\[[^\[\]\n]+\]\]/g, // wikilinks & visual embeds
    /`[^`]+`/g,               // inline code
    /\[[^\]]+\]\([^)]+\)/g,   // markdown links
  ];
  for (const re of patterns) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(line)) !== null) {
      spans.push([m.index, m.index + m[0].length]);
    }
  }
  return spans;
}

export function findPlainMentionRange(line: string, targetTitle: string): [number, number] | null {
  if (!line || !targetTitle) return null;
  const excluded = computeExcludedSpans(line);
  const titleEsc = targetTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const isAsciiTitle = /^[A-Za-z0-9 _.-]+$/.test(targetTitle);
  const pattern = isAsciiTitle ? new RegExp(`(?<![A-Za-z0-9_])${titleEsc}(?![A-Za-z0-9_])`, 'gi') : new RegExp(titleEsc, 'g');

  pattern.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = pattern.exec(line)) !== null) {
    const start = m.index;
    const end = start + m[0].length;
    const overlapsExcluded = excluded.some(([s, e]) => start < e && end > s);
    if (!overlapsExcluded) {
      return [start, end];
    }
  }
  return null;
}

export function findUnlinkedMentions(
  userId: number,
  targetPage: WikiPageRecord
): Array<{ page_id: number; title: string; slug: string; mentions: Array<{ line_no: number; excerpt: string }> }> {
  const db = getDb();
  const linkedPageIds = new Set(
    (
      db
        .prepare('SELECT source_page_id FROM wiki_links WHERE user_id = ? AND target_page_id = ?')
        .all(userId, targetPage.id) as { source_page_id: number }[]
    ).map((r) => r.source_page_id)
  );

  const escapedLikeTitle = `%${escapeLike(targetPage.title)}%`;
  const candidates = db
    .prepare("SELECT id, title, slug, content FROM wiki_pages WHERE user_id = ? AND id != ? AND content LIKE ? ESCAPE '\\' LIMIT 50")
    .all(userId, targetPage.id, escapedLikeTitle) as Array<{ id: number; title: string; slug: string; content: string }>;

  const results: Array<{ page_id: number; title: string; slug: string; mentions: Array<{ line_no: number; excerpt: string }> }> = [];
  for (const cand of candidates) {
    if (linkedPageIds.has(cand.id)) continue;

    const lines = (cand.content || '').split('\n');
    let inFence = false;
    const matchesFound: Array<{ line_no: number; excerpt: string }> = [];

    for (let lineNo = 0; lineNo < lines.length; lineNo++) {
      const line = lines[lineNo]!;
      if (/^\s*```/.test(line)) {
        inFence = !inFence;
        continue;
      }
      if (!inFence && findPlainMentionRange(line, targetPage.title) !== null) {
        matchesFound.push({
          line_no: lineNo + 1,
          excerpt: line.trim().slice(0, 160),
        });
      }
    }

    if (matchesFound.length > 0) {
      results.push({
        page_id: cand.id,
        title: cand.title,
        slug: cand.slug,
        mentions: matchesFound,
      });
    }
  }

  return results;
}

export interface PromoteNoteParams {
  userId: number;
  userEmail: string;
  resourceId: number | string;
  title?: string | undefined;
  parentId?: number | null | undefined;
  archiveOriginal?: boolean | undefined;
}

/** Promote a knowledge-base note resource into a structured Wiki page, inheriting tags & assets. */
export async function promoteNoteToWiki(
  params: PromoteNoteParams
): Promise<{ page: WikiPageRecord; archivedOriginal: boolean }> {
  const current = getResource(params.userId, params.resourceId);
  if (!current) {
    throw new NotFoundError('Resource not found');
  }
  if (current.type !== 'note') {
    throw new ValidationError('Only note resources can be promoted to Wiki');
  }

  let content = current.content_text ?? '';
  if (current.file_path && fs.existsSync(current.file_path)) {
    content = fs.readFileSync(current.file_path, 'utf8');
  }

  const targetTitle = normalizeTitle(params.title || current.title) || '未命名笔记';
  const archiveOriginal = params.archiveOriginal !== false;

  const page = createWikiPage({
    userId: params.userId,
    userEmail: params.userEmail,
    title: targetTitle,
    content,
    parentId: params.parentId ?? null,
    tags: current.tags,
    deduplicateSlug: true,
  });

  if (archiveOriginal) {
    const db = getDb();
    db.prepare(`
      UPDATE assets
      SET owner_type = 'wiki', owner_id = ?
      WHERE user_id = ? AND owner_type = 'resource' AND owner_id = ?
    `).run(String(page.id), params.userId, String(current.id));

    await deleteUserResource(params.userId, current.id);
  }

  return { page, archivedOriginal: archiveOriginal };
}

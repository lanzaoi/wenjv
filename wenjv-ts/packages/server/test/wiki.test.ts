import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { getDb } from '../src/db/index.js';
import { config } from '../src/config.js';
import { syncPageToVault, removePageFromVault } from '../src/services/wiki.js';
import { setupTestEnv, type TestEnv } from './helper.js';

describe('Wiki Service & Routes (S7)', () => {
  let env: TestEnv;
  let token: string;

  beforeEach(async () => {
    env = setupTestEnv();

    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'dave@example.com',
        password: 'Password123!',
      }),
    });

    const login = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: 'dave@example.com',
        password: 'Password123!',
      }),
    });
    const loginData = (await login.json()) as { access_token: string };
    token = loginData.access_token;
  });

  afterEach(() => {
    env.cleanup();
  });

  it('creates wiki pages, maintains hierarchy, supports rollback and graph links', async () => {
    // 1. Create root wiki page
    const page1Resp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: '知识库设计',
        content: '这是知识库设计的根页面，引用 [[模块架构]]。',
      }),
    });
    expect(page1Resp.status).toBe(201);
    const page1 = (await page1Resp.json()) as { id: number; title: string; revision_count: number };
    expect(page1.title).toBe('知识库设计');
    expect(page1.revision_count).toBe(1);

    // 2. Create child page
    const page2Resp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: '模块架构',
        content: '模块架构详细拆解。',
        parent_id: page1.id,
      }),
    });
    expect(page2Resp.status).toBe(201);
    const page2 = (await page2Resp.json()) as { id: number; parent_id: number };
    expect(page2.parent_id).toBe(page1.id);

    // 3. Get tree
    const treeResp = await env.app.request('/wiki/tree', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(treeResp.status).toBe(200);
    const tree = (await treeResp.json()) as Array<{ id: number; children: Array<{ id: number }> }>;
    expect(tree.length).toBe(1);
    expect(tree[0]?.id).toBe(page1.id);
    expect(tree[0]?.children.length).toBe(1);
    expect(tree[0]?.children[0]?.id).toBe(page2.id);

    // 4. Update page (creates revision 2)
    const updateResp = await env.app.request(`/wiki/pages/${page1.id}`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        content: '修改后的知识库设计正文，仍然引用 [[模块架构]]。',
      }),
    });
    expect(updateResp.status).toBe(200);
    const updatedPage1 = (await updateResp.json()) as { revision_count: number; content: string };
    expect(updatedPage1.revision_count).toBe(2);

    // 5. Check revisions
    const revResp = await env.app.request(`/wiki/pages/${page1.id}/revisions`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(revResp.status).toBe(200);
    const revisions = (await revResp.json()) as Array<{ rev_no: number }>;
    expect(revisions.length).toBe(2);

    // 6. Rollback to revision 1
    const rollResp = await env.app.request(`/wiki/pages/${page1.id}/rollback/1`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(rollResp.status).toBe(200);
    const rolled = (await rollResp.json()) as { content: string };
    expect(rolled.content).toContain('这是知识库设计的根页面');

    // 7. Graph
    const graphResp = await env.app.request('/wiki/graph', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(graphResp.status).toBe(200);
    const graph = (await graphResp.json()) as { nodes: unknown[]; links: Array<{ source: number; target: number }> };
    expect(graph.nodes.length).toBe(2);
    expect(graph.links.length).toBe(1);
    expect(graph.links[0]?.source).toBe(page1.id);
    expect(graph.links[0]?.target).toBe(page2.id);

    // 8. Revision Diff
    const diffResp = await env.app.request(`/wiki/pages/${page1.id}/diff?from_rev=1&to_rev=2`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(diffResp.status).toBe(200);
    const diffData = (await diffResp.json()) as { diff_lines: Array<{ type: string; content: string }> };
    expect(diffData.diff_lines.length).toBeGreaterThan(0);

    // 9. Upload asset
    const sharp = (await import('sharp')).default;
    const pngBuffer = await sharp({
      create: {
        width: 100,
        height: 100,
        channels: 3,
        background: { r: 0, g: 128, b: 255 },
      },
    })
      .png()
      .toBuffer();

    const assetFd = new FormData();
    assetFd.append('file', new Blob([pngBuffer], { type: 'image/png' }), 'arch-diag.png');
    const assetResp = await env.app.request(`/wiki/pages/${page1.id}/assets`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: assetFd,
    });
    expect(assetResp.status).toBe(200);
    const assetData = (await assetResp.json()) as { markdown_tag: string };
    expect(assetData.markdown_tag).toContain(`![[visual:${page1.id}/`);

    // 10. Search wiki
    const searchResp = await env.app.request('/wiki/search?q=模块架构', {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(searchResp.status).toBe(200);
    const searchResults = (await searchResp.json()) as Array<{ id: number; title: string; match_source: string }>;
    expect(searchResults.length).toBeGreaterThan(0);
    expect(searchResults[0]?.title).toBe('模块架构');
    expect(searchResults[0]?.match_source).toBe('title');

    // 11. Unlinked mentions & Link mention
    // Create page 3 mentioning '模块架构' in plain text
    const page3Resp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        title: '工程实践记录',
        content: '我们在工程中贯彻了模块架构的解耦设计规范。',
      }),
    });
    const page3 = (await page3Resp.json()) as { id: number };

    const unlinkedResp = await env.app.request(`/wiki/pages/${page2.id}/unlinked-mentions`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(unlinkedResp.status).toBe(200);
    const unlinkedData = (await unlinkedResp.json()) as Array<{ page_id: number; mentions: unknown[] }>;
    expect(unlinkedData.some((u) => u.page_id === page3.id)).toBe(true);

    const linkMentionResp = await env.app.request(`/wiki/pages/${page2.id}/link-mention`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ source_page_id: page3.id }),
    });
    expect(linkMentionResp.status).toBe(200);

    // Verify page3 content now contains [[模块架构]]
    const page3Updated = await env.app.request(`/wiki/pages/${page3.id}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    const page3Data = (await page3Updated.json()) as { content: string };
    expect(page3Data.content).toContain('[[模块架构]]');

    // 12. Delete page
    const delResp = await env.app.request(`/wiki/pages/${page3.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(delResp.status).toBe(204);
  });

  it('enforces optimistic locking with expected_rev_no returning 409 Conflict (BUG-08)', async () => {
    const createResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '并发锁测试', content: 'v1' }),
    });
    const page = (await createResp.json()) as { id: number; revision_count: number };
    expect(page.revision_count).toBe(1);

    // Valid expected_rev_no succeeds
    const okResp = await env.app.request(`/wiki/pages/${page.id}`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: 'v2', expected_rev_no: 1 }),
    });
    expect(okResp.status).toBe(200);
    const updated = (await okResp.json()) as { revision_count: number };
    expect(updated.revision_count).toBe(2);

    // Stale expected_rev_no returns 409 Conflict
    const staleResp = await env.app.request(`/wiki/pages/${page.id}`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: 'v3-stale', expected_rev_no: 1 }),
    });
    expect(staleResp.status).toBe(409);
  });

  it('orchestrates page rename with aliases, tenant isolation, AST variant rewrites, and source job reindex (BUG-09/10/11)', async () => {
    // Register second tenant user B
    await env.app.request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'other@example.com', password: 'Password123!' }),
    });
    const loginB = await env.app.request('/auth/jwt/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'other@example.com', password: 'Password123!' }),
    });
    const tokenB = ((await loginB.json()) as { access_token: string }).access_token;

    // Target page under user A
    const targetResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '旧页面标题', content: 'target body' }),
    });
    const target = (await targetResp.json()) as { id: number; user_id: number };

    // Source page under user A covering empty suffix variants & code fence
    const sourceContent = [
      '普通链接 [[旧页面标题]]',
      '空别名 [[旧页面标题|]] 与空锚点 [[旧页面标题#]]',
      '带锚点和别名 [[旧页面标题#sec|别名]]',
      '```md',
      '代码块内 [[旧页面标题]] 不应被改写',
      '```',
    ].join('\n');
    const srcResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '引用源页', content: sourceContent }),
    });
    const src = (await srcResp.json()) as { id: number; revision_count: number };

    // User B has a page mentioning [[旧页面标题]]
    const bSrcResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${tokenB}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'B的页面', content: '跨租户 [[旧页面标题]] 不得修改' }),
    });
    const bSrc = (await bSrcResp.json()) as { id: number };

    // Mark existing jobs succeeded so we can verify rename enqueues a new reindex job for source
    const db = getDb();
    db.prepare("UPDATE ingestion_jobs SET status = 'succeeded'").run();

    // Rename target page
    const renameResp = await env.app.request(`/wiki/pages/${target.id}`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '新页面标题' }),
    });
    expect(renameResp.status).toBe(200);

    // 1. Alias recorded
    const aliasRow = db
      .prepare('SELECT alias_title FROM wiki_aliases WHERE user_id = ? AND page_id = ?')
      .get(target.user_id, target.id) as { alias_title: string } | undefined;
    expect(aliasRow?.alias_title).toBe('旧页面标题');

    // 2. Source page rewritten cleanly including empty-suffix variants, code block untouched
    const srcAfter = (await (
      await env.app.request(`/wiki/pages/${src.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json()) as { content: string; revision_count: number };
    expect(srcAfter.content).toContain('[[新页面标题]]');
    expect(srcAfter.content).toContain('[[新页面标题|]]');
    expect(srcAfter.content).toContain('[[新页面标题#]]');
    expect(srcAfter.content).toContain('[[新页面标题#sec|别名]]');
    expect(srcAfter.content).toContain('代码块内 [[旧页面标题]] 不应被改写');
    expect(srcAfter.revision_count).toBe(src.revision_count + 1);

    // 3. Source page reindex job enqueued
    const srcJob = db
      .prepare("SELECT * FROM ingestion_jobs WHERE entity_type = 'wiki' AND entity_id = ? AND status = 'pending'")
      .get(src.id);
    expect(srcJob).toBeDefined();

    // 4. Tenant B untouched
    const bAfter = (await (
      await env.app.request(`/wiki/pages/${bSrc.id}`, {
        headers: { Authorization: `Bearer ${tokenB}` },
      })
    ).json()) as { content: string };
    expect(bAfter.content).toBe('跨租户 [[旧页面标题]] 不得修改');
  });

  it('re-indexes moved node and all descendants on moveWikiPage (BUG-13)', async () => {
    const r = await (
      await env.app.request('/wiki/pages', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Root', content: 'r' }),
      })
    ).json() as { id: number };
    const child = await (
      await env.app.request('/wiki/pages', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Child', content: 'c', parent_id: r.id }),
      })
    ).json() as { id: number };
    const grand = await (
      await env.app.request('/wiki/pages', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Grand', content: 'g', parent_id: child.id }),
      })
    ).json() as { id: number };
    const other = await (
      await env.app.request('/wiki/pages', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Other', content: 'o' }),
      })
    ).json() as { id: number };

    const db = getDb();
    db.prepare("UPDATE ingestion_jobs SET status = 'succeeded'").run();

    const moveResp = await env.app.request(`/wiki/pages/${child.id}/move`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_parent_id: other.id, sort_order: 1 }),
    });
    expect(moveResp.status).toBe(200);

    const grandAfter = (await (
      await env.app.request(`/wiki/pages/${grand.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json()) as { path: string };
    expect(grandAfter.path).toBe(`/${other.id}/${child.id}/${grand.id}/`);

    const pendingIds = (
      db
        .prepare("SELECT entity_id FROM ingestion_jobs WHERE entity_type = 'wiki' AND status = 'pending'")
        .all() as Array<{ entity_id: number }>
    ).map((x) => x.entity_id);
    expect(pendingIds).toContain(child.id);
    expect(pendingIds).toContain(grand.id);
  });

  it('blocks vault symlink escape and path traversal (BUG-03)', () => {
    const outsideFile = path.join(env.tmpDir, 'outside-secret.txt');
    fs.writeFileSync(outsideFile, 'DO_NOT_OVERWRITE', 'utf8');

    const userVault = path.join(config.resolvedVaultDir, '99');
    fs.mkdirSync(userVault, { recursive: true });
    const symlinkTarget = path.join(userVault, 'evil-link.md');
    fs.symlinkSync(outsideFile, symlinkTarget);

    expect(() => syncPageToVault(99, 'evil-link', 'Evil', 'pwned')).toThrow(/symlink|escape|traversal/i);
    expect(fs.readFileSync(outsideFile, 'utf8')).toBe('DO_NOT_OVERWRITE');

    expect(() => removePageFromVault(99, 'evil-link')).toThrow(/symlink|escape|traversal/i);
    expect(fs.existsSync(outsideFile)).toBe(true);
  });

  it('persists visual links and enforces non-null unique constraint on wiki_links (BUG-06)', async () => {
    const pResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: '视觉双链页',
        content: '包含图片 ![[visual:12/chart.jpg|系统图]] 与文本 [[目标页]]',
      }),
    });
    expect(pResp.status).toBe(201);
    const page = (await pResp.json()) as { id: number; user_id: number };

    const db = getDb();
    const visLink = db
      .prepare("SELECT * FROM wiki_links WHERE source_page_id = ? AND link_type = 'visual'")
      .get(page.id) as { target_title: string; alias: string; section_anchor: string } | undefined;
    expect(visLink).toBeDefined();
    expect(visLink?.target_title).toBe('12/chart.jpg');
    expect(visLink?.alias).toBe('系统图');
    expect(visLink?.section_anchor).toBe('');

    const textLink = db
      .prepare("SELECT alias, section_anchor FROM wiki_links WHERE source_page_id = ? AND link_type = 'wikilink'")
      .get(page.id) as { alias: string | null; section_anchor: string | null };
    expect(textLink.alias).toBe('');
    expect(textLink.section_anchor).toBe('');

    // SQLite unique constraint must reject duplicate empty-alias/anchor insert instead of silently allowing NULL != NULL
    expect(() => {
      db.prepare(`
        INSERT INTO wiki_links(user_id, source_page_id, target_page_id, target_title, alias, link_type, section_anchor)
        VALUES (?, ?, NULL, '目标页', '', 'wikilink', '')
      `).run(page.user_id, page.id);
    }).toThrow(/UNIQUE constraint failed/i);
  });

  it('escapes LIKE wildcards and excludes inline code/markdown links in unlinked-mentions (BUG-30/31)', async () => {
    const targetResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '100%_test', content: 'target' }),
    });
    const target = (await targetResp.json()) as { id: number };

    // False-positive wildcard page that should NOT match 100%_test
    await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'WildcardFalse', content: 'Here is 1000Xtest string' }),
    });

    // Inline code and markdown link only page for another target 'Vector'
    const vecResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Vector', content: 'vector page' }),
    });
    const vecPage = (await vecResp.json()) as { id: number };

    const noisePageResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'NoiseOnly',
        content: 'Use `Vector` inline or [Vector](https://example.com) link or [[Vector|alias]] here.',
      }),
    });
    const noisePage = (await noisePageResp.json()) as { id: number };

    const validPageResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'ValidMention',
        content: 'We study vector retrieval in detail.',
      }),
    });
    const validPage = (await validPageResp.json()) as { id: number };

    // Check BUG-30 LIKE escape
    const wildMentions = (await (
      await env.app.request(`/wiki/pages/${target.id}/unlinked-mentions`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json()) as Array<{ page_id: number }>;
    expect(wildMentions.length).toBe(0);

    // Check BUG-31 inline-code / markdown link exclusion + case-insensitive plain match
    const vecMentions = (await (
      await env.app.request(`/wiki/pages/${vecPage.id}/unlinked-mentions`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json()) as Array<{ page_id: number }>;
    expect(vecMentions.some((m) => m.page_id === noisePage.id)).toBe(false);
    expect(vecMentions.some((m) => m.page_id === validPage.id)).toBe(true);
  });

  it('populates backlinks on GET /wiki/pages/:id and backfills red-links when target page is created', async () => {
    // 1. Source page links to [[FutureConcept]] before FutureConcept exists
    const srcResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'IndexNote',
        content: 'See [[FutureConcept]] for details.',
      }),
    });
    expect(srcResp.status).toBe(201);
    const srcPage = (await srcResp.json()) as { id: number; title: string };

    // 2. Create FutureConcept afterwards -> should resolve pending wiki_links
    const targetResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'FutureConcept',
        content: 'Future concept definition.',
      }),
    });
    expect(targetResp.status).toBe(201);
    const targetPage = (await targetResp.json()) as {
      id: number;
      backlinks?: Array<{ source_page_id: number; source_title: string }>;
    };

    expect(Array.isArray(targetPage.backlinks)).toBe(true);
    expect(targetPage.backlinks?.length).toBe(1);
    expect(targetPage.backlinks?.[0]?.source_page_id).toBe(srcPage.id);
    expect(targetPage.backlinks?.[0]?.source_title).toBe('IndexNote');

    // Graph must include the backfilled edge
    const graphResp = await env.app.request('/wiki/graph', {
      headers: { Authorization: `Bearer ${token}` },
    });
    const graph = (await graphResp.json()) as {
      links: Array<{ source: number; target: number }>;
    };
    expect(graph.links.some((l) => l.source === srcPage.id && l.target === targetPage.id)).toBe(true);
  });

  it('promotes a note resource to Wiki preserving tags, deduplicating slug, and optionally archiving original', async () => {
    // Seed an existing wiki page with same title to verify slug deduplication
    const existingResp = await env.app.request('/wiki/pages', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Physics Inbox', content: 'old wiki page' }),
    });
    expect(existingResp.status).toBe(201);
    const parentPage = (await existingResp.json()) as { id: number };

    // Create two note resources
    const note1Resp = await env.app.request('/resources/notes', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Physics Inbox',
        content: '牛顿第二定律 $F=ma$ 笔记内容。',
        tags: ['physics', 'inbox'],
      }),
    });
    expect(note1Resp.status).toBe(201);
    const note1 = (await note1Resp.json()) as { id: number };

    // 1. Promote with archive_original=true (default) & colliding slug & parent_id
    const promoteResp = await env.app.request(`/resources/${note1.id}/promote-to-wiki`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent_id: parentPage.id }),
    });
    expect(promoteResp.status).toBe(201);
    const promoted = (await promoteResp.json()) as {
      page: { id: number; slug: string; parent_id: number | null; content: string; tags: string[] };
      archived_original: boolean;
    };
    expect(promoted.archived_original).toBe(true);
    expect(promoted.page.parent_id).toBe(parentPage.id);
    expect(promoted.page.slug).toBe('physics-inbox-2');
    expect(promoted.page.content).toContain('牛顿第二定律');
    expect(promoted.page.tags).toEqual(expect.arrayContaining(['physics', 'inbox']));

    // Original note should be removed when archived_original=true
    const checkRemoved = await env.app.request(`/resources/${note1.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(checkRemoved.status).toBe(404);

    // 2. Promote with archive_original=false keeps note resource
    const note2Resp = await env.app.request('/resources/notes', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Keep Copy Note',
        content: '保留原笔记副本的内容。',
        tags: ['keep'],
      }),
    });
    const note2 = (await note2Resp.json()) as { id: number };
    const keepResp = await env.app.request(`/resources/${note2.id}/promote-to-wiki`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Copy Wiki Title', archive_original: false }),
    });
    expect(keepResp.status).toBe(201);
    const keepData = (await keepResp.json()) as { archived_original: boolean; page: { title: string } };
    expect(keepData.archived_original).toBe(false);
    expect(keepData.page.title).toBe('Copy Wiki Title');

    const checkKept = await env.app.request(`/resources/${note2.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(checkKept.status).toBe(200);
  });
});

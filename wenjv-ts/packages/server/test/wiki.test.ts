import { describe, it, expect, beforeEach, afterEach } from 'vitest';
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
});

import { execFileSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { expect, test } from '@playwright/test';

const e2eBaseDir = process.env['WENJV_E2E_DIR'] || path.join(os.tmpdir(), 'wenjv-e2e-data');
const e2eDbPath = path.join(e2eBaseDir, 'wenjv.db');

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]!;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
  }
  return (c ^ 0xffffffff) >>> 0;
}

function makePngChunk(type: string, data: Buffer): Buffer {
  const typeBuf = Buffer.from(type, 'ascii');
  const lenBuf = Buffer.alloc(4);
  lenBuf.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([lenBuf, typeBuf, data, crcBuf]);
}

function createSolidPng(width = 16, height = 16): Buffer {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = 1 + width * 4;
  const raw = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const rowStart = y * stride;
    raw[rowStart] = 0; // filter none
    for (let x = 0; x < width; x++) {
      const px = rowStart + 1 + x * 4;
      raw[px] = 45;
      raw[px + 1] = 120;
      raw[px + 2] = 220;
      raw[px + 3] = 255;
    }
  }

  const idat = zlib.deflateSync(raw);
  return Buffer.concat([
    signature,
    makePngChunk('IHDR', ihdr),
    makePngChunk('IDAT', idat),
    makePngChunk('IEND', Buffer.alloc(0)),
  ]);
}

function promoteUserToSuperuser(email: string): void {
  execFileSync('python3', [
    '-c',
    `import sqlite3, sys; conn = sqlite3.connect(sys.argv[1]); cur = conn.execute("UPDATE users SET is_superuser = 1 WHERE email = ?", (sys.argv[2],)); conn.commit(); assert cur.rowcount == 1`,
    e2eDbPath,
    email,
  ]);
}

test.describe('wenjv single-port E2E flows', () => {
  test('supports auth guard, note/image ingestion with thumbnail, keepalive state, refs search, wiki, and admin console', async ({
    page,
  }) => {
    const normalEmail = 'e2e-user@wenjv.local';
    const adminEmail = 'e2e-admin@wenjv.local';
    const password = 'E2ePassword!2026';

    // 1. Unauthenticated visit redirects to /login
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);

    // 2. Register normal user and confirm non-superuser guard blocks /admin
    await page.getByRole('link', { name: '注册' }).click();
    await expect(page).toHaveURL(/\/register/);
    await page.getByPlaceholder('you@example.com').fill(normalEmail);
    const pwInputs = page.locator('input[type="password"]');
    await pwInputs.nth(0).fill(password);
    await pwInputs.nth(1).fill(password);
    await page.getByRole('button', { name: '注册并登录' }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('link', { name: '管理' })).toHaveCount(0);

    await page.goto('/admin');
    await expect(page).toHaveURL(/\/$/);

    // 3. Create a note in ChatView left sidebar
    await page.getByRole('button', { name: '笔记', exact: true }).click();
    await page.getByPlaceholder('笔记标题').fill('E2E 光合作用原理笔记');
    await page.getByPlaceholder('Markdown / 纯文本').fill(
      '光合作用是将光能转化为化学能的过程，核心反应式包含叶绿体电子传递与卡尔文循环。'
    );
    await page.getByPlaceholder('标签，逗号/空格分隔').first().fill('bio e2e');
    await page.getByRole('button', { name: '保存笔记', exact: true }).click();
    await expect(page.locator('.success-banner')).toContainText('笔记已创建');

    // 4. Upload a real PNG image in ChatView image tab
    await page.getByRole('button', { name: '图片', exact: true }).click();
    const imagePaneInput = page.locator('.pane').nth(1).locator('input[type="file"]');
    await imagePaneInput.setInputFiles({
      name: 'e2e-diagram.png',
      mimeType: 'image/png',
      buffer: createSolidPng(16, 16),
    });
    await page.getByRole('button', { name: '提交图片入库' }).click();
    await expect(page.locator('.success-banner')).toContainText('图片已提交');

    // 5. Type prompt in composer to test KeepAlive state across routes
    const composerPrompt = page.getByPlaceholder('提出问题，或粘贴/上传截图直接对话…');
    await composerPrompt.fill('KeepAlive 未发送草稿文本');

    // 6. Open LibraryView, wait for ingestion completion, and inspect image thumbnail preview
    await page.getByRole('link', { name: '资料库' }).click();
    await expect(page).toHaveURL(/\/library/);
    await expect(page.getByText('E2E 光合作用原理笔记')).toBeVisible();
    await expect(page.getByText('e2e-diagram.png').first()).toBeVisible();

    const diagramRow = page.locator('li.resource-row', { hasText: 'e2e-diagram.png' }).first();
    await expect(diagramRow).toContainText('finished', { timeout: 45_000 });

    const rowThumb = diagramRow.locator('img.row-thumb');
    await expect(rowThumb).toBeVisible();
    await expect
      .poll(async () => rowThumb.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0);

    await diagramRow.click();
    const detailDialog = page.getByRole('dialog', { name: '资源详情' });
    await expect(detailDialog).toBeVisible();
    const detailImg = detailDialog.locator('img.detail-image-preview');
    await expect(detailImg).toBeVisible();
    await expect
      .poll(async () => detailImg.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0);
    await detailDialog.getByRole('button', { name: '关闭' }).last().click();

    // 7. Create a Wiki page
    await page.getByRole('link', { name: 'Wiki' }).click();
    await expect(page).toHaveURL(/\/wiki/);
    await page.getByRole('button', { name: '新建知识页面' }).click();
    await expect(page.locator('.wiki-toast')).toContainText('已创建');

    // 8. Return to ChatView and verify KeepAlive preserved draft prompt, then run refs search
    await page.getByRole('link', { name: '对话' }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(composerPrompt).toHaveValue('KeepAlive 未发送草稿文本');

    await composerPrompt.fill('卡尔文循环');
    await page.getByRole('button', { name: '仅引用' }).click();
    await composerPrompt.press('Enter');
    await expect(page.locator('.cites')).toBeVisible();
    await expect(page.locator('.cites')).toContainText('光合作用');

    // 8b. Verify hidden thinking stream + secondary /thinking/:id view + fixed nav/pin icons
    await expect(page.getByRole('link', { name: 'Wiki' }).locator('svg path')).toHaveCount(3);
    await page.route('**/chat', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue();
        return;
      }
      const sseBody = [
        `data: ${JSON.stringify({ type: 'citations', citations: [] })}\n\n`,
        `data: ${JSON.stringify({ type: 'thinking', content: '先核对光合作用光反应路径' })}\n\n`,
        `data: ${JSON.stringify({ type: 'token', content: '最终答案：ATP 与 NADPH' })}\n\n`,
        `data: ${JSON.stringify({ type: 'done' })}\n\n`,
      ].join('');
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        body: sseBody,
      });
    });

    await page.getByRole('button', { name: '自由对话' }).click();
    await composerPrompt.fill('请分析光合作用能量转换');
    await composerPrompt.press('Enter');
    const lastAssistantBubble = page.locator('.msg.assistant').last();
    await expect(lastAssistantBubble.locator('.content')).toContainText('最终答案：ATP 与 NADPH');
    await expect(lastAssistantBubble.locator('.content')).not.toContainText('先核对光合作用光反应路径');
    await expect(lastAssistantBubble.locator('.save-to-wiki-btn svg')).toHaveCount(1);

    const thinkingBtn = lastAssistantBubble.locator('.msg-thinking-btn');
    await expect(thinkingBtn).toBeVisible();
    await thinkingBtn.click();
    await expect(page).toHaveURL(/\/thinking\/\d+/);
    await expect(page.locator('.reasoning-content')).toContainText('先核对光合作用光反应路径');
    await expect(page.locator('.context-text')).toContainText('请分析光合作用能量转换');

    await page.getByRole('button', { name: '返回对话' }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('.msg.assistant .content').last()).toContainText('最终答案：ATP 与 NADPH');
    await page.unroute('**/chat');

    // 9. Logout, register superuser account, promote in SQLite, re-login, and inspect /admin
    await page.getByRole('button', { name: '退出' }).click();
    await expect(page).toHaveURL(/\/login/);

    await page.getByRole('link', { name: '注册' }).click();
    await expect(page).toHaveURL(/\/register/);
    await page.getByPlaceholder('you@example.com').fill(adminEmail);
    await pwInputs.nth(0).fill(password);
    await pwInputs.nth(1).fill(password);
    await page.getByRole('button', { name: '注册并登录' }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.getByRole('button', { name: '退出' }).click();
    await expect(page).toHaveURL(/\/login/);

    promoteUserToSuperuser(adminEmail);

    await page.getByPlaceholder('you@example.com').fill(adminEmail);
    await page.locator('input[type="password"]').fill(password);
    await page.getByRole('button', { name: '登录' }).click();
    await expect(page).toHaveURL(/\/$/);

    const adminLink = page.getByRole('link', { name: '管理' });
    await expect(adminLink).toBeVisible();
    await adminLink.click();
    await expect(page).toHaveURL(/\/admin/);

    await expect(page.getByRole('heading', { name: '系统管理与观测' })).toBeVisible();
    await expect(page.getByText('OCR Sidecar')).toBeVisible();
    await expect(page.getByText('SigLIP2 视觉编码')).toBeVisible();
    await expect(page.getByText('卡尔文循环')).toBeVisible();

    await page.getByRole('button', { name: '清零计数' }).click();
    await expect(page.locator('.info-banner')).toContainText(/reset|清零/i);
  });
});

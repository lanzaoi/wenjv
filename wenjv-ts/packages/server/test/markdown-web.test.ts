import { describe, it, expect } from 'vitest';
import { renderMarkdown } from '../../web/src/utils/markdown.js';
import { renderMd } from '../../web/src/utils/chat-format.js';

describe('Web Markdown Rendering Security & Escaping (BUG-07)', () => {
  it('avoids double HTML escaping in wikilinks and visual embeds', () => {
    const md = [
      '链接 [[R&D <Guide>#A&B|C&D]]',
      '',
      '图片 ![[visual:12/a.jpg|Chart & <Graph>]]',
    ].join('\n');

    const html = renderMarkdown(md);
    expect(html).not.toContain('&amp;amp;');
    expect(html).not.toContain('&amp;lt;');
    expect(html).toContain('data-wiki-target="R&amp;D &lt;Guide&gt;"');
    expect(html).toContain('src="/api/assets/image?path=mm_assets%2F12%2Fa.jpg"');
    expect(html).toContain('alt="Chart &amp; &lt;Graph&gt;"');
    expect(html).toContain('<span class="wiki-embed-caption">Chart &amp; &lt;Graph&gt;</span>');
  });

  it('blocks javascript: XSS URLs in markdown links', () => {
    const html = renderMarkdown('Click [here](javascript:alert(1)) or [ok](https://example.com)');
    expect(html).not.toContain('javascript:');
    expect(html).toContain('href="https://example.com"');
  });

  it('appends assetToken to visual embeds and marks missing wikilinks when options provided', () => {
    const html = renderMarkdown('See [[Existing]] and [[GhostPage]]\n\n![[visual:5/pic.jpg|Slide]]', {
      assetToken: 'jwt-abc-123',
      knownTitles: new Set(['Existing']),
    });
    expect(html).toContain('src="/api/assets/image?path=mm_assets%2F5%2Fpic.jpg&token=jwt-abc-123"');
    expect(html).toContain('class="wiki-link-btn" data-wiki-target="Existing"');
    expect(html).toContain('class="wiki-link-btn is-missing" data-wiki-target="GhostPage"');
  });

  it('prevents double-quote attribute breakout and HTML injection in chat renderMd (H2)', () => {
    const payload = [
      'Try [click](https://a.com/"onfocus="alert(1))',
      'Bad [js](javascript:alert(1))',
      '<script>alert(1)</script>',
      '<img src=x onerror=alert(1)>',
    ].join('\n');

    const html = renderMd(payload);
    expect(html).not.toContain('"onfocus=');
    expect(html).toContain('&quot;onfocus=');
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img ');
    expect(html).toContain('&lt;script&gt;');
  });
});

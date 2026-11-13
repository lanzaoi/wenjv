import { describe, it, expect } from 'vitest';
import { renderMarkdown } from '../../web/src/utils/markdown.js';

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
});

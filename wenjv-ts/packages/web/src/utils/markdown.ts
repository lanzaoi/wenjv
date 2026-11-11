/**
 * Lightweight, safe client-side Markdown & Wikilink parser.
 * Zero-dependency, offline-ready, renders [[Wikilinks]] into interactive navigation nodes.
 */

function escapeHtml(str: string): string {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function unescapeHtml(str: string): string {
  return String(str || '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

export function slugifyHeading(text: string): string {
  return String(text || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function renderMarkdown(rawMd: string): string {
  if (!rawMd) return '';

  const lines = rawMd.split('\n');
  const out: string[] = [];
  let inCodeBlock = false;
  let codeBlockLang = '';
  let codeBlockLines: string[] = [];
  let inList = false;
  let listType: 'ul' | 'ol' = 'ul';
  let inTable = false;

  function closeList() {
    if (inList) {
      out.push(listType === 'ul' ? '</ul>' : '</ol>');
      inList = false;
    }
  }

  function closeTable() {
    if (inTable) {
      out.push('</tbody></table></div>');
      inTable = false;
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';

    // 1. Code Block Fence (```)
    const fenceMatch = line.match(/^```(\w+)?/);
    if (fenceMatch) {
      if (inCodeBlock) {
        // End code block
        const codeContent = escapeHtml(codeBlockLines.join('\n'));
        out.push(
          `<pre class="code-block" data-lang="${codeBlockLang}"><code class="language-${codeBlockLang}">${codeContent}</code></pre>`
        );
        inCodeBlock = false;
        codeBlockLines = [];
        codeBlockLang = '';
      } else {
        closeList();
        closeTable();
        inCodeBlock = true;
        codeBlockLang = fenceMatch[1] || 'plaintext';
        codeBlockLines = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    // 2. Table row
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      closeList();
      const rowCells = line
        .trim()
        .slice(1, -1)
        .split('|')
        .map((c) => c.trim());

      // Check if it's separator row (|---|---|)
      const isSep = rowCells.every((c) => /^:?-+:?$/.test(c));
      if (isSep) {
        continue;
      }

      if (!inTable) {
        inTable = true;
        out.push('<div class="table-wrap"><table class="markdown-table"><thead><tr>');
        for (const c of rowCells) {
          out.push(`<th>${parseInline(escapeHtml(c))}</th>`);
        }
        out.push('</tr></thead><tbody>');
        continue;
      } else {
        out.push('<tr>');
        for (const c of rowCells) {
          out.push(`<td>${parseInline(escapeHtml(c))}</td>`);
        }
        out.push('</tr>');
        continue;
      }
    } else {
      closeTable();
    }

    // 3. Blank Line
    if (!line.trim()) {
      closeList();
      closeTable();
      continue;
    }

    // 4. Horizontal Rule
    if (/^(\*\*\*|---|___)$/.test(line.trim())) {
      closeList();
      out.push('<hr class="markdown-hr" />');
      continue;
    }

    // 5. Headings
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch && headingMatch[1] && headingMatch[2]) {
      closeList();
      const level = headingMatch[1].length;
      const title = headingMatch[2].trim();
      const slug = slugifyHeading(title);
      out.push(`<h${level} id="${slug}" class="heading-${level}">${parseInline(escapeHtml(title))}</h${level}>`);
      continue;
    }

    // 6. Blockquote
    if (line.startsWith('>')) {
      closeList();
      const quoteText = line.replace(/^>\s?/, '');
      out.push(`<blockquote>${parseInline(escapeHtml(quoteText))}</blockquote>`);
      continue;
    }

    // 7. Checkboxes (- [ ] or - [x])
    const checkMatch = line.match(/^[-*]\s+\[([ xX])\]\s+(.+)$/);
    if (checkMatch && checkMatch[1] && checkMatch[2]) {
      closeList();
      const checked = checkMatch[1].toLowerCase() === 'x';
      out.push(
        `<div class="task-item"><input type="checkbox" disabled ${checked ? 'checked' : ''} /> <span>${parseInline(escapeHtml(checkMatch[2]))}</span></div>`
      );
      continue;
    }

    // 8. Lists (- or * or 1.)
    const ulMatch = line.match(/^[-*]\s+(.+)$/);
    const olMatch = line.match(/^\d+\.\s+(.+)$/);
    if (ulMatch && ulMatch[1]) {
      if (!inList || listType !== 'ul') {
        closeList();
        inList = true;
        listType = 'ul';
        out.push('<ul>');
      }
      out.push(`<li>${parseInline(escapeHtml(ulMatch[1]))}</li>`);
      continue;
    } else if (olMatch && olMatch[1]) {
      if (!inList || listType !== 'ol') {
        closeList();
        inList = true;
        listType = 'ol';
        out.push('<ol>');
      }
      out.push(`<li>${parseInline(escapeHtml(olMatch[1]))}</li>`);
      continue;
    } else {
      closeList();
    }

    // 9. Standard Paragraph
    out.push(`<p>${parseInline(escapeHtml(line))}</p>`);
  }

  closeList();
  closeTable();

  return out.join('\n');
}

/**
 * Inline formatting:
 * - [[Target Page|Alias]] or [[Target Page]]
 * - `code`
 * - **bold**
 * - *italic*
 * - [Link](url)
 */
export function parseInline(text: string): string {
  if (!text) return '';

  // Inline code `code` (protect from further replacements)
  const codeSnippets: string[] = [];
  let safe = text.replace(/`([^`]+)`/g, (_, code) => {
    codeSnippets.push(`<code>${code}</code>`);
    return `__CODE_SNIPPET_${codeSnippets.length - 1}__`;
  });

  // Visual Embeds: ![[visual:resource_id/filename|alt]] or ![[visual:resource_id/filename]]
  safe = safe.replace(/!\[\[visual:([^|\]]+)(?:\|([^\]]+))?\]\]/g, (_, assetPath, alt) => {
    const rawPath = String(assetPath || '').trim();
    const label = String(alt || rawPath).trim();
    const imgSrc = `/api/documents/assets/image?path=mm_assets/${encodeURIComponent(rawPath)}`;
    return `<div class="wiki-visual-embed"><img src="${imgSrc}" alt="${escapeHtml(label)}" class="wiki-embed-img" /><span class="wiki-embed-caption">${escapeHtml(label)}</span></div>`;
  });

  // Wikilinks: [[Target#Anchor|Alias]] or [[Target#Anchor]] or [[Target|Alias]] or [[Target]]
  safe = safe.replace(/\[\[([^|#\]]+)(?:#([^|\]]+))?(?:\|([^\]]+))?\]\]/g, (_, target, anchor, alias) => {
    // Unescape HTML first because the whole line was already escapeHtml'd
    const rawTarget = unescapeHtml(target).trim();
    const rawAnchor = anchor ? unescapeHtml(anchor).trim() : '';
    const rawAlias = alias ? unescapeHtml(alias).trim() : '';
    const label = (rawAlias || (rawAnchor ? `${rawTarget}#${rawAnchor}` : rawTarget)).trim();
    return `<button type="button" class="wiki-link-btn" data-wiki-target="${escapeHtml(rawTarget)}" data-wiki-anchor="${escapeHtml(rawAnchor)}" title="跳转到页面：${escapeHtml(rawTarget)}${rawAnchor ? ' #' + escapeHtml(rawAnchor) : ''}">📄 ${escapeHtml(label)}</button>`;
  });

  // Standard Markdown Links [label](url)
  safe = safe.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // Bold **text**
  safe = safe.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // Italic *text*
  safe = safe.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  // Restore inline code
  safe = safe.replace(/__CODE_SNIPPET_(\d+)__/g, (_, idx) => codeSnippets[Number(idx)] ?? '');

  return safe;
}

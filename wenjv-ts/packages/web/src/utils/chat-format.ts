/** Lightweight Markdown-to-HTML renderer shared by chat and thinking views. */
export function renderMd(text: string): string {
  if (!text) return '';
  const codeBlocks: string[] = [];
  let processed = String(text).replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_match, lang, code) => {
    const id = `__CODE_BLOCK_${codeBlocks.length}__`;
    const escCode = String(code)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    codeBlocks.push(`<pre class="code-block"><code class="language-${lang || 'text'}">${escCode}</code></pre>`);
    return id;
  });

  processed = processed
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  processed = processed.replace(/^### (.+)$/gm, '<h4 class="md-h">$1</h4>');
  processed = processed.replace(/^## (.+)$/gm, '<h3 class="md-h">$1</h3>');
  processed = processed.replace(/^# (.+)$/gm, '<h2 class="md-h">$1</h2>');
  processed = processed.replace(/^&gt; (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');
  processed = processed.replace(/^[-*] (.+)$/gm, '<div class="md-li">• $1</div>');
  processed = processed.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');
  processed = processed.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  processed = processed.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  processed = processed.replace(
    /\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="chat-link">$1</a>'
  );
  processed = processed.replace(/\n/g, '<br>');
  processed = processed.replace(/(<\/(?:h[234]|blockquote|div)>)<br>/g, '$1');

  codeBlocks.forEach((block, idx) => {
    processed = processed.replace(`__CODE_BLOCK_${idx}__`, block);
  });

  return processed;
}

/** Format character count into a compact human-readable badge label. */
export function formatThinkingLength(text: string): string {
  const len = text.trim().length;
  if (len <= 0) return '0 字';
  return `${len} 字`;
}

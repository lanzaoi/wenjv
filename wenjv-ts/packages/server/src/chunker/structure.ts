export interface TextChunk {
  text: string;
  indexing_text: string;
  header_str: string;
  block_type: string;
  start_char: number;
  end_char: number;
  page_number: number;
}

export interface SplitterOptions {
  chunkSize?: number;
  chunkOverlap?: number;
  separators?: string[];
}

export class RecursiveTextSplitter {
  private chunkSize: number;
  private chunkOverlap: number;
  private separators: string[];

  constructor(options: SplitterOptions = {}) {
    this.chunkSize = options.chunkSize ?? 1000;
    this.chunkOverlap = options.chunkOverlap ?? 150;
    this.separators = options.separators ?? ['\n\n', '\n', '。', '，', ' ', ''];
  }

  public splitText(text: string): string[] {
    return this._splitText(text, this.separators);
  }

  private _splitText(text: string, separators: string[]): string[] {
    const finalChunks: string[] = [];
    let separator = separators[separators.length - 1] ?? '';
    let newSeparators: string[] = [];

    for (let i = 0; i < separators.length; i++) {
      const s = separators[i]!;
      if (s === '') {
        separator = s;
        break;
      }
      if (text.includes(s)) {
        separator = s;
        newSeparators = separators.slice(i + 1);
        break;
      }
    }

    const splits = separator ? text.split(separator) : Array.from(text);
    const goodSplits: string[] = [];

    for (const s of splits) {
      if (s.length < this.chunkSize) {
        goodSplits.push(s);
      } else {
        if (goodSplits.length > 0) {
          const merged = this._mergeSplits(goodSplits, separator);
          finalChunks.push(...merged);
          goodSplits.length = 0;
        }
        if (newSeparators.length === 0) {
          finalChunks.push(s);
        } else {
          const otherInfo = this._splitText(s, newSeparators);
          finalChunks.push(...otherInfo);
        }
      }
    }

    if (goodSplits.length > 0) {
      const merged = this._mergeSplits(goodSplits, separator);
      finalChunks.push(...merged);
    }

    return finalChunks;
  }

  private _mergeSplits(splits: string[], separator: string): string[] {
    const docs: string[] = [];
    const currentDoc: string[] = [];
    let total = 0;

    for (const d of splits) {
      const len = d.length;
      if (total + len + (currentDoc.length > 0 ? separator.length : 0) > this.chunkSize) {
        if (total > 0) {
          const doc = currentDoc.join(separator).trim();
          if (doc) docs.push(doc);
          while (
            total > this.chunkOverlap ||
            (total + len + (currentDoc.length > 0 ? separator.length : 0) > this.chunkSize && total > 0)
          ) {
            const popped = currentDoc.shift();
            if (popped !== undefined) {
              total -= popped.length + (currentDoc.length > 0 ? separator.length : 0);
            } else {
              break;
            }
          }
        }
      }
      currentDoc.push(d);
      total += len + (currentDoc.length > 1 ? separator.length : 0);
    }

    const doc = currentDoc.join(separator).trim();
    if (doc) docs.push(doc);
    return docs;
  }
}

interface MarkdownBlock {
  type: 'heading' | 'code' | 'table' | 'text';
  level?: number;
  title?: string;
  lang?: string;
  lines?: string[];
  content: string;
}

export function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const lines = text.split('\n');
  const blocks: MarkdownBlock[] = [];
  let i = 0;
  const n = lines.length;

  let inCode = false;
  let codeLines: string[] = [];
  let codeLang = '';
  let tableLines: string[] = [];
  let textBuf: string[] = [];

  const flushTable = () => {
    if (tableLines.length > 0) {
      blocks.push({
        type: 'table',
        lines: [...tableLines],
        content: tableLines.join('\n'),
      });
      tableLines = [];
    }
  };

  const flushText = () => {
    if (textBuf.length > 0) {
      const content = textBuf.join('\n').trim();
      if (content) {
        blocks.push({ type: 'text', content });
      }
      textBuf = [];
    }
  };

  const headerRe = /^(#{1,6})\s+(.+)$/;
  const tableRowRe = /^\s*\|.*\|\s*$/;
  const codeStartRe = /^\s*```(\w*)\s*$/;
  const codeEndRe = /^\s*```\s*$/;

  while (i < n) {
    const line = lines[i]!;

    if (!inCode && codeStartRe.test(line)) {
      flushText();
      flushTable();
      inCode = true;
      const m = line.match(codeStartRe);
      codeLang = m?.[1] || '';
      codeLines = [line];
      i++;
      continue;
    } else if (inCode) {
      codeLines.push(line);
      if (codeEndRe.test(line)) {
        inCode = false;
        blocks.push({
          type: 'code',
          lang: codeLang,
          content: codeLines.join('\n'),
        });
        codeLines = [];
      }
      i++;
      continue;
    }

    if (tableRowRe.test(line)) {
      flushText();
      tableLines.push(line);
      i++;
      continue;
    } else {
      flushTable();
    }

    const hm = line.trim().match(headerRe);
    if (hm && hm[1] && hm[2]) {
      flushText();
      blocks.push({
        type: 'heading',
        level: hm[1].length,
        title: hm[2].trim(),
        content: line,
      });
      i++;
      continue;
    }

    textBuf.push(line);
    i++;
  }

  flushText();
  flushTable();
  if (inCode && codeLines.length > 0) {
    blocks.push({
      type: 'code',
      lang: codeLang,
      content: codeLines.join('\n'),
    });
  }

  return blocks;
}

export function chunkTableBlock(tableLines: string[], maxAtomicSize = 1200): string[] {
  const fullTable = tableLines.join('\n');
  if (fullTable.length <= maxAtomicSize || tableLines.length <= 3) {
    return [fullTable];
  }

  const headers = tableLines.slice(0, 2);
  const rows = tableLines.slice(2);
  const subTables: string[] = [];
  let currBatch: string[] = [];
  let currLen = headers.reduce((acc, h) => acc + h.length + 1, 0);

  for (const r of rows) {
    const rLen = r.length + 1;
    if (currBatch.length > 0 && currLen + rLen > maxAtomicSize) {
      subTables.push([...headers, ...currBatch].join('\n'));
      currBatch = [r];
      currLen = headers.reduce((acc, h) => acc + h.length + 1, 0) + rLen;
    } else {
      currBatch.push(r);
      currLen += rLen;
    }
  }

  if (currBatch.length > 0) {
    subTables.push([...headers, ...currBatch].join('\n'));
  }

  return subTables.length > 0 ? subTables : [fullTable];
}

export function chunkCodeBlock(codeContent: string, lang = '', maxAtomicSize = 1200): string[] {
  if (codeContent.length <= maxAtomicSize) {
    return [codeContent];
  }

  const lines = codeContent.split('\n');
  let innerLines = lines;
  if (innerLines.length > 0 && innerLines[0]!.trim().startsWith('```')) {
    innerLines = innerLines.slice(1);
  }
  if (innerLines.length > 0 && innerLines[innerLines.length - 1]!.trim() === '```') {
    innerLines = innerLines.slice(0, -1);
  }

  const subBlocks: string[] = [];
  let currBatch: string[] = [];
  let currLen = lang.length + 8;

  for (const line of innerLines) {
    const lLen = line.length + 1;
    if (currBatch.length > 0 && currLen + lLen > maxAtomicSize) {
      subBlocks.push(`\`\`\`${lang}\n` + currBatch.join('\n') + '\n```');
      currBatch = [line];
      currLen = lang.length + 8 + lLen;
    } else {
      currBatch.push(line);
      currLen += lLen;
    }
  }

  if (currBatch.length > 0) {
    subBlocks.push(`\`\`\`${lang}\n` + currBatch.join('\n') + '\n```');
  }

  return subBlocks.length > 0 ? subBlocks : [codeContent];
}

export function structureAwareChunk(
  body: string,
  splitter?: RecursiveTextSplitter,
  maxAtomicSize = 1200,
  pageNumber = 1
): TextChunk[] {
  const blocks = parseMarkdownBlocks(body);
  const breadcrumbsStack: { level: number; title: string }[] = [];
  const chunks: TextChunk[] = [];
  let charCursor = 0;

  for (const b of blocks) {
    if (b.type === 'heading') {
      const level = b.level ?? 1;
      const title = b.title ?? '';
      while (breadcrumbsStack.length > 0 && breadcrumbsStack[breadcrumbsStack.length - 1]!.level >= level) {
        breadcrumbsStack.pop();
      }
      breadcrumbsStack.push({ level, title });
      continue;
    }

    const headerStr = breadcrumbsStack.map((item) => item.title).join(' > ');
    let subTexts: string[] = [];

    if (b.type === 'table' && b.lines) {
      subTexts = chunkTableBlock(b.lines, maxAtomicSize);
    } else if (b.type === 'code') {
      subTexts = chunkCodeBlock(b.content, b.lang || '', maxAtomicSize);
    } else {
      if (splitter) {
        subTexts = splitter.splitText(b.content);
      } else {
        subTexts = [b.content];
      }
    }

    for (const st of subTexts) {
      if (!st.trim()) continue;
      let startPos = body.indexOf(st, charCursor);
      if (startPos === -1) {
        startPos = charCursor;
      }
      const endPos = startPos + st.length;
      charCursor = endPos;

      const indexingText = headerStr ? `[${headerStr}]\n\n${st}` : st;

      chunks.push({
        text: st,
        indexing_text: indexingText,
        header_str: headerStr,
        block_type: b.type,
        start_char: startPos,
        end_char: endPos,
        page_number: pageNumber,
      });
    }
  }

  if (chunks.length === 0 && body.trim()) {
    const rawSplits = splitter ? splitter.splitText(body) : [body];
    for (const rs of rawSplits) {
      chunks.push({
        text: rs,
        indexing_text: rs,
        header_str: '',
        block_type: 'text',
        start_char: 0,
        end_char: rs.length,
        page_number: pageNumber,
      });
    }
  }

  return chunks;
}

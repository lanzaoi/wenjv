export interface ParsedTextResult {
  text: string;
}

export function parseText(content: string | Buffer): ParsedTextResult {
  const text = typeof content === 'string' ? content : content.toString('utf8');
  return {
    text: text.trim(),
  };
}

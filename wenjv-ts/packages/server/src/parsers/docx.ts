import mammoth from 'mammoth';

export interface ParsedDocxResult {
  text: string;
}

export async function parseDocx(buffer: Buffer): Promise<ParsedDocxResult> {
  const result = await mammoth.extractRawText({ buffer });
  return {
    text: result.value.trim(),
  };
}

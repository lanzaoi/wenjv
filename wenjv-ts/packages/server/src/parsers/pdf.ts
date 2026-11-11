import { extractText } from 'unpdf';

export interface ParsedPdfPage {
  pageNumber: number;
  text: string;
}

export interface ParsedPdfResult {
  text: string;
  pages: ParsedPdfPage[];
  totalPages: number;
}

export async function parsePdf(buffer: Buffer | Uint8Array): Promise<ParsedPdfResult> {
  const result = await extractText(buffer);
  const totalPages = result.totalPages || (Array.isArray(result.text) ? result.text.length : 1);
  const rawPages: string[] = Array.isArray(result.text) ? result.text : [String(result.text || '')];

  const pages: ParsedPdfPage[] = rawPages.map((text, idx) => ({
    pageNumber: idx + 1,
    text: text.trim(),
  }));

  const fullText = pages.map((p) => p.text).filter(Boolean).join('\n\n');

  return {
    text: fullText,
    pages,
    totalPages,
  };
}

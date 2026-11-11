import JSZip from 'jszip';

export interface ParsedPptxSlide {
  slideNumber: number;
  text: string;
}

export interface ParsedPptxResult {
  text: string;
  slides: ParsedPptxSlide[];
  totalSlides: number;
}

export async function parsePptx(buffer: Buffer): Promise<ParsedPptxResult> {
  const zip = await JSZip.loadAsync(buffer);
  const slideEntries: { num: number; path: string }[] = [];

  zip.forEach((relativePath) => {
    const match = relativePath.match(/^ppt\/slides\/slide(\d+)\.xml$/);
    if (match && match[1]) {
      slideEntries.push({
        num: parseInt(match[1], 10),
        path: relativePath,
      });
    }
  });

  slideEntries.sort((a, b) => a.num - b.num);

  const slides: ParsedPptxSlide[] = [];

  for (const entry of slideEntries) {
    const file = zip.file(entry.path);
    if (!file) continue;

    const xml = await file.async('string');
    // Extract text from <a:t>...</a:t> elements
    const textMatches = xml.match(/<a:t(?:\s+[^>]*)?>([\s\S]*?)<\/a:t>/g) || [];
    const textPieces = textMatches.map((m) => {
      return m
        .replace(/<a:t(?:\s+[^>]*)?>/, '')
        .replace(/<\/a:t>/, '')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
        .replace(/&apos;/g, "'")
        .replace(/&quot;/g, '"');
    });

    const slideText = textPieces.join(' ').replace(/\s+/g, ' ').trim();
    if (slideText) {
      slides.push({
        slideNumber: entry.num,
        text: slideText,
      });
    }
  }

  const fullText = slides.map((s) => s.text).join('\n\n');

  return {
    text: fullText,
    slides,
    totalSlides: slideEntries.length,
  };
}

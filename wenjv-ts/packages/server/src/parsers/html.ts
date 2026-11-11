import { parseHTML } from 'linkedom';
import { Readability } from '@mozilla/readability';

export interface ParsedHtmlResult {
  title: string;
  text: string;
  excerpt?: string;
  byline?: string;
}

export function parseHtml(htmlContent: string): ParsedHtmlResult {
  const { document } = parseHTML(htmlContent);
  const reader = new Readability(document);
  const article = reader.parse();

  if (article && article.textContent) {
    return {
      title: article.title || document.title || '',
      text: article.textContent.trim(),
      excerpt: article.excerpt || '',
      byline: article.byline || '',
    };
  }

  // Fallback if readability cannot parse content
  const bodyText = document.body ? document.body.textContent || '' : '';
  return {
    title: document.title || '',
    text: bodyText.trim(),
  };
}

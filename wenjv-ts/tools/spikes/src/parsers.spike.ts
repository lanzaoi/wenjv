import JSZip from 'jszip';
import { parseText } from '../../../packages/server/src/parsers/text.js';
import { parseHtml } from '../../../packages/server/src/parsers/html.js';
import { parsePptx } from '../../../packages/server/src/parsers/pptx.js';

export async function runParsersSpike(): Promise<void> {
  // 1. Text parser
  const txt = parseText('Hello world\nThis is a test.');
  if (!txt.text.includes('Hello world')) {
    throw new Error('Text parser failed');
  }

  // 2. HTML parser (Readability + Linkedom)
  const htmlSample = `
    <!DOCTYPE html>
    <html>
      <head><title>Test Article Title</title></head>
      <body>
        <article>
          <h1>Test Article Title</h1>
          <p>This is the main content of the article with important insights on TypeScript.</p>
        </article>
      </body>
    </html>
  `;
  const htmlRes = parseHtml(htmlSample);
  if (!htmlRes.title.includes('Test Article Title') || !htmlRes.text.includes('important insights')) {
    throw new Error(`HTML parser failed: title=${htmlRes.title}, text=${htmlRes.text}`);
  }

  // 3. PPTX parser (synthesize minimal valid PPTX zip)
  const zip = new JSZip();
  zip.file(
    'ppt/slides/slide1.xml',
    `<?xml version="1.0" encoding="UTF-8"?>
    <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:cSld><p:spTree><p:sp><p:txBody>
        <a:p><a:r><a:t>Slide 1 Title</a:t></a:r></a:p>
        <a:p><a:r><a:t>Slide 1 Content</a:t></a:r></a:p>
      </p:txBody></p:sp></p:spTree></p:cSld>
    </p:sld>`
  );
  zip.file(
    'ppt/slides/slide2.xml',
    `<?xml version="1.0" encoding="UTF-8"?>
    <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:cSld><p:spTree><p:sp><p:txBody>
        <a:p><a:r><a:t>Slide 2 Summary</a:t></a:r></a:p>
      </p:txBody></p:sp></p:spTree></p:cSld>
    </p:sld>`
  );
  const pptxBuffer = await zip.generateAsync({ type: 'nodebuffer' });
  const pptxRes = await parsePptx(pptxBuffer);
  if (pptxRes.slides.length !== 2 || !pptxRes.text.includes('Slide 1 Title') || !pptxRes.text.includes('Slide 2 Summary')) {
    throw new Error(`PPTX parser failed: slides=${pptxRes.slides.length}, text=${pptxRes.text}`);
  }
}

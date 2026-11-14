import { config } from '../config.js';

export type OcrMode = 'auto' | 'general' | 'formula';

export interface OcrResult {
  text: string;
  engine: string;
  mode: string;
  elapsed_ms: number;
  pages?: number;
}

export interface OcrClientOptions {
  enabled?: boolean;
  baseUrl?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

/**
 * HTTP client for the local Python CPU OCR sidecar (PP-OCRv5 Mobile + Pix2Text).
 * Designed to fail-open so ingestion never stalls if the sidecar is stopped.
 */
export class OcrSidecarClient {
  private readonly enabledOverride: boolean | undefined;
  private readonly baseUrlOverride: string | undefined;
  private readonly timeoutOverride: number | undefined;
  private readonly fetchFn: typeof fetch;

  constructor(options?: OcrClientOptions) {
    this.enabledOverride = options?.enabled;
    this.baseUrlOverride = options?.baseUrl;
    this.timeoutOverride = options?.timeoutMs;
    this.fetchFn = options?.fetchImpl ?? fetch;
  }

  public isEnabled(): boolean {
    return this.enabledOverride ?? config.OCR_ENABLED;
  }

  private getBaseUrl(): string {
    return (this.baseUrlOverride ?? config.OCR_SIDECAR_URL).replace(/\/+$/, '');
  }

  private getTimeoutMs(): number {
    return this.timeoutOverride ?? config.OCR_TIMEOUT_MS;
  }

  public async health(): Promise<{ ok: boolean; status?: string; engines?: Record<string, unknown> }> {
    if (!this.isEnabled()) {
      return { ok: false, status: 'disabled' };
    }
    try {
      const resp = await this.fetchFn(`${this.getBaseUrl()}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(Math.min(5000, this.getTimeoutMs())),
      });
      if (!resp.ok) {
        return { ok: false, status: `http_${resp.status}` };
      }
      const data = (await resp.json()) as Record<string, unknown>;
      const engines = data['engines'] as Record<string, unknown> | undefined;
      return {
        ok: data['status'] === 'ok',
        status: String(data['status'] || 'unknown'),
        ...(engines ? { engines } : {}),
      };
    } catch {
      return { ok: false, status: 'unreachable' };
    }
  }

  public async recognizeImage(
    imageBuffer: Buffer,
    filename: string,
    mode: OcrMode = 'auto'
  ): Promise<OcrResult | null> {
    return this.postMultipart('/ocr/image', imageBuffer, filename, { mode });
  }

  public async recognizePdf(
    pdfBuffer: Buffer,
    filename: string,
    mode: OcrMode = 'general',
    maxPages = 12
  ): Promise<OcrResult | null> {
    return this.postMultipart('/ocr/pdf', pdfBuffer, filename, {
      mode,
      max_pages: String(maxPages),
    });
  }

  private async postMultipart(
    endpointPath: string,
    buffer: Buffer,
    filename: string,
    fields: Record<string, string>
  ): Promise<OcrResult | null> {
    if (!this.isEnabled()) return null;

    try {
      const form = new FormData();
      const bytes = Uint8Array.from(buffer);
      form.append('file', new Blob([bytes], { type: 'application/octet-stream' }), filename);
      for (const [k, v] of Object.entries(fields)) {
        form.append(k, v);
      }

      const resp = await this.fetchFn(`${this.getBaseUrl()}${endpointPath}`, {
        method: 'POST',
        body: form,
        signal: AbortSignal.timeout(this.getTimeoutMs()),
      });

      if (!resp.ok) {
        const errText = await resp.text().catch(() => '');
        console.warn(`[OCR] ${endpointPath} returned HTTP ${resp.status}: ${errText.slice(0, 200)}`);
        return null;
      }

      const data = (await resp.json()) as Partial<OcrResult>;
      const text = typeof data.text === 'string' ? data.text.trim() : '';
      if (!text) return null;

      return {
        text,
        engine: typeof data.engine === 'string' ? data.engine : 'unknown',
        mode: typeof data.mode === 'string' ? data.mode : fields['mode'] || 'auto',
        elapsed_ms: typeof data.elapsed_ms === 'number' ? data.elapsed_ms : 0,
        ...(typeof data.pages === 'number' ? { pages: data.pages } : {}),
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[OCR] Sidecar call failed (${endpointPath}): ${msg}`);
      return null;
    }
  }
}

let _ocrClient: OcrSidecarClient | null = null;

export function getOcrClient(): OcrSidecarClient {
  if (!_ocrClient) {
    _ocrClient = new OcrSidecarClient();
  }
  return _ocrClient;
}

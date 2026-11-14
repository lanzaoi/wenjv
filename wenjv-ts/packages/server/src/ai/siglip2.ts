import fs from 'node:fs';
import path from 'node:path';
import ort from 'onnxruntime-node';
import { Tokenizer } from '@huggingface/tokenizers';
import sharp from 'sharp';
import { config } from '../config.js';

const VISION_MODEL_CANDIDATES = [
  'vision_model_q4.onnx',
  'vision_model_q4f16.onnx',
  'vision_model.onnx',
  'vision_model_fp16.onnx',
  'vision_model_int8.onnx',
] as const;

export class SigLIP2Engine {
  private textSession: ort.InferenceSession | null = null;
  private visionSession: ort.InferenceSession | null = null;
  private tokenizer: Tokenizer | null = null;
  private modelDir: string;
  private visionSupported = false;

  constructor(modelDir?: string) {
    this.modelDir = modelDir || path.join(config.resolvedModelsDir, 'siglip2_onnx');
  }

  public isVisionSupported(): boolean {
    return this.visionSupported;
  }

  public async init(): Promise<void> {
    if (this.textSession && this.tokenizer) {
      return;
    }
    const textModelPath = path.join(this.modelDir, 'onnx', 'text_model_int8.onnx');
    const tokJsonPath = path.join(this.modelDir, 'tokenizer.json');
    const tokCfgPath = path.join(this.modelDir, 'tokenizer_config.json');

    if (!fs.existsSync(textModelPath) || !fs.existsSync(tokJsonPath)) {
      throw new Error(`SigLIP 2 ONNX files missing in ${this.modelDir}`);
    }

    const tokJson = JSON.parse(fs.readFileSync(tokJsonPath, 'utf8'));
    const tokCfg = fs.existsSync(tokCfgPath)
      ? JSON.parse(fs.readFileSync(tokCfgPath, 'utf8'))
      : {};

    this.tokenizer = new Tokenizer(tokJson, tokCfg);

    const opts: ort.SessionOptions = {
      intraOpNumThreads: 4,
      interOpNumThreads: 1,
      graphOptimizationLevel: 'all',
      executionProviders: ['cpu'],
    };

    this.textSession = await ort.InferenceSession.create(textModelPath, opts);

    for (const candidate of VISION_MODEL_CANDIDATES) {
      const visionModelPath = path.join(this.modelDir, 'onnx', candidate);
      if (!fs.existsSync(visionModelPath)) continue;
      try {
        this.visionSession = await ort.InferenceSession.create(visionModelPath, opts);
        this.visionSupported = true;
        break;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.warn(`[SigLIP2] Vision model ${candidate} failed to load on CPU EP: ${msg}`);
      }
    }
  }

  public async embedText(text: string): Promise<number[]> {
    await this.init();
    if (!this.textSession || !this.tokenizer) {
      throw new Error('SigLIP2 text session not initialized');
    }

    const maxLen = 64;
    const out = this.tokenizer.encode(text.trim() ? text : ' ');
    const ids = out.ids.slice(0, maxLen);
    while (ids.length < maxLen) {
      ids.push(0);
    }

    const inputIds = new BigInt64Array(ids.map(BigInt));
    const feeds: Record<string, ort.Tensor> = {
      input_ids: new ort.Tensor('int64', inputIds, [1, maxLen]),
    };

    const results = await this.textSession.run(feeds);
    const pooler = results['pooler_output'] || results['last_hidden_state'];
    if (!pooler) {
      throw new Error('SigLIP2 missing text output');
    }

    const raw = pooler.data as Float32Array;
    const dims = 768;
    const vec = Array.from(raw.subarray(0, dims));

    let normSq = 0;
    for (const v of vec) normSq += v * v;
    const norm = Math.sqrt(normSq) || 1e-12;
    return vec.map((v) => v / norm);
  }

  public async embedImage(imageBuffer: Buffer): Promise<number[]> {
    await this.init();
    if (!this.visionSupported || !this.visionSession) {
      return new Array(768).fill(0);
    }

    try {
      const resized = await sharp(imageBuffer)
        .removeAlpha()
        .toColorspace('srgb')
        .resize(224, 224, { fit: 'fill', kernel: 'linear' })
        .raw()
        .toBuffer();

      const pixelValues = new Float32Array(3 * 224 * 224);
      for (let i = 0; i < 224 * 224; i++) {
        const r = resized[i * 3 + 0] ?? 0;
        const g = resized[i * 3 + 1] ?? 0;
        const b = resized[i * 3 + 2] ?? 0;

        pixelValues[0 * 224 * 224 + i] = (r / 255.0 - 0.5) / 0.5;
        pixelValues[1 * 224 * 224 + i] = (g / 255.0 - 0.5) / 0.5;
        pixelValues[2 * 224 * 224 + i] = (b / 255.0 - 0.5) / 0.5;
      }

      const feeds: Record<string, ort.Tensor> = {
        pixel_values: new ort.Tensor('float32', pixelValues, [1, 3, 224, 224]),
      };

      const results = await this.visionSession.run(feeds);
      const pooler = results['pooler_output'];
      if (!pooler) return new Array(768).fill(0);

      const raw = pooler.data as Float32Array;
      const dims = 768;
      const vec = Array.from(raw.subarray(0, dims));

      let normSq = 0;
      for (const v of vec) normSq += v * v;
      const norm = Math.sqrt(normSq) || 1e-12;
      return vec.map((v) => v / norm);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[SigLIP2] embedImage failed: ${msg}`);
      return new Array(768).fill(0);
    }
  }
}

let _siglip2: SigLIP2Engine | null = null;

export function getSigLIP2(): SigLIP2Engine {
  if (!_siglip2) {
    _siglip2 = new SigLIP2Engine();
  }
  return _siglip2;
}

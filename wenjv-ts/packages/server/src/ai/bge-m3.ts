import fs from 'node:fs';
import path from 'node:path';
import ort from 'onnxruntime-node';
import { Tokenizer } from '@huggingface/tokenizers';
import { config } from '../config.js';

export class BGEM3Embedder {
  private session: ort.InferenceSession | null = null;
  private tokenizer: Tokenizer | null = null;
  private modelDir: string;

  constructor(modelDir?: string) {
    this.modelDir = modelDir || path.join(config.resolvedModelsDir, 'bge_m3_onnx');
  }

  public async init(): Promise<void> {
    if (this.session && this.tokenizer) {
      return;
    }
    const modelPath = path.join(this.modelDir, 'model_quantized.onnx');
    const tokJsonPath = path.join(this.modelDir, 'tokenizer.json');
    const tokCfgPath = path.join(this.modelDir, 'tokenizer_config.json');

    if (!fs.existsSync(modelPath) || !fs.existsSync(tokJsonPath)) {
      throw new Error(`BGE-M3 ONNX files missing in ${this.modelDir}`);
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

    this.session = await ort.InferenceSession.create(modelPath, opts);
  }

  public async embedDocuments(texts: string[]): Promise<number[][]> {
    if (texts.length === 0) {
      return [];
    }
    await this.init();
    if (!this.session || !this.tokenizer) {
      throw new Error('Embedder failed to initialize');
    }

    const batchSize = 16;
    const allVectors: number[][] = [];

    for (let i = 0; i < texts.length; i += batchSize) {
      const batchTexts = texts.slice(i, i + batchSize);
      const encodedList = batchTexts.map((t) => {
        // Python slice[:1500] in unicode codepoints
        const codepoints = Array.from(t);
        const truncatedText = codepoints.length > 1500 ? codepoints.slice(0, 1500).join('') : t;
        const out = this.tokenizer!.encode(truncatedText.trim() ? truncatedText : ' ');
        return {
          ids: out.ids.slice(0, 512),
          attentionMask: out.attention_mask.slice(0, 512),
        };
      });

      const maxLen = Math.max(...encodedList.map((e) => e.ids.length), 1);
      const batchCount = batchTexts.length;

      const inputIds = new BigInt64Array(batchCount * maxLen);
      const attnMask = new BigInt64Array(batchCount * maxLen);

      for (let r = 0; r < batchCount; r++) {
        const item = encodedList[r];
        if (!item) continue;
        for (let c = 0; c < item.ids.length; c++) {
          const val = item.ids[c];
          const mask = item.attentionMask[c];
          if (val !== undefined) inputIds[r * maxLen + c] = BigInt(val);
          if (mask !== undefined) attnMask[r * maxLen + c] = BigInt(mask);
        }
      }

      const feeds: Record<string, ort.Tensor> = {
        input_ids: new ort.Tensor('int64', inputIds, [batchCount, maxLen]),
        attention_mask: new ort.Tensor('int64', attnMask, [batchCount, maxLen]),
      };

      const results = await this.session.run(feeds);
      const dense = results['dense_vecs'];
      if (!dense) {
        throw new Error('Missing dense_vecs in model output');
      }

      const rawData = dense.data as Float32Array;
      const dims = 1024;

      for (let r = 0; r < batchCount; r++) {
        const rowSlice = Array.from(rawData.subarray(r * dims, (r + 1) * dims));
        let normSq = 0;
        for (const v of rowSlice) {
          normSq += v * v;
        }
        const norm = Math.sqrt(normSq) || 1e-12;
        const normalized = rowSlice.map((v) => v / norm);
        allVectors.push(normalized);
      }
    }

    return allVectors;
  }

  public async embedQuery(text: string): Promise<number[]> {
    const res = await this.embedDocuments([text]);
    return res[0] ?? new Array(1024).fill(0);
  }
}

let _embedder: BGEM3Embedder | null = null;

export function getEmbedder(): BGEM3Embedder {
  if (!_embedder) {
    _embedder = new BGEM3Embedder();
  }
  return _embedder;
}

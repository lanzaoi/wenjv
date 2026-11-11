import fs from 'node:fs';
import path from 'node:path';
import ort from 'onnxruntime-node';
import { Tokenizer } from '@huggingface/tokenizers';
import { config } from '../config.js';

export interface RerankResult {
  index: number;
  relevanceScore: number;
}

export class BGEReranker {
  private session: ort.InferenceSession | null = null;
  private tokenizer: Tokenizer | null = null;
  private modelDir: string;

  constructor(modelDir?: string) {
    this.modelDir = modelDir || path.join(config.resolvedModelsDir, 'bge_reranker_base');
  }

  public async init(): Promise<void> {
    if (this.session && this.tokenizer) {
      return;
    }
    const modelPath = path.join(this.modelDir, 'model_quantized.onnx');
    const tokJsonPath = path.join(this.modelDir, 'tokenizer.json');
    const tokCfgPath = path.join(this.modelDir, 'tokenizer_config.json');

    if (!fs.existsSync(modelPath) || !fs.existsSync(tokJsonPath)) {
      throw new Error(`BGE Reranker ONNX files missing in ${this.modelDir}`);
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

  public async rerank(query: string, documents: string[]): Promise<RerankResult[]> {
    if (documents.length === 0) {
      return [];
    }
    await this.init();
    if (!this.session || !this.tokenizer) {
      throw new Error('Reranker failed to initialize');
    }

    // Sort documents by character length to avoid unnecessary padding computation (matches Python)
    const indexedDocs = documents.map((doc, idx) => ({ doc, origIdx: idx }));
    indexedDocs.sort((a, b) => a.doc.length - b.doc.length);

    const sortedDocs = indexedDocs.map((item) => item.doc);
    const origIndices = indexedDocs.map((item) => item.origIdx);

    const maxLen = config.RERANK_MAX_LENGTH || 256;
    const microBatchSize = config.RERANK_MICRO_BATCH_SIZE || 4;
    const rawScores: number[] = [];

    for (let i = 0; i < sortedDocs.length; i += microBatchSize) {
      const batchDocs = sortedDocs.slice(i, i + microBatchSize);
      const encodedList = batchDocs.map((doc) => {
        const out = this.tokenizer!.encode(query, { text_pair: doc });
        return {
          ids: out.ids.slice(0, maxLen),
          attentionMask: out.attention_mask.slice(0, maxLen),
        };
      });

      const maxSeq = Math.max(...encodedList.map((e) => e.ids.length), 1);
      const batchCount = batchDocs.length;

      const inputIds = new BigInt64Array(batchCount * maxSeq);
      const attnMask = new BigInt64Array(batchCount * maxSeq);

      for (let r = 0; r < batchCount; r++) {
        const item = encodedList[r];
        if (!item) continue;
        for (let c = 0; c < item.ids.length; c++) {
          const val = item.ids[c];
          const mask = item.attentionMask[c];
          if (val !== undefined) inputIds[r * maxSeq + c] = BigInt(val);
          if (mask !== undefined) attnMask[r * maxSeq + c] = BigInt(mask);
        }
      }

      const feeds: Record<string, ort.Tensor> = {
        input_ids: new ort.Tensor('int64', inputIds, [batchCount, maxSeq]),
        attention_mask: new ort.Tensor('int64', attnMask, [batchCount, maxSeq]),
      };

      const results = await this.session.run(feeds);
      const logits = results['logits'];
      if (!logits) {
        throw new Error('Missing logits in reranker output');
      }

      const rawData = logits.data as Float32Array;
      for (let r = 0; r < batchCount; r++) {
        const logit = rawData[r] ?? 0;
        const score = 1.0 / (1.0 + Math.exp(-logit));
        rawScores.push(score);
      }
    }

    const results: RerankResult[] = origIndices.map((origIdx, i) => ({
      index: origIdx,
      relevanceScore: rawScores[i] ?? 0,
    }));

    results.sort((a, b) => b.relevanceScore - a.relevanceScore);
    return results;
  }
}

let _reranker: BGEReranker | null = null;

export function getReranker(): BGEReranker {
  if (!_reranker) {
    _reranker = new BGEReranker();
  }
  return _reranker;
}

import { BGEM3Embedder } from '../../../packages/server/src/ai/bge-m3.js';

export async function runBgeM3Spike(): Promise<void> {
  const embedder = new BGEM3Embedder();
  await embedder.init();

  const texts = [
    '这是第一篇中文测试文档，测试BGE-M3模型在Node.js中的嵌入能力。',
    '这是第二篇关于人工智能和知识库检索的中文技术文档。',
    'TypeScript and Node.js provide excellent performance for full-stack applications.',
    '机器学习与深度学习是现代人工智能的两大基石。',
  ];

  const vectors = await embedder.embedDocuments(texts);
  if (vectors.length !== texts.length) {
    throw new Error(`Expected ${texts.length} vectors, got ${vectors.length}`);
  }

  for (const vec of vectors) {
    if (vec.length !== 1024) {
      throw new Error(`Expected vector dimension 1024, got ${vec.length}`);
    }
    const norm = Math.sqrt(vec.reduce((sum: number, x: number) => sum + x * x, 0));
    if (Math.abs(norm - 1.0) > 0.01) {
      throw new Error(`Vector not L2 normalized: norm = ${norm}`);
    }
  }

  const qVec = await embedder.embedQuery('人工智能知识库');
  if (qVec.length !== 1024) {
    throw new Error('Query vector dimension mismatch');
  }
}

import { BGEReranker } from '../../../packages/server/src/ai/reranker.js';

export async function runRerankerSpike(): Promise<void> {
  const reranker = new BGEReranker();
  await reranker.init();

  const query = '什么是问据系统？';
  const docs = [
    '今天天气很好，阳光明媚，适合出门散步。',
    '问据（Wenjv）是一个私有个人知识库系统，基于RAG架构和多模态检索技术。',
    '如何使用Python编写异步Web服务器？',
  ];

  const results = await reranker.rerank(query, docs);
  if (results.length !== docs.length) {
    throw new Error(`Expected ${docs.length} rerank results, got ${results.length}`);
  }

  // The most relevant document should be index 1
  if (results[0]?.index !== 1) {
    throw new Error(`Expected top rerank result to be doc index 1, got ${results[0]?.index}`);
  }

  // Scores should be strictly in descending order
  for (let i = 1; i < results.length; i++) {
    const prev = results[i - 1]?.relevanceScore ?? 0;
    const curr = results[i]?.relevanceScore ?? 0;
    if (prev < curr) {
      throw new Error(`Rerank results not sorted descending: ${prev} < ${curr}`);
    }
  }
}

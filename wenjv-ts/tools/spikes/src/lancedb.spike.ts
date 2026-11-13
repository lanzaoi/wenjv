import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { TextVectorStore } from '../../../packages/server/src/vector/text-store.js';

export async function runLanceDbSpike(): Promise<void> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lancedb-spike-'));
  const store = new TextVectorStore(tmpDir);
  await store.init();

  const dummyVec1 = new Array(1024).fill(0.01);
  dummyVec1[0] = 1.0;
  const dummyVec2 = new Array(1024).fill(0.01);
  dummyVec2[1] = 1.0;

  await store.addVectors([
    {
      id: 'doc-1',
      vector: dummyVec1,
      user_id: '1',
      entity_type: 'resource',
      entity_id: 1,
      resource_type: 'file',
    },
    {
      id: 'doc-2',
      vector: dummyVec2,
      user_id: '1',
      entity_type: 'resource',
      entity_id: 2,
      resource_type: 'file',
    },
  ]);

  const searchHits = await store.search(dummyVec1, { limit: 2, userId: '1' });
  if (searchHits.length === 0) {
    throw new Error('LanceDB search returned 0 hits');
  }
  if (searchHits[0]?.id !== 'doc-1') {
    throw new Error(`LanceDB search top hit was ${searchHits[0]?.id}, expected doc-1`);
  }

  await store.deleteByEntity('resource', 1, '1');
  const afterDelete = await store.search(dummyVec1, { limit: 2, userId: '1' });
  if (afterDelete.some((h) => h.id === 'doc-1')) {
    throw new Error('LanceDB deleteByEntity failed to remove doc-1');
  }

  fs.rmSync(tmpDir, { recursive: true, force: true });
}

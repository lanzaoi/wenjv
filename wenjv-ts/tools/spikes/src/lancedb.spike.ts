import * as lancedb from '@lancedb/lancedb';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { DocumentStore } from '../../../packages/server/src/vector/document-store.js';

export async function runLanceDbSpike(): Promise<void> {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lancedb-spike-'));
  const store = new DocumentStore(tmpDir);
  await store.init();

  const dummyVec1 = new Array(1024).fill(0.01);
  dummyVec1[0] = 1.0;
  const dummyVec2 = new Array(1024).fill(0.01);
  dummyVec2[1] = 1.0;

  await store.addDocuments([
    {
      id: 'doc-1',
      vector: dummyVec1,
      page_content: 'LanceDB vector store test item 1',
      source: 'test.md',
      page: '1',
      title: 'Item 1',
      filename: 'test.md',
      belongs_to: 'test.md',
      user_id: '1',
      link_id: '',
      file_id: '1',
      source_type: 'file',
      resource_id: '1',
      chunk_group: 'g1',
      chunk_order: 0,
      image_path: '',
    },
    {
      id: 'doc-2',
      vector: dummyVec2,
      page_content: 'LanceDB vector store test item 2',
      source: 'test2.md',
      page: '1',
      title: 'Item 2',
      filename: 'test2.md',
      belongs_to: 'test2.md',
      user_id: '1',
      link_id: '',
      file_id: '2',
      source_type: 'file',
      resource_id: '2',
      chunk_group: 'g2',
      chunk_order: 0,
      image_path: '',
    },
  ]);

  const searchHits = await store.search(dummyVec1, { limit: 2 });
  if (searchHits.length === 0) {
    throw new Error('LanceDB search returned 0 hits');
  }
  if (searchHits[0]?.id !== 'doc-1') {
    throw new Error(`LanceDB search top hit was ${searchHits[0]?.id}, expected doc-1`);
  }

  await store.deleteByResourceId('1');
  const afterDelete = await store.search(dummyVec1, { limit: 2 });
  if (afterDelete.some((h: { id: string }) => h.id === 'doc-1')) {
    throw new Error('LanceDB deleteByResourceId failed to remove doc-1');
  }

  fs.rmSync(tmpDir, { recursive: true, force: true });
}

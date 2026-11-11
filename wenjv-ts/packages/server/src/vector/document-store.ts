import fs from 'node:fs';
import * as lancedb from '@lancedb/lancedb';
import { config } from '../config.js';

export interface DocumentVectorItem {
  id: string;
  vector: number[];
  page_content: string;
  source: string;
  page: string;
  title: string;
  filename: string;
  belongs_to: string;
  user_id: string;
  link_id: string;
  file_id: string;
  source_type: string;
  resource_id: string;
  chunk_group: string;
  chunk_order: number;
  image_path: string;
}

export interface VectorSearchResult {
  id: string;
  page_content: string;
  source: string;
  page: string;
  title: string;
  filename: string;
  belongs_to: string;
  user_id: string;
  link_id: string;
  file_id: string;
  source_type: string;
  resource_id: string;
  chunk_group: string;
  chunk_order: number;
  image_path: string;
  _distance?: number;
  score?: number;
}

export interface VectorSearchOptions {
  limit?: number | undefined;
  userId?: string | number | null | undefined;
  belongsTo?: string | null | undefined;
  sourceType?: string | null | undefined;
  includeSources?: string[] | null | undefined;
}

export class DocumentStore {
  private db: lancedb.Connection | null = null;
  private table: lancedb.Table | null = null;
  private lanceDir: string;

  constructor(lanceDir?: string) {
    this.lanceDir = lanceDir || config.resolvedLanceDir;
  }

  public getLanceDir(): string {
    return this.lanceDir;
  }

  public async init(): Promise<void> {
    if (this.db && this.table) {
      return;
    }
    if (!fs.existsSync(this.lanceDir)) {
      fs.mkdirSync(this.lanceDir, { recursive: true });
    }

    this.db = await lancedb.connect(this.lanceDir);
    const tableNames = await this.db.tableNames();

    if (tableNames.includes('document_store')) {
      this.table = await this.db.openTable('document_store');
    } else {
      // Create empty table with initial record then delete it
      const seed: Record<string, unknown>[] = [
        {
          id: '__seed__',
          vector: new Array(1024).fill(0),
          page_content: '',
          source: '',
          page: '',
          title: '',
          filename: '',
          belongs_to: '',
          user_id: '',
          link_id: '',
          file_id: '',
          source_type: '',
          resource_id: '',
          chunk_group: '',
          chunk_order: 0,
          image_path: '',
        },
      ];
      this.table = await this.db.createTable('document_store', seed);
      await this.table.delete("id = '__seed__'");
    }
  }

  public async addDocuments(docs: DocumentVectorItem[]): Promise<void> {
    if (docs.length === 0) return;
    await this.init();
    if (!this.table) throw new Error('Document store not initialized');

    const records = docs.map((d) => ({
      id: d.id,
      vector: d.vector,
      page_content: d.page_content || '',
      source: d.source || '',
      page: d.page || '',
      title: d.title || '',
      filename: d.filename || '',
      belongs_to: d.belongs_to || '',
      user_id: String(d.user_id || ''),
      link_id: String(d.link_id || ''),
      file_id: String(d.file_id || ''),
      source_type: String(d.source_type || ''),
      resource_id: String(d.resource_id || ''),
      chunk_group: d.chunk_group || '',
      chunk_order: d.chunk_order ?? 0,
      image_path: d.image_path || '',
    }));

    await this.table.add(records);
  }

  public async search(
    queryVector: number[],
    options: VectorSearchOptions = {}
  ): Promise<VectorSearchResult[]> {
    await this.init();
    if (!this.table) throw new Error('Document store not initialized');

    const limit = options.limit ?? 20;
    let query = this.table.vectorSearch(queryVector).limit(limit);

    const filterParts: string[] = [];
    if (options.userId !== undefined && options.userId !== null) {
      filterParts.push(`user_id = '${String(options.userId).replace(/'/g, "''")}'`);
    }
    if (options.belongsTo) {
      filterParts.push(`belongs_to = '${options.belongsTo.replace(/'/g, "''")}'`);
    }
    if (options.sourceType) {
      filterParts.push(`source_type = '${options.sourceType.replace(/'/g, "''")}'`);
    }
    if (options.includeSources && options.includeSources.length > 0) {
      const srcList = options.includeSources
        .filter(Boolean)
        .map((s) => `'${s.replace(/'/g, "''")}'`)
        .join(', ');
      if (srcList) {
        filterParts.push(`(filename IN (${srcList}) OR title IN (${srcList}))`);
      }
    }

    if (filterParts.length > 0) {
      query = query.where(filterParts.join(' AND '));
    }

    const rows = (await query.toArray()) as unknown as VectorSearchResult[];
    return rows.map((r) => {
      const dist = r._distance ?? 1.0;
      // Lance returns L2 distance; convert to similarity score
      const sim = 1.0 / (1.0 + dist);
      return {
        ...r,
        score: sim,
      };
    });
  }

  public async deleteByResourceId(resourceId: string, userId?: string | number | null): Promise<void> {
    await this.init();
    if (!this.table) return;
    const escaped = resourceId.replace(/'/g, "''");
    let filter = `resource_id = '${escaped}'`;
    if (userId !== undefined && userId !== null) {
      filter += ` AND user_id = '${String(userId).replace(/'/g, "''")}'`;
    }
    try {
      await this.table.delete(filter);
    } catch {
      // ignore
    }
  }

  public async deleteByFilename(filename: string, belongsTo?: string | null): Promise<void> {
    await this.init();
    if (!this.table) return;
    const escaped = filename.replace(/'/g, "''");
    let filter = `filename = '${escaped}'`;
    if (belongsTo) {
      filter += ` AND belongs_to = '${belongsTo.replace(/'/g, "''")}'`;
    }
    try {
      await this.table.delete(filter);
    } catch {
      // ignore
    }
  }

  public async deleteByLinkId(linkId: string, belongsTo?: string | null): Promise<void> {
    await this.init();
    if (!this.table) return;
    const escaped = linkId.replace(/'/g, "''");
    let filter = `link_id = '${escaped}'`;
    if (belongsTo) {
      filter += ` AND belongs_to = '${belongsTo.replace(/'/g, "''")}'`;
    }
    try {
      await this.table.delete(filter);
    } catch {
      // ignore
    }
  }
}

let _docStore: DocumentStore | null = null;

export function resetDocumentStore(): void {
  _docStore = null;
}

export function getDocumentStore(lanceDir?: string): DocumentStore {
  const targetDir = lanceDir || config.resolvedLanceDir;
  if (!_docStore || _docStore.getLanceDir() !== targetDir) {
    _docStore = new DocumentStore(targetDir);
  }
  return _docStore;
}

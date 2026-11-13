import fs from 'node:fs';
import * as lancedb from '@lancedb/lancedb';
import { config } from '../config.js';
import type { ChunkEntityType, ChunkResourceType } from '../db/chunks.js';

export interface TextVectorItem {
  id: string;
  vector: number[];
  user_id: string | number;
  entity_type: ChunkEntityType;
  entity_id: string | number;
  resource_type: ChunkResourceType;
}

export interface TextVectorSearchResult {
  id: string;
  user_id: string;
  entity_type: ChunkEntityType;
  entity_id: number;
  resource_type: ChunkResourceType;
  _distance?: number;
  score: number;
}

export interface TextVectorSearchOptions {
  limit?: number | undefined;
  userId?: string | number | null | undefined;
  entityType?: ChunkEntityType | null | undefined;
  resourceType?: ChunkResourceType | null | undefined;
  entityRefs?: Array<{ entity_type: ChunkEntityType; entity_id: number }> | null | undefined;
}

function escapeSqlString(v: string | number): string {
  return String(v).replace(/'/g, "''");
}

/**
 * Slim LanceDB text vector store (`text_vectors`).
 * Stores only vector + minimal relational foreign keys; text content and metadata
 * are batch-hydrated from SQLite `chunks`.
 */
export class TextVectorStore {
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
    const tableName = config.VECTOR_STORE_COLLECTION_NAME || 'text_vectors';
    const tableNames = await this.db.tableNames();

    if (tableNames.includes(tableName)) {
      this.table = await this.db.openTable(tableName);
    } else {
      const seed: Record<string, unknown>[] = [
        {
          id: '__seed__',
          vector: new Array(1024).fill(0),
          user_id: '',
          entity_type: 'resource',
          entity_id: '',
          resource_type: 'file',
        },
      ];
      this.table = await this.db.createTable(tableName, seed);
      await this.table.delete("id = '__seed__'");
    }
  }

  public async addVectors(items: TextVectorItem[]): Promise<void> {
    if (items.length === 0) return;
    await this.init();
    if (!this.table) throw new Error('Text vector store not initialized');

    const records = items.map((item) => ({
      id: item.id,
      vector: item.vector,
      user_id: String(item.user_id),
      entity_type: item.entity_type,
      entity_id: String(item.entity_id),
      resource_type: item.resource_type,
    }));

    await this.table.add(records);
  }

  public async search(
    queryVector: number[],
    options: TextVectorSearchOptions = {}
  ): Promise<TextVectorSearchResult[]> {
    await this.init();
    if (!this.table) throw new Error('Text vector store not initialized');

    if (options.entityRefs && options.entityRefs.length === 0) {
      return [];
    }

    const limit = options.limit ?? 20;
    let query = this.table.vectorSearch(queryVector).limit(limit);

    const filterParts: string[] = [];
    if (options.userId !== undefined && options.userId !== null) {
      filterParts.push(`user_id = '${escapeSqlString(options.userId)}'`);
    }
    if (options.entityType) {
      filterParts.push(`entity_type = '${escapeSqlString(options.entityType)}'`);
    }
    if (options.resourceType) {
      filterParts.push(`resource_type = '${escapeSqlString(options.resourceType)}'`);
    }
    if (options.entityRefs && options.entityRefs.length > 0) {
      const refFilters = options.entityRefs.map(
        (r) => `(entity_type = '${escapeSqlString(r.entity_type)}' AND entity_id = '${escapeSqlString(r.entity_id)}')`
      );
      filterParts.push(`(${refFilters.join(' OR ')})`);
    }

    if (filterParts.length > 0) {
      query = query.where(filterParts.join(' AND '));
    }

    const rows = (await query.toArray()) as Array<Record<string, unknown>>;
    return rows.map((r) => {
      const dist = typeof r['_distance'] === 'number' ? r['_distance'] : 1.0;
      return {
        id: String(r['id'] || ''),
        user_id: String(r['user_id'] || ''),
        entity_type: (r['entity_type'] === 'wiki' ? 'wiki' : 'resource') as ChunkEntityType,
        entity_id: Number(r['entity_id'] || 0),
        resource_type: String(r['resource_type'] || 'file') as ChunkResourceType,
        _distance: dist,
        score: 1.0 / (1.0 + dist),
      };
    });
  }

  public async deleteByEntity(
    entityType: ChunkEntityType,
    entityId: number | string,
    userId?: string | number | null
  ): Promise<void> {
    await this.init();
    if (!this.table) return;
    let filter = `entity_type = '${escapeSqlString(entityType)}' AND entity_id = '${escapeSqlString(entityId)}'`;
    if (userId !== undefined && userId !== null) {
      filter += ` AND user_id = '${escapeSqlString(userId)}'`;
    }
    try {
      await this.table.delete(filter);
    } catch {
      // ignore empty/non-matching table deletes
    }
  }
}

let _textStore: TextVectorStore | null = null;

export function resetTextStore(): void {
  _textStore = null;
}

export function getTextStore(lanceDir?: string): TextVectorStore {
  const targetDir = lanceDir || config.resolvedLanceDir;
  if (!_textStore || _textStore.getLanceDir() !== targetDir) {
    _textStore = new TextVectorStore(targetDir);
  }
  return _textStore;
}

import fs from 'node:fs';
import * as lancedb from '@lancedb/lancedb';
import { config } from '../config.js';

export type AssetOwnerType = 'resource' | 'wiki' | 'chat';

export interface VisualVectorItem {
  id: string;
  vector: number[];
  user_id: string | number;
  owner_type: AssetOwnerType;
  owner_id: string | number;
}

export interface VisualVectorSearchResult {
  id: string;
  user_id: string;
  owner_type: AssetOwnerType;
  owner_id: string;
  score: number;
  _distance: number;
}

export interface VisualSearchOptions {
  limit?: number | undefined;
  userId?: string | number | null | undefined;
  ownerType?: AssetOwnerType | null | undefined;
}

function escapeSqlString(v: string | number): string {
  return String(v).replace(/'/g, "''");
}

/**
 * Slim LanceDB visual vector store (`visual_vectors`).
 * Stores only SigLIP2 vector + owner foreign keys; metadata and file paths
 * are hydrated from SQLite `assets`.
 */
export class VisualVectorStore {
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
    const tableName = config.VISUAL_VECTOR_STORE_COLLECTION_NAME || 'visual_vectors';
    const tableNames = await this.db.tableNames();

    if (tableNames.includes(tableName)) {
      this.table = await this.db.openTable(tableName);
    } else {
      const seed: Record<string, unknown>[] = [
        {
          id: '__seed__',
          vector: new Array(768).fill(0),
          user_id: '',
          owner_type: 'resource',
          owner_id: '',
        },
      ];
      this.table = await this.db.createTable(tableName, seed);
      await this.table.delete("id = '__seed__'");
    }
  }

  public async addVectors(items: VisualVectorItem[]): Promise<void> {
    if (items.length === 0) return;
    await this.init();
    if (!this.table) throw new Error('Visual store not initialized');

    const records = items.map((item) => ({
      id: item.id,
      vector: item.vector,
      user_id: String(item.user_id),
      owner_type: item.owner_type,
      owner_id: String(item.owner_id),
    }));

    await this.table.add(records);
  }

  public async search(
    queryVector: number[],
    options: VisualSearchOptions = {}
  ): Promise<VisualVectorSearchResult[]> {
    await this.init();
    if (!this.table) return [];

    const limit = options.limit ?? 5;
    const filterParts: string[] = [];

    if (options.userId !== undefined && options.userId !== null && options.userId !== '') {
      filterParts.push(`user_id = '${escapeSqlString(options.userId)}'`);
    }
    if (options.ownerType) {
      filterParts.push(`owner_type = '${escapeSqlString(options.ownerType)}'`);
    }

    let searchBuilder = this.table.search(queryVector).limit(limit);
    if (filterParts.length > 0) {
      searchBuilder = searchBuilder.where(filterParts.join(' AND '));
    }

    const rows = (await searchBuilder.toArray()) as Array<Record<string, unknown>>;
    return rows.map((row) => {
      const dist = typeof row['_distance'] === 'number' ? row['_distance'] : 1.0;
      return {
        id: String(row['id'] || ''),
        user_id: String(row['user_id'] || ''),
        owner_type: String(row['owner_type'] || 'resource') as AssetOwnerType,
        owner_id: String(row['owner_id'] || ''),
        score: 1.0 / (1.0 + dist),
        _distance: dist,
      };
    });
  }

  public async deleteById(assetId: string, userId?: string | number): Promise<void> {
    await this.init();
    if (!this.table) return;
    let filter = `id = '${escapeSqlString(assetId)}'`;
    if (userId !== undefined && userId !== null) {
      filter += ` AND user_id = '${escapeSqlString(userId)}'`;
    }
    try {
      await this.table.delete(filter);
    } catch {
      // ignore
    }
  }

  public async deleteByOwner(ownerType: AssetOwnerType, ownerId: string | number, userId?: string | number): Promise<void> {
    await this.init();
    if (!this.table) return;
    let filter = `owner_type = '${escapeSqlString(ownerType)}' AND owner_id = '${escapeSqlString(ownerId)}'`;
    if (userId !== undefined && userId !== null) {
      filter += ` AND user_id = '${escapeSqlString(userId)}'`;
    }
    try {
      await this.table.delete(filter);
    } catch {
      // ignore
    }
  }
}

let _visualStore: VisualVectorStore | null = null;

export function resetVisualStore(): void {
  _visualStore = null;
}

export function getVisualStore(lanceDir?: string): VisualVectorStore {
  const targetDir = lanceDir || config.resolvedLanceDir;
  if (!_visualStore || _visualStore.getLanceDir() !== targetDir) {
    _visualStore = new VisualVectorStore(targetDir);
  }
  return _visualStore;
}

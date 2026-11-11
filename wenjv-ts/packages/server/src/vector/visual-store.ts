import fs from 'node:fs';
import * as lancedb from '@lancedb/lancedb';
import { config } from '../config.js';

export interface VisualVectorItem {
  id: string;
  vector: number[];
  page_content: string;
  image_path: string;
  source: string;
  page: string;
  title: string;
  filename: string;
  belongs_to: string;
  user_id: string;
  file_id: string;
  resource_id: string;
  source_type: string;
}

export interface VisualSearchResult {
  id: string;
  page_content: string;
  image_path: string;
  source: string;
  page: string;
  title: string;
  filename: string;
  belongs_to: string;
  user_id: string;
  file_id: string;
  resource_id: string;
  source_type: string;
  score?: number | undefined;
  _distance?: number | undefined;
}

export interface VisualSearchOptions {
  limit?: number | undefined;
  userId?: string | number | null | undefined;
  belongsTo?: string | null | undefined;
  sourceType?: string | null | undefined;
}

export class VisualStore {
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

    if (tableNames.includes('visual_store')) {
      this.table = await this.db.openTable('visual_store');
    } else {
      const seed: Record<string, unknown>[] = [
        {
          id: '__seed__',
          vector: new Array(768).fill(0),
          page_content: '',
          image_path: '',
          source: '',
          page: '',
          title: '',
          filename: '',
          belongs_to: '',
          user_id: '',
          file_id: '',
          resource_id: '',
          source_type: '',
        },
      ];
      this.table = await this.db.createTable('visual_store', seed);
      await this.table.delete("id = '__seed__'");
    }
  }

  public async addDocuments(docs: VisualVectorItem[]): Promise<void> {
    if (docs.length === 0) return;
    await this.init();
    if (!this.table) throw new Error('Visual store not initialized');

    const records = docs.map((d) => ({
      id: d.id,
      vector: d.vector,
      page_content: d.page_content || '',
      image_path: d.image_path || '',
      source: d.source || '',
      page: d.page || '',
      title: d.title || '',
      filename: d.filename || '',
      belongs_to: d.belongs_to || '',
      user_id: String(d.user_id || ''),
      file_id: String(d.file_id || ''),
      resource_id: String(d.resource_id || ''),
      source_type: String(d.source_type || ''),
    }));

    await this.table.add(records);
  }

  public async search(
    queryVector: number[],
    options: VisualSearchOptions = {}
  ): Promise<VisualSearchResult[]> {
    await this.init();
    if (!this.table) return [];

    const limit = options.limit || 5;
    const filterConditions: string[] = [];

    if (options.userId !== undefined && options.userId !== null && options.userId !== '') {
      const uid = String(options.userId).replace(/'/g, "''");
      if (options.belongsTo) {
        const belongs = options.belongsTo.replace(/'/g, "''");
        filterConditions.push(`(user_id = '${uid}' OR belongs_to = '${belongs}')`);
      } else {
        filterConditions.push(`user_id = '${uid}'`);
      }
    } else if (options.belongsTo) {
      filterConditions.push(`belongs_to = '${options.belongsTo.replace(/'/g, "''")}'`);
    }

    if (options.sourceType) {
      filterConditions.push(`source_type = '${options.sourceType.replace(/'/g, "''")}'`);
    }

    const filterExpr = filterConditions.join(' AND ');
    let searchBuilder = this.table.search(queryVector).limit(limit);

    if (filterExpr) {
      searchBuilder = searchBuilder.where(filterExpr);
    }

    const rows = (await searchBuilder.toArray()) as Array<Record<string, unknown>>;
    return rows.map((row) => ({
      id: String(row['id'] || ''),
      page_content: String(row['page_content'] || ''),
      image_path: String(row['image_path'] || ''),
      source: String(row['source'] || ''),
      page: String(row['page'] || ''),
      title: String(row['title'] || ''),
      filename: String(row['filename'] || ''),
      belongs_to: String(row['belongs_to'] || ''),
      user_id: String(row['user_id'] || ''),
      file_id: String(row['file_id'] || ''),
      resource_id: String(row['resource_id'] || ''),
      source_type: String(row['source_type'] || ''),
      score: typeof row['_distance'] === 'number' ? row['_distance'] : 0,
      _distance: typeof row['_distance'] === 'number' ? row['_distance'] : 0,
    }));
  }

  public async deleteByResourceId(resourceId: string, userId?: string | number): Promise<void> {
    await this.init();
    if (!this.table) return;
    const escaped = resourceId.replace(/'/g, "''");
    let filter = `(resource_id = '${escaped}' OR file_id = '${escaped}')`;
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
}

let _visualStore: VisualStore | null = null;

export function resetVisualStore(): void {
  _visualStore = null;
}

export function getVisualStore(lanceDir?: string): VisualStore {
  const targetDir = lanceDir || config.resolvedLanceDir;
  if (!_visualStore || _visualStore.getLanceDir() !== targetDir) {
    _visualStore = new VisualStore(targetDir);
  }
  return _visualStore;
}

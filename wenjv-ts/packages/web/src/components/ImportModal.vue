<template>
  <div v-if="show" class="import-backdrop" @click.self="closeModal">
    <div class="import-modal" role="dialog" aria-modal="true" aria-label="批量导入与旧库迁移">
      <header class="modal-head">
        <div>
          <h3>导入资料与旧库迁移</h3>
          <p class="modal-sub">支持本地批量文件/文件夹上传，或从旧版数据库无损导入到当前账号</p>
        </div>
        <button type="button" class="close-btn" aria-label="关闭弹窗" @click="closeModal">×</button>
      </header>

      <!-- Tab Switcher -->
      <div class="modal-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          :class="['tab-pill', { 'is-active': activeTab === 'batch' }]"
          @click="activeTab = 'batch'"
        >
          批量上传文件 / 文件夹
        </button>
        <button
          type="button"
          role="tab"
          :class="['tab-pill', { 'is-active': activeTab === 'legacy' }]"
          @click="openLegacyTab"
        >
          从旧库导入 (v1 → v2)
        </button>
      </div>

      <!-- TAB 1: Batch Upload -->
      <div v-if="activeTab === 'batch'" class="modal-body">
        <div
          class="batch-dropzone"
          :class="{ 'is-dragover': isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDropFiles"
        >
          <div class="dz-heading">拖拽多个文件到此处，或选择本地文件 / 文件夹</div>
          <div class="dz-formats">
            支持格式：PDF、Word (.docx)、PPT (.pptx)、Markdown (.md/.markdown)、TXT、CSV、JSON、HTML、SH、PNG/JPG（单文件 ≤ 25MB）
          </div>
          <div class="dz-btns">
            <button type="button" class="pick-btn is-primary" :disabled="uploadingBatch" @click="fileInputRef?.click()">
              选择多个文件
            </button>
            <button type="button" class="pick-btn" :disabled="uploadingBatch" @click="dirInputRef?.click()">
              选择整个文件夹
            </button>
          </div>
          <input
            ref="fileInputRef"
            type="file"
            multiple
            :accept="ACCEPT_ATTR"
            hidden
            @change="onPickFiles"
          />
          <input
            ref="dirInputRef"
            type="file"
            webkitdirectory
            directory
            multiple
            hidden
            @change="onPickFiles"
          />
        </div>

        <div class="batch-tags-row">
          <label for="batch-tags-input">批量附加标签（可选）</label>
          <input
            id="batch-tags-input"
            v-model="batchTagsInput"
            type="text"
            class="batch-tags-input"
            placeholder="多个标签用逗号或空格分隔，例如：项目文档 架构"
            :disabled="uploadingBatch"
          />
        </div>

        <div v-if="queue.length > 0" class="queue-section">
          <div class="queue-summary">
            <span>共 {{ queue.length }} 项 · 待传 {{ pendingCount }} · 成功 {{ doneCount }} · 跳过/失败 {{ skippedOrErrorCount }}</span>
            <button
              v-if="!uploadingBatch"
              type="button"
              class="clear-list-btn"
              @click="queue = []"
            >
              清空列表
            </button>
          </div>

          <div v-if="uploadingBatch || doneCount > 0" class="progress-track">
            <div class="progress-fill" :style="{ width: `${progressPercent}%` }" />
          </div>

          <ul class="queue-list">
            <li v-for="item in queue" :key="item.key" class="queue-row">
              <div class="q-info">
                <span class="q-name" :title="item.displayPath">{{ item.displayPath }}</span>
                <span class="q-size">{{ formatSize(item.file.size) }}</span>
              </div>
              <span :class="['q-status', `is-${item.status}`]">{{ item.message }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- TAB 2: Legacy v1 Import -->
      <div v-else class="modal-body">
        <div v-if="legacyError" class="inline-error">{{ legacyError }}</div>

        <!-- Option A: Detected Local ~/.config/wenjv -->
        <section class="legacy-card">
          <div class="legacy-card-head">
            <div>
              <h4>本机旧版目录一键导入</h4>
              <p class="legacy-desc">只读读取本机旧版数据库并迁移至当前登录账号，不会修改或覆盖原目录及当前已有页面。</p>
            </div>
            <button
              type="button"
              class="refresh-detect-btn"
              :disabled="detectingLegacy || importingLegacy"
              @click="runDetectLegacy"
            >
              {{ detectingLegacy ? '检测中...' : '重新检测' }}
            </button>
          </div>

          <div v-if="detectingLegacy" class="detect-muted">正在扫描本机旧版知识库...</div>

          <div v-else-if="detectInfo?.same_as_active" class="detect-muted">
            当前服务正在直接使用旧版目录，无需再次导入。
          </div>

          <div v-else-if="!detectInfo?.detected" class="detect-muted">
            未在本机默认位置检测到旧版 <code>~/.config/wenjv/wenjv.db</code> 数据库，可使用下方“上传备份文件导入”。
          </div>

          <div v-else class="detect-found">
            <div class="detect-path">已检测到只读源：<code>{{ detectInfo.source_label }}</code></div>
            <div v-if="detectInfo.preview" class="preview-metrics">
              <span>文件 {{ detectInfo.preview.files }} 份</span>
              <span>笔记 {{ detectInfo.preview.notes }} 篇</span>
              <span>链接 {{ detectInfo.preview.links }} 条</span>
              <span>Wiki {{ detectInfo.preview.wikiPages }} 篇</span>
              <span class="metric-ok">磁盘可读 {{ detectInfo.preview.foundOnDisk }} 份</span>
              <span v-if="detectInfo.preview.missingFiles > 0" class="metric-warn">
                自动跳过缺失文件 {{ detectInfo.preview.missingFiles }} 条
              </span>
            </div>
            <div class="legacy-actions">
              <button
                type="button"
                class="primary-go-btn"
                :disabled="importingLegacy"
                @click="runLocalLegacyImport"
              >
                {{ importingLegacy ? '正在导入...' : '一键从本机旧库导入' }}
              </button>
            </div>
          </div>
        </section>

        <!-- Option B: Upload Backup wenjv.db + Optional Attachments -->
        <section class="legacy-card">
          <div class="legacy-card-head">
            <div>
              <h4>上传旧版备份文件导入</h4>
              <p class="legacy-desc">手动选择旧版 <code>wenjv.db</code> 文件；若旧库内含附件或笔记文件，可一并选择原 <code>uploads</code> 文件夹上传。</p>
            </div>
          </div>

          <div class="bundle-pickers">
            <div class="picker-line">
              <span class="picker-label">1. 数据库文件 (必需)</span>
              <button type="button" class="pick-btn" :disabled="importingLegacy" @click="dbFileRef?.click()">
                选择 wenjv.db
              </button>
              <span class="picker-val">{{ selectedDbFile ? selectedDbFile.name : '未选择' }}</span>
              <input
                ref="dbFileRef"
                type="file"
                accept=".db,.sqlite,.sqlite3"
                hidden
                @change="onSelectDbFile"
              />
            </div>

            <div class="picker-line">
              <span class="picker-label">2. 原 uploads 附件 (可选)</span>
              <button type="button" class="pick-btn" :disabled="importingLegacy" @click="legacyAttachRef?.click()">
                选择 uploads 文件夹
              </button>
              <span class="picker-val">
                {{ selectedLegacyAttachments.length > 0 ? `已选 ${selectedLegacyAttachments.length} 个文件` : '未选择（仅导入数据库与 Wiki 正文）' }}
              </span>
              <input
                ref="legacyAttachRef"
                type="file"
                webkitdirectory
                directory
                multiple
                hidden
                @change="onSelectLegacyAttachments"
              />
            </div>
          </div>

          <div class="legacy-actions">
            <button
              type="button"
              class="pick-btn is-primary"
              :disabled="!selectedDbFile || importingLegacy"
              @click="runBundleImport"
            >
              {{ importingLegacy ? '正在迁移上传...' : '上传备份并导入' }}
            </button>
          </div>
        </section>

        <!-- Legacy Import Result Card -->
        <div v-if="legacyResult" class="legacy-success-card">
          <div class="success-title">旧库数据已无损导入当前账号，后台正在构建检索索引</div>
          <div class="preview-metrics">
            <span>导入文件 {{ legacyResult.stats.files }}</span>
            <span>笔记 {{ legacyResult.stats.notes }}</span>
            <span>链接 {{ legacyResult.stats.links }}</span>
            <span>Wiki 页面 {{ legacyResult.stats.wikiPages }}</span>
            <span>Wiki 双链 {{ legacyResult.stats.wikiLinks }}</span>
            <span>入队索引 {{ legacyResult.enqueued }} 项</span>
          </div>
          <div class="success-nav">
            <button type="button" class="pick-btn" @click="closeModal">完成并查看资料库</button>
            <button
              v-if="legacyResult.stats.wikiPages > 0"
              type="button"
              class="pick-btn is-primary"
              @click="$emit('go-wiki')"
            >
              前往 Wiki 查看
            </button>
          </div>
        </div>
      </div>

      <footer v-if="activeTab === 'batch'" class="modal-foot">
        <button type="button" class="pick-btn" :disabled="uploadingBatch" @click="closeModal">关闭</button>
        <button
          type="button"
          class="primary-go-btn"
          :disabled="uploadingBatch || pendingCount === 0"
          @click="startBatchUpload"
        >
          {{ uploadingBatch ? `正在上传 (${doneCount}/${eligibleCount})...` : `开始批量导入 (${pendingCount} 个文件)` }}
        </button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  detectLegacyImport,
  importLegacyBundle,
  importLocalLegacy,
  uploadFile,
  type LegacyDetectResult,
  type LegacyImportResult,
} from '../api/client';
import { useAuthStore } from '../stores/auth';

const ALLOWED_EXTS = new Set([
  'txt',
  'pdf',
  'md',
  'json',
  'sh',
  'markdown',
  'docx',
  'pptx',
  'csv',
  'html',
  'htm',
  'png',
  'jpg',
  'jpeg',
]);
const MAX_BYTES = 25 * 1024 * 1024;
const ACCEPT_ATTR = Array.from(ALLOWED_EXTS)
  .map((e) => `.${e}`)
  .join(',');

interface BatchItem {
  key: string;
  displayPath: string;
  file: File;
  status: 'pending' | 'uploading' | 'done' | 'skipped' | 'error';
  message: string;
}

const props = defineProps<{
  show: boolean;
  initialTab?: 'batch' | 'legacy';
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'imported'): void;
  (e: 'go-wiki'): void;
}>();

const auth = useAuthStore();

const activeTab = ref<'batch' | 'legacy'>('batch');
const isDragging = ref(false);
const batchTagsInput = ref('');
const queue = ref<BatchItem[]>([]);
const uploadingBatch = ref(false);

const fileInputRef = ref<HTMLInputElement | null>(null);
const dirInputRef = ref<HTMLInputElement | null>(null);

// Legacy tab state
const detectingLegacy = ref(false);
const detectInfo = ref<LegacyDetectResult | null>(null);
const importingLegacy = ref(false);
const legacyError = ref('');
const legacyResult = ref<LegacyImportResult | null>(null);

const selectedDbFile = ref<File | null>(null);
const selectedLegacyAttachments = ref<File[]>([]);
const dbFileRef = ref<HTMLInputElement | null>(null);
const legacyAttachRef = ref<HTMLInputElement | null>(null);

watch(
  () => props.show,
  (visible) => {
    if (visible) {
      activeTab.value = props.initialTab || 'batch';
      legacyError.value = '';
      if (activeTab.value === 'legacy') {
        void runDetectLegacy();
      }
    }
  }
);

const pendingCount = computed(() => queue.value.filter((i) => i.status === 'pending').length);
const doneCount = computed(() => queue.value.filter((i) => i.status === 'done').length);
const skippedOrErrorCount = computed(
  () => queue.value.filter((i) => i.status === 'skipped' || i.status === 'error').length
);
const eligibleCount = computed(
  () => queue.value.filter((i) => i.status !== 'skipped').length
);
const progressPercent = computed(() => {
  const total = eligibleCount.value;
  if (!total) return 0;
  const finished = queue.value.filter((i) => i.status === 'done' || i.status === 'error').length;
  return Math.min(100, Math.round((finished / total) * 100));
});

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function appendFilesToQueue(fileList: FileList | File[]) {
  const existingKeys = new Set(queue.value.map((i) => i.key));
  const additions: BatchItem[] = [];

  for (const file of Array.from(fileList)) {
    const relPath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
    // Ignore macOS/Windows system junk inside folders
    if (file.name.startsWith('.') || file.name === 'Thumbs.db') continue;

    const key = `${relPath}:${file.size}:${file.lastModified}`;
    if (existingKeys.has(key)) continue;

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXTS.has(ext)) {
      additions.push({
        key,
        displayPath: relPath,
        file,
        status: 'skipped',
        message: `跳过 (.${ext || '无扩展名'} 不支持)`,
      });
      continue;
    }

    if (file.size > MAX_BYTES) {
      additions.push({
        key,
        displayPath: relPath,
        file,
        status: 'skipped',
        message: '跳过 (超过 25MB)',
      });
      continue;
    }

    additions.push({
      key,
      displayPath: relPath,
      file,
      status: 'pending',
      message: '等待上传',
    });
  }

  queue.value = [...queue.value, ...additions];
}

function onPickFiles(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files && input.files.length > 0) {
    appendFilesToQueue(input.files);
  }
  input.value = '';
}

function onDropFiles(e: DragEvent) {
  isDragging.value = false;
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    appendFilesToQueue(e.dataTransfer.files);
  }
}

async function startBatchUpload() {
  if (uploadingBatch.value) return;
  const tags = batchTagsInput.value
    .split(/[,，\s]+/)
    .map((s) => s.trim().replace(/^#+/, ''))
    .filter(Boolean);

  uploadingBatch.value = true;
  let uploadedAny = false;
  try {
    for (const item of queue.value) {
      if (item.status !== 'pending') continue;
      item.status = 'uploading';
      item.message = '上传中...';
      try {
        await uploadFile(auth.token, item.file, tags.length > 0 ? tags : null);
        item.status = 'done';
        item.message = '已入队解析';
        uploadedAny = true;
      } catch (err: unknown) {
        item.status = 'error';
        item.message = err instanceof Error ? err.message : '上传失败';
      }
    }
    if (uploadedAny) {
      emit('imported');
    }
  } finally {
    uploadingBatch.value = false;
  }
}

function openLegacyTab() {
  activeTab.value = 'legacy';
  if (!detectInfo.value && !detectingLegacy.value) {
    void runDetectLegacy();
  }
}

async function runDetectLegacy() {
  detectingLegacy.value = true;
  legacyError.value = '';
  try {
    detectInfo.value = await detectLegacyImport(auth.token);
  } catch (err: unknown) {
    legacyError.value = err instanceof Error ? err.message : '检测本机旧库失败';
  } finally {
    detectingLegacy.value = false;
  }
}

async function runLocalLegacyImport() {
  importingLegacy.value = true;
  legacyError.value = '';
  legacyResult.value = null;
  try {
    legacyResult.value = await importLocalLegacy(auth.token, true);
    emit('imported');
  } catch (err: unknown) {
    legacyError.value = err instanceof Error ? err.message : '旧库导入失败';
  } finally {
    importingLegacy.value = false;
  }
}

function onSelectDbFile(e: Event) {
  const input = e.target as HTMLInputElement;
  selectedDbFile.value = input.files?.[0] || null;
}

function onSelectLegacyAttachments(e: Event) {
  const input = e.target as HTMLInputElement;
  selectedLegacyAttachments.value = input.files ? Array.from(input.files) : [];
}

async function runBundleImport() {
  if (!selectedDbFile.value) return;
  importingLegacy.value = true;
  legacyError.value = '';
  legacyResult.value = null;
  try {
    legacyResult.value = await importLegacyBundle(
      auth.token,
      selectedDbFile.value,
      selectedLegacyAttachments.value,
      true
    );
    emit('imported');
  } catch (err: unknown) {
    legacyError.value = err instanceof Error ? err.message : '上传备份导入失败';
  } finally {
    importingLegacy.value = false;
  }
}

function closeModal() {
  if (uploadingBatch.value || importingLegacy.value) return;
  emit('close');
}
</script>

<style scoped>
.import-backdrop {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(15, 23, 42, 0.44);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.import-modal {
  width: min(680px, 95vw);
  max-height: 88vh;
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 16px;
  box-shadow: 0 24px 54px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-head {
  padding: 18px 22px 12px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--border, #e5e5ea);
}

.modal-head h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 650;
  color: var(--text, #1d1d1f);
}

.modal-sub {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--text-secondary, #6e6e73);
}

.close-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  font-size: 20px;
  color: var(--text-secondary, #6e6e73);
  border-radius: 7px;
  cursor: pointer;
}

.close-btn:hover {
  background: rgba(0, 0, 0, 0.06);
}

.modal-tabs {
  display: flex;
  gap: 6px;
  padding: 10px 22px;
  background: #f5f5f7;
  border-bottom: 1px solid var(--border, #e5e5ea);
}

.tab-pill {
  border: none;
  background: transparent;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
}

.tab-pill.is-active {
  background: #ffffff;
  color: #0058b0;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.modal-body {
  padding: 18px 22px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.batch-dropzone {
  border: 1.5px dashed var(--border, #d1d1d6);
  border-radius: 12px;
  background: #fbfbfd;
  padding: 22px 18px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.batch-dropzone.is-dragover {
  border-color: var(--accent, #0071e3);
  background: rgba(0, 113, 227, 0.05);
}

.dz-heading {
  font-size: 14px;
  font-weight: 600;
  color: var(--text, #1d1d1f);
}

.dz-formats {
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
  max-width: 520px;
  line-height: 1.5;
}

.dz-btns {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}

.pick-btn {
  border: 1px solid var(--border, #d1d1d6);
  background: #ffffff;
  color: var(--text, #1d1d1f);
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 500;
  padding: 6px 13px;
  cursor: pointer;
}

.pick-btn:hover:not(:disabled) {
  background: #f5f5f7;
}

.pick-btn.is-primary {
  border-color: rgba(0, 113, 227, 0.35);
  background: rgba(0, 113, 227, 0.08);
  color: #0058b0;
  font-weight: 600;
}

.pick-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.batch-tags-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-secondary, #515154);
}

.batch-tags-input {
  flex: 1;
  border: 1px solid var(--border, #d1d1d6);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 12.5px;
  outline: none;
}

.batch-tags-input:focus {
  border-color: var(--accent, #0071e3);
}

.queue-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.queue-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-secondary, #6e6e73);
}

.clear-list-btn {
  border: none;
  background: transparent;
  color: var(--accent, #0071e3);
  font-size: 12px;
  cursor: pointer;
}

.progress-track {
  height: 5px;
  background: #ececf0;
  border-radius: 999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent, #0071e3);
  transition: width 0.2s ease;
}

.queue-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 210px;
  overflow-y: auto;
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 10px;
}

.queue-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid #f2f2f7;
  font-size: 12.5px;
}

.queue-row:last-child {
  border-bottom: none;
}

.q-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.q-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text, #1d1d1f);
}

.q-size {
  font-size: 11px;
  color: var(--text-tertiary, #86868b);
  flex-shrink: 0;
}

.q-status {
  font-size: 11.5px;
  flex-shrink: 0;
}

.q-status.is-pending {
  color: var(--text-tertiary, #86868b);
}

.q-status.is-uploading {
  color: #0058b0;
  font-weight: 500;
}

.q-status.is-done {
  color: #15803d;
  font-weight: 500;
}

.q-status.is-skipped {
  color: #b45309;
}

.q-status.is-error {
  color: #b91c1c;
}

.modal-foot {
  padding: 12px 22px;
  border-top: 1px solid var(--border, #e5e5ea);
  background: #fbfbfd;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.primary-go-btn {
  border: none;
  border-radius: 8px;
  background: var(--accent, #0071e3);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  padding: 7px 16px;
  cursor: pointer;
}

.primary-go-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.inline-error {
  padding: 9px 12px;
  border-radius: 9px;
  background: #fff5f5;
  border: 1px solid rgba(255, 59, 48, 0.25);
  color: #b91c1c;
  font-size: 12.5px;
}

.legacy-card {
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 12px;
  padding: 14px 16px;
  background: #fbfbfd;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.legacy-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.legacy-card-head h4 {
  margin: 0 0 3px;
  font-size: 14px;
  font-weight: 650;
  color: var(--text, #1d1d1f);
}

.legacy-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary, #6e6e73);
}

.refresh-detect-btn {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  border-radius: 7px;
  font-size: 11.5px;
  padding: 4px 10px;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
  flex-shrink: 0;
}

.detect-muted {
  font-size: 12.5px;
  color: var(--text-secondary, #6e6e73);
}

.detect-found {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detect-path {
  font-size: 12px;
  color: var(--text-secondary, #515154);
}

.preview-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preview-metrics span {
  font-size: 12px;
  padding: 3px 9px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid var(--border, #e5e5ea);
  color: var(--text, #1d1d1f);
}

.preview-metrics .metric-ok {
  border-color: rgba(21, 128, 61, 0.25);
  color: #15803d;
}

.preview-metrics .metric-warn {
  border-color: rgba(180, 83, 9, 0.25);
  color: #b45309;
}

.legacy-actions {
  display: flex;
  justify-content: flex-end;
}

.bundle-pickers {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.picker-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12.5px;
}

.picker-label {
  min-width: 145px;
  color: var(--text-secondary, #515154);
  font-weight: 500;
}

.picker-val {
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
}

.legacy-success-card {
  border: 1px solid rgba(21, 128, 61, 0.3);
  background: #f0fdf4;
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.success-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #166534;
}

.success-nav {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>

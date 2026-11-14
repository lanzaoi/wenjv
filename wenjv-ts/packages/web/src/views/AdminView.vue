<template>
  <div class="admin">
    <header class="head">
      <div class="head-left">
        <div class="head-icon"><Icon name="sliders" :size="20" /></div>
        <div>
          <h1>系统管理与观测</h1>
          <p class="muted sub">索引规模、RAG 检索指标、模型运行状态与任务队列</p>
        </div>
      </div>
      <div class="head-actions">
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="reloadAll">
          <Icon name="refresh" :size="15" :spin="loading" />
          <span>{{ loading ? '刷新中…' : '刷新数据' }}</span>
        </button>
      </div>
    </header>

    <div v-if="error" class="err-banner">
      <Icon name="x" :size="15" />
      <span>{{ error }}</span>
    </div>
    <div v-if="notice" class="info-banner">
      <Icon name="check" :size="15" />
      <span>{{ notice }}</span>
    </div>

    <section class="card-grid" v-if="stats">
      <div class="stat-card card">
        <span class="stat-label">OCR Sidecar</span>
        <strong class="stat-value">
          <span class="dot" :class="stats.runtime?.ocr?.ok ? 'ok' : 'warn'" />
          {{ stats.runtime?.ocr?.ok ? '在线' : stats.runtime?.ocr?.status || '未连接' }}
        </strong>
        <span class="stat-sub">PP-OCRv5 Mobile + Pix2Text</span>
      </div>
      <div class="stat-card card">
        <span class="stat-label">SigLIP2 视觉编码</span>
        <strong class="stat-value">
          <span class="dot" :class="stats.runtime?.siglip2_vision ? 'ok' : 'warn'" />
          {{ stats.runtime?.siglip2_vision ? '已就绪' : '不可用' }}
        </strong>
        <span class="stat-sub">768 维跨模态向量索引</span>
      </div>
      <div class="stat-card card">
        <span class="stat-label">知识库规模</span>
        <strong class="stat-value">{{ stats.counts.resources }} 资料 / {{ stats.counts.wiki_pages }} Wiki</strong>
        <span class="stat-sub">
          文件 {{ stats.counts.files }} · 笔记 {{ stats.counts.notes }} · 链接 {{ stats.counts.links }} · 分块 {{ stats.counts.chunks }} · 资产 {{ stats.counts.assets }}
        </span>
      </div>
      <div class="stat-card card">
        <span class="stat-label">查询量与延迟</span>
        <strong class="stat-value">{{ stats.total_queries }} 次 ({{ stats.avg_latency_ms }} ms)</strong>
        <span class="stat-sub">最近 24 小时 {{ stats.last_24h_queries }} 次 · 用户 {{ stats.counts.users }}</span>
      </div>
    </section>

    <section class="panel card" v-if="stats">
      <div class="panel-head">
        <h2>检索通道指标</h2>
      </div>
      <div class="kpi-row">
        <div class="kpi"><span class="kpi-k">向量命中率</span><strong>{{ pct(stats.v_hit_rate) }}</strong></div>
        <div class="kpi"><span class="kpi-k">FTS5 命中率</span><strong>{{ pct(stats.fts5_hit_rate) }}</strong></div>
        <div class="kpi"><span class="kpi-k">结构化命中率</span><strong>{{ pct(stats.s_hit_rate) }}</strong></div>
        <div class="kpi"><span class="kpi-k">缓存命中率</span><strong>{{ pct(stats.cache_hit_rate) }}</strong></div>
        <div class="kpi"><span class="kpi-k">异常率</span><strong>{{ pct(stats.error_rate) }}</strong></div>
      </div>
    </section>

    <div class="two-col">
      <section class="panel card">
        <div class="panel-head">
          <h2>API 调用计数</h2>
          <button
            class="btn btn-secondary btn-sm"
            type="button"
            :disabled="resetting"
            @click="onResetCounts"
          >
            {{ resetting ? '清零中…' : '清零计数' }}
          </button>
        </div>
        <table class="tbl">
          <thead>
            <tr>
              <th>Provider</th>
              <th>调用类型</th>
              <th>累计次数</th>
              <th>上次清零</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in stats?.api_calls || []" :key="idx">
              <td>{{ item.provider }}</td>
              <td>{{ item.call_type }}</td>
              <td class="num">{{ item.call_count }}</td>
              <td class="muted">{{ item.last_reset || '-' }}</td>
            </tr>
            <tr v-if="!stats?.api_calls?.length">
              <td colspan="4" class="empty-cell">暂无 API 调用记录</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="panel card">
        <div class="panel-head">
          <h2>最近入库任务</h2>
          <span class="muted" style="font-size: 12px" v-if="stats?.jobs">
            待处理 {{ stats.jobs['pending'] || 0 }} · 进行中 {{ stats.jobs['running'] || 0 }} · 完成 {{ stats.jobs['finished'] || 0 }} · 失败 {{ stats.jobs['failed'] || 0 }}
          </span>
        </div>
        <table class="tbl">
          <thead>
            <tr>
              <th>ID</th>
              <th>对象</th>
              <th>状态</th>
              <th>尝试</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs.slice(0, 15)" :key="job.id">
              <td class="num">#{{ job.id }}</td>
              <td>{{ job.entity_type }} #{{ job.entity_id }}</td>
              <td><StatusDot :status="job.status" /></td>
              <td class="num">{{ job.attempts }}/{{ job.max_attempts }}</td>
              <td>
                <button
                  v-if="job.status === 'failed' || job.status === 'cancelled'"
                  class="btn btn-secondary btn-xs"
                  type="button"
                  @click="onRetryJob(job.id)"
                >
                  重试
                </button>
                <span v-else class="muted" style="font-size: 12px">{{ job.last_error ? job.last_error.slice(0, 32) : '-' }}</span>
              </td>
            </tr>
            <tr v-if="jobs.length === 0">
              <td colspan="5" class="empty-cell">暂无任务记录</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <section class="panel card">
      <div class="panel-head">
        <h2>最近检索日志 ({{ filteredLogs.length }})</h2>
        <input
          v-model="logFilter"
          type="search"
          class="filter-input"
          placeholder="筛选查询词或错误…"
        />
      </div>
      <table class="tbl">
        <thead>
          <tr>
            <th>时间</th>
            <th>查询语句</th>
            <th>延迟</th>
            <th>通道命中 (V/F/S)</th>
            <th>缓存</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in filteredLogs" :key="log.id">
            <td class="muted">{{ log.timestamp }}</td>
            <td class="q-cell" :title="log.query">{{ log.query }}</td>
            <td class="num">{{ Number(log.latency_ms || 0).toFixed(1) }} ms</td>
            <td class="num">V:{{ log.v_hits }} / F:{{ log.fts5_hits }} / S:{{ log.s_hits }} ({{ log.total_hits }})</td>
            <td>{{ log.cache_hit ? '命中' : '-' }}</td>
            <td :class="log.error ? 'err-text' : 'muted'">{{ log.error || '-' }}</td>
          </tr>
          <tr v-if="filteredLogs.length === 0">
            <td colspan="6" class="empty-cell">暂无查询日志</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated } from 'vue';
import {
  getAdminStats,
  getAdminLogs,
  resetAdminCounts,
  listJobs,
  retryJob,
  type AdminStats,
  type AdminQueryLog,
  type IngestionJobItem,
} from '../api/client.js';
import { useAuthStore } from '../stores/auth.js';
import Icon from '../components/Icon.vue';
import StatusDot from '../components/StatusDot.vue';

defineOptions({ name: 'AdminView' });

const auth = useAuthStore();
const loading = ref(false);
const resetting = ref(false);
const error = ref('');
const notice = ref('');
const stats = ref<AdminStats | null>(null);
const logs = ref<AdminQueryLog[]>([]);
const jobs = ref<IngestionJobItem[]>([]);
const logFilter = ref('');

const filteredLogs = computed(() => {
  const q = logFilter.value.trim().toLowerCase();
  if (!q) return logs.value;
  return logs.value.filter(
    (l) =>
      (l.query || '').toLowerCase().includes(q) ||
      (l.error || '').toLowerCase().includes(q)
  );
});

function pct(val: number): string {
  return `${(Number(val || 0) * 100).toFixed(1)}%`;
}

async function reloadAll(): Promise<void> {
  if (!auth.token) return;
  loading.value = true;
  error.value = '';
  try {
    const [s, l, j] = await Promise.all([
      getAdminStats(auth.token),
      getAdminLogs(auth.token, 50),
      listJobs(auth.token),
    ]);
    stats.value = s;
    logs.value = l.logs || [];
    jobs.value = j || [];
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

async function onResetCounts(): Promise<void> {
  if (!auth.token || resetting.value) return;
  resetting.value = true;
  notice.value = '';
  error.value = '';
  try {
    const res = await resetAdminCounts(auth.token);
    notice.value = res.message || 'API 计数已清零';
    await reloadAll();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    resetting.value = false;
  }
}

async function onRetryJob(jobId: number): Promise<void> {
  if (!auth.token) return;
  notice.value = '';
  error.value = '';
  try {
    await retryJob(auth.token, jobId);
    notice.value = `任务 #${jobId} 已重新入队`;
    await reloadAll();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}

onMounted(() => {
  void reloadAll();
});

onActivated(() => {
  void reloadAll();
});
</script>

<style scoped>
.admin {
  max-width: 1120px;
  margin: 0 auto;
  padding: 20px 18px 40px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.head-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  display: grid;
  place-items: center;
  color: var(--accent);
}
.head h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}
.sub {
  margin: 2px 0 0;
  font-size: 12.5px;
}
.err-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-radius: 9px;
  background: #fff5f5;
  border: 1px solid rgba(255, 59, 48, 0.25);
  color: #b91c1c;
  font-size: 13px;
}
.info-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-radius: 9px;
  background: #f0fdf4;
  border: 1px solid rgba(22, 163, 74, 0.25);
  color: #15803d;
  font-size: 13px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.stat-card {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
}
.stat-value {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 16px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.stat-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex-shrink: 0;
}
.dot.ok {
  background: #16a34a;
}
.dot.warn {
  background: #d97706;
}
.panel {
  padding: 14px 16px;
  overflow-x: auto;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.panel-head h2 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 650;
}
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
}
.kpi {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.kpi-k {
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.kpi strong {
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}
.two-col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
}
.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.tbl th,
.tbl td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.tbl th {
  color: var(--text-tertiary);
  font-weight: 550;
  font-size: 11.5px;
}
.num {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.q-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty-cell {
  text-align: center;
  color: var(--text-tertiary);
  padding: 18px 8px;
}
.err-text {
  color: #b91c1c;
}
.filter-input {
  width: 210px;
  padding: 5px 10px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 12.5px;
  outline: none;
}
.filter-input:focus {
  border-color: var(--accent);
}
.btn-xs {
  padding: 2px 8px;
  font-size: 11.5px;
}
</style>

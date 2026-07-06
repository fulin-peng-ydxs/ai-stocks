<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppPagination from '@/components/AppPagination.vue'
import HelpTip from '@/components/HelpTip.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { getAuditDetail, getAuditSummary, listAuditLogs, type AuditLog, type AuditQuery, type AuditSummary } from '@/api/audit'
import { getPublicDictItems } from '@/api/dict'
import { listTenants } from '@/api/tenant'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useTableSort } from '@/composables/useTableSort'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'

const pageKey = 'audit-log'
const AUTO_REFRESH_MS = 30_000

interface OptionItem {
  value: string
  label: string
}

const FALLBACK_EVENT_CATEGORIES: OptionItem[] = [
  { value: 'api', label: '接口' },
  { value: 'task', label: '任务' },
  { value: 'security', label: '安全' },
  { value: 'rbac', label: '权限' },
  { value: 'config', label: '配置' },
  { value: 'dict', label: '字典' },
]
const FALLBACK_RESULTS: OptionItem[] = [
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'denied', label: '拒绝' },
]
const STATUS_OPTIONS: OptionItem[] = [
  { value: 'completed', label: '完成' },
  { value: 'running', label: '处理中' },
  { value: 'failed', label: '异常' },
  { value: 'blocked', label: '已阻断' },
  { value: 'skipped', label: '已跳过' },
]

const auth = useAuthStore()
const baseLayout = getPageLayout(pageKey)
const {
  effective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
} = useRemoteLayoutConfig(baseLayout)
const drawerConfig = {
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
}

const { settings, isDirty: bizDirty, reset: resetBiz } = usePageSettings(pageKey, {
  autoRefreshEnabled: false,
  filters: {
    start_time: '',
    end_time: '',
    event_category: [] as string[],
    result: [] as string[],
    status: [] as string[],
    resource_code: '',
    actor_keyword: '',
    target_keyword: '',
    tenant_id: [] as string[],
  },
})
const settingsOpen = ref(false)
const filters = settings.filters
const dateRange = ref<[string, string] | null>(
  filters.start_time && filters.end_time ? [filters.start_time, filters.end_time] : null,
)

const rows = ref<AuditLog[]>([])
const total = ref(0)
const page = ref(1)
const tableLoading = ref(false)
const summaryLoading = ref(false)
const loadError = ref(false)
const permissionError = ref(false)
const summaryError = ref(false)
const summary = ref<AuditSummary | null>(null)
const retentionHint = computed(() => {
  const days = summary.value?.retention_days
  return typeof days === 'number' && Number.isFinite(days)
    ? `默认最近 ${days} 天`
    : '默认窗口按系统设置'
})
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref(false)
const activeDetail = ref<AuditLog | null>(null)
const eventOptions = ref<OptionItem[]>(FALLBACK_EVENT_CATEGORIES)
const resultOptions = ref<OptionItem[]>(FALLBACK_RESULTS)
const statusOptions = ref<OptionItem[]>(STATUS_OPTIONS)
const tenantOptions = ref<OptionItem[]>([])

const pageSize = computed(() => {
  const raw = componentValueOf('auditTable', 'pageSize')
  return typeof raw === 'number' && Number.isFinite(raw) ? Math.max(10, Math.min(200, raw)) : 50
})
const AUDIT_SORT_FIELDS = ['event_time', 'event_category', 'result', 'status', 'duration_ms'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof AUDIT_SORT_FIELDS)[number]>({
  slotId: 'auditTable',
  defaultSort: 'event_time:desc',
  componentValueOf,
  setComponentKnob,
  allowedFields: AUDIT_SORT_FIELDS,
  onChanged: () => {
    page.value = 1
    void loadAll()
  },
})
const hiddenColumns = computed<string[]>(() => {
  const raw = componentValueOf('auditTable', 'hiddenColumns')
  return Array.isArray(raw) ? raw.map(String) : []
})
const drawerDirty = computed(() => layoutDirty.value || bizDirty.value)
const canViewAudit = computed(() => auth.isSystem || auth.permissions.includes('audit:view') || auth.menusStatus !== 'ready')
let refreshTimer: number | undefined
let listRequestSeq = 0
let summaryRequestSeq = 0
let listLoadingSeq = 0
let summaryLoadingSeq = 0

function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}

function tagType(value: string | null | undefined): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'success' || value === 'completed') return 'success'
  if (value === 'failed' || value === 'error' || value === 'denied') return 'danger'
  if (value === 'running' || value === 'processing') return 'warning'
  return 'info'
}

function labelOf(options: OptionItem[], value: string | null | undefined): string {
  if (!value) return '-'
  return options.find((item) => item.value === value)?.label ?? value
}

function eventLabel(row: AuditLog): string {
  return labelOf(eventOptions.value, row.event_category)
}

function resultLabel(value: string | null | undefined): string {
  return labelOf(resultOptions.value, value)
}

function statusLabel(value: string | null | undefined): string {
  return labelOf(statusOptions.value, value)
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+/, '').replace(/\+.*$/, '').slice(0, 19)
}

function formatDuration(value: number | null | undefined): string {
  if (value == null) return '-'
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${value}ms`
}

function targetText(row: AuditLog): string {
  return row.target_label || row.target_id || row.target_type || '-'
}

function targetDescription(row: AuditLog): string {
  return row.target_description || row.resource_name || row.resource_code || row.path || ''
}

function actorText(row: AuditLog): string {
  return row.actor_account || row.actor_user_id || 'system'
}

function compactFilter(value: string | null | undefined): string | undefined {
  const text = String(value ?? '').trim()
  return text ? text : undefined
}

function compactList(value: string[] | string | null | undefined): string[] | undefined {
  const list = Array.isArray(value) ? value : value ? [value] : []
  const out = list.map((item) => String(item).trim()).filter(Boolean)
  return out.length ? out : undefined
}

function buildQuery(): AuditQuery {
  return {
    page: page.value,
    page_size: pageSize.value,
    start_time: compactFilter(filters.start_time),
    end_time: compactFilter(filters.end_time),
    event_category: compactList(filters.event_category),
    result: compactList(filters.result),
    status: compactList(filters.status),
    resource_code: compactFilter(filters.resource_code),
    actor_keyword: compactFilter(filters.actor_keyword),
    target_keyword: compactFilter(filters.target_keyword),
    tenant_id: auth.isSystem ? compactList(filters.tenant_id) : undefined,
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
  }
}

function errorStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}

async function loadSummary(silent = false) {
  const seq = ++summaryRequestSeq
  if (!silent) {
    summaryLoading.value = true
    summaryLoadingSeq = seq
  }
  summaryError.value = false
  const { page: _page, page_size: _size, sort_by: _sortBy, sort_order: _sortOrder, ...query } = buildQuery()
  try {
    const data = await getAuditSummary(query)
    if (seq !== summaryRequestSeq) return
    summary.value = data
  } catch {
    if (seq === summaryRequestSeq) summaryError.value = true
  } finally {
    if (!silent && summaryLoadingSeq === seq) summaryLoading.value = false
  }
}

async function loadList(silent = false) {
  if (!canViewAudit.value) {
    permissionError.value = true
    return
  }
  const seq = ++listRequestSeq
  if (!silent) {
    tableLoading.value = true
    listLoadingSeq = seq
  }
  loadError.value = false
  permissionError.value = false
  try {
    const data = await listAuditLogs(buildQuery())
    if (seq !== listRequestSeq) return
    rows.value = data.list
    total.value = data.total
    if (data.list.length === 0 && page.value > 1) {
      page.value = Math.max(1, Math.ceil(data.total / pageSize.value))
      if (page.value > 1) await loadList(silent)
    }
  } catch (error) {
    if (seq === listRequestSeq) {
      if (errorStatus(error) === 403) permissionError.value = true
      else if (!silent) loadError.value = true
    }
  } finally {
    if (!silent && listLoadingSeq === seq) tableLoading.value = false
  }
}

async function loadAll(silent = false) {
  if (!canViewAudit.value) {
    permissionError.value = true
    return
  }
  await Promise.all([loadList(silent), loadSummary(silent)])
}

function applyDateRange() {
  filters.start_time = dateRange.value?.[0] ?? ''
  filters.end_time = dateRange.value?.[1] ?? ''
}

async function search() {
  applyDateRange()
  page.value = 1
  await loadAll()
}

function filterChanged() {
  void search()
}

function pageChanged(value: number) {
  page.value = value
  void loadAll()
}

function pageSizeChanged(value: number) {
  if (value === pageSize.value) return
  setComponentKnob('auditTable', 'pageSize', value)
  page.value = 1
}

async function refresh(silent = false) {
  await loadAll(silent)
  if (!silent && !loadError.value && !permissionError.value) ElMessage.success('已刷新')
}

async function resetFilters() {
  dateRange.value = null
  Object.assign(filters, {
    start_time: '',
    end_time: '',
    event_category: [],
    result: [],
    status: [],
    resource_code: '',
    actor_keyword: '',
    target_keyword: '',
    tenant_id: [],
  })
  page.value = 1
  await loadAll()
}

async function openDetail(row: AuditLog) {
  activeDetail.value = row
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = false
  try {
    activeDetail.value = await getAuditDetail(row.id)
  } catch {
    detailError.value = true
  } finally {
    detailLoading.value = false
  }
}

async function loadDictOptions() {
  const load = async (typeCode: string, fallback: OptionItem[]) => {
    try {
      const data = await getPublicDictItems(typeCode)
      return data.items.length
        ? data.items.map((item) => ({ value: item.code, label: item.label }))
        : fallback
    } catch {
      return fallback
    }
  }
  const [events, results, statuses] = await Promise.all([
    load('audit_event_type', FALLBACK_EVENT_CATEGORIES),
    load('audit_result', FALLBACK_RESULTS),
    load('audit_status', STATUS_OPTIONS),
  ])
  eventOptions.value = events
  resultOptions.value = results
  statusOptions.value = statuses
}

async function loadTenantOptions() {
  if (!auth.isSystem) {
    tenantOptions.value = []
    return
  }
  try {
    const data = await listTenants({ page: 1, size: 200 })
    tenantOptions.value = data.items.map((tenant) => ({
      value: tenant.id,
      label: tenant.name,
    }))
  } catch {
    tenantOptions.value = []
  }
}

function startTimer() {
  stopTimer()
  if (!settings.autoRefreshEnabled) return
  refreshTimer = window.setInterval(() => {
    void refresh(true)
  }, AUTO_REFRESH_MS)
}

function stopTimer() {
  if (refreshTimer != null) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
}

watch(() => settings.autoRefreshEnabled, startTimer)
watch(pageSize, () => {
  page.value = 1
  void loadAll(true)
})

onMounted(async () => {
  await Promise.all([loadDictOptions(), loadTenantOptions()])
  await loadAll()
  startTimer()
})

onBeforeUnmount(stopTimer)
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="audit-head">
        <div class="audit-title">
          <h2>审计日志</h2>
          <HelpTip title="审计日志说明" :width="420">
            记录接口、任务、安全、权限、配置和字典事件。系统管理员查看全局，租户管理员仅查看本租户事件。
          </HelpTip>
        </div>
        <div class="audit-actions">
          <el-switch v-model="settings.autoRefreshEnabled" size="small" active-text="自动刷新" />
          <el-button :loading="tableLoading || summaryLoading" @click="refresh(false)">刷新</el-button>
          <el-tooltip content="导出能力不在本阶段范围" placement="bottom">
            <span><el-button disabled>导出</el-button></span>
          </el-tooltip>
          <PageSettingsTrigger :dirty="drawerDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </template>

    <template #summary>
      <div class="audit-summary" v-loading="summaryLoading">
        <div class="metric">
          <span>范围事件</span>
          <b>{{ summary?.total ?? 0 }}</b>
          <em>{{ retentionHint }}</em>
        </div>
        <div class="metric">
          <span>失败 / 拒绝</span>
          <b class="warn">{{ summary?.failed ?? 0 }}</b>
          <em>{{ summaryError ? '摘要读取失败' : '含失败、拒绝和异常' }}</em>
        </div>
        <div class="metric">
          <span>安全事件</span>
          <b class="danger">{{ summary?.by_category?.security ?? 0 }}</b>
          <em>登录失败、账号锁定等</em>
        </div>
      </div>
    </template>

    <template #filters>
      <div class="audit-filters">
        <el-date-picker
          v-model="dateRange"
          type="datetimerange"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          range-separator="至"
          class="audit-date"
        />
        <AppFilterSelect
          v-model="filters.event_category"
          :options="eventOptions"
          placeholder="事件类型"
          class="w140"
          @change="filterChanged"
        />
        <AppFilterSelect
          v-model="filters.result"
          :options="resultOptions"
          placeholder="结果"
          class="w120"
          @change="filterChanged"
        />
        <AppFilterSelect
          v-model="filters.status"
          :options="statusOptions"
          placeholder="状态"
          class="w120"
          @change="filterChanged"
        />
        <el-input v-model="filters.resource_code" clearable placeholder="资源码" class="w160" />
        <el-input v-model="filters.actor_keyword" clearable placeholder="处理人" class="w140" />
        <el-input v-model="filters.target_keyword" clearable placeholder="目标对象" class="w160" />
        <AppFilterSelect
          v-if="auth.isSystem"
          v-model="filters.tenant_id"
          :options="tenantOptions"
          placeholder="租户"
          class="w180"
          @change="filterChanged"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </template>

    <template #auditTable>
      <el-result v-if="permissionError" icon="warning" title="无权限查看审计日志" sub-title="请联系系统管理员调整审计查看权限" class="audit-state" />
      <el-result v-else-if="loadError" icon="warning" title="审计服务暂不可用" sub-title="请稍后重试，已发生事件仍会在服务端继续写入" class="audit-state">
        <template #extra><el-button type="primary" @click="loadAll()">重试</el-button></template>
      </el-result>
      <div v-else class="audit-table-wrap">
        <el-table
          :data="rows"
          v-loading="tableLoading"
          height="100%"
          row-key="id"
          stripe
          class="audit-table"
          :default-sort="elementDefaultSort"
          @sort-change="onSortChange"
          @row-click="openDetail"
        >
          <el-table-column v-if="colVisible('event_time')" label="时间" prop="event_time" width="168" sortable="custom">
            <template #default="{ row }">{{ formatTime(row.event_time) }}</template>
          </el-table-column>
          <el-table-column v-if="colVisible('actor')" label="处理人" width="132" show-overflow-tooltip>
            <template #default="{ row }">{{ actorText(row) }}</template>
          </el-table-column>
          <el-table-column v-if="colVisible('event_category')" label="事件类型" prop="event_category" width="100" sortable="custom">
            <template #default="{ row }">
              <el-tag :type="row.event_category === 'security' ? 'danger' : row.event_category === 'task' ? 'info' : 'success'" effect="plain">
                {{ eventLabel(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="colVisible('resource_code')" label="资源码" min-width="170" show-overflow-tooltip>
            <template #default="{ row }"><span class="mono">{{ row.resource_code || '-' }}</span></template>
          </el-table-column>
          <el-table-column v-if="colVisible('target')" label="目标对象" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="target-cell">
                <b>{{ targetText(row) }}</b>
                <em v-if="targetDescription(row)">{{ targetDescription(row) }}</em>
              </span>
            </template>
          </el-table-column>
          <el-table-column v-if="colVisible('result')" label="结果" prop="result" width="86" sortable="custom">
            <template #default="{ row }"><el-tag :type="tagType(row.result)" effect="plain">{{ resultLabel(row.result) }}</el-tag></template>
          </el-table-column>
          <el-table-column v-if="colVisible('status')" label="状态" prop="status" width="96" sortable="custom">
            <template #default="{ row }"><el-tag :type="tagType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag></template>
          </el-table-column>
          <el-table-column v-if="colVisible('ip')" label="IP" prop="ip" width="132" show-overflow-tooltip />
          <el-table-column v-if="colVisible('duration_ms')" label="耗时" prop="duration_ms" width="84" sortable="custom">
            <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
          </el-table-column>
          <el-table-column v-if="colVisible('error_summary')" label="错误摘要" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.error_summary || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="78" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty class="app-empty" description="暂无审计记录">
              <el-button @click="resetFilters">重置筛选</el-button>
            </el-empty>
          </template>
        </el-table>
        <div class="audit-pager">
          <AppPagination
            :current-page="page"
            :page-size="pageSize"
            :total="total"
            @current-change="pageChanged"
            @size-change="pageSizeChanged"
          />
        </div>
      </div>
    </template>

    <template #overlays>
      <el-drawer v-model="detailOpen" title="审计详情" size="520px" class="audit-detail-drawer">
        <div v-loading="detailLoading" class="detail-body">
          <el-result v-if="detailError" icon="warning" title="详情读取失败" sub-title="请关闭后重试" />
          <template v-else-if="activeDetail">
            <section class="detail-hero">
              <div class="detail-title">
                <b>{{ targetText(activeDetail) }}</b>
                <em v-if="targetDescription(activeDetail)">{{ targetDescription(activeDetail) }}</em>
                <span>{{ formatTime(activeDetail.event_time) }} · {{ actorText(activeDetail) }}</span>
              </div>
              <div class="detail-tags">
                <el-tag effect="plain">{{ eventLabel(activeDetail) }}</el-tag>
                <el-tag :type="tagType(activeDetail.result)" effect="plain">{{ resultLabel(activeDetail.result) }}</el-tag>
                <el-tag :type="tagType(activeDetail.status)" effect="plain">{{ statusLabel(activeDetail.status) }}</el-tag>
              </div>
            </section>

            <div class="detail-grid">
              <section class="detail-card">
                <h4>执行信息</h4>
                <div class="info-row"><span>处理人</span><b>{{ actorText(activeDetail) }}</b></div>
                <div class="info-row"><span>租户</span><b>{{ activeDetail.tenant_id || '-' }}</b></div>
                <div class="info-row"><span>来源 IP</span><b>{{ activeDetail.ip || '-' }}</b></div>
                <div class="info-row"><span>耗时</span><b>{{ formatDuration(activeDetail.duration_ms) }}</b></div>
              </section>
              <section class="detail-card">
                <h4>资源信息</h4>
                <div class="info-row"><span>资源码</span><b class="mono">{{ activeDetail.resource_code || '-' }}</b></div>
                <div class="info-row"><span>事件类型</span><b>{{ activeDetail.event_type }}</b></div>
                <div class="info-row"><span>中文说明</span><b>{{ targetDescription(activeDetail) || '-' }}</b></div>
                <div class="info-row"><span>请求方法</span><b>{{ activeDetail.method || '-' }}</b></div>
                <div class="info-row"><span>请求路径</span><b>{{ activeDetail.path || '-' }}</b></div>
              </section>
            </div>

            <section class="detail-section">
              <h4>错误摘要</h4>
              <p :class="{ muted: !activeDetail.error_summary }">{{ activeDetail.error_summary || '无错误摘要' }}</p>
            </section>

            <section class="detail-section">
              <h4>事件上下文</h4>
              <pre class="json">{{ JSON.stringify(activeDetail.context || {}, null, 2) }}</pre>
            </section>
          </template>
        </div>
        <template #footer>
          <el-button @click="detailOpen = false">关闭</el-button>
        </template>
      </el-drawer>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="审计日志"
        :dirty="drawerDirty"
        :page-key="pageKey"
        :config="drawerConfig"
        @reset="resetBiz(); resetLayout()"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.audit-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.audit-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.audit-title h2 {
  margin: 0;
  font-size: 20px;
}
.audit-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.audit-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 12px;
}
.metric {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
  padding: 11px 12px;
  min-width: 0;
}
.metric span,
.metric em {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-style: normal;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.metric b {
  display: block;
  margin-top: 4px;
  color: var(--el-text-color-primary);
  font-size: 20px;
  line-height: 1.25;
}
.metric b.warn { color: var(--el-color-warning); }
.metric b.danger { color: var(--el-color-danger); }
.audit-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.audit-date {
  width: 330px;
}
.w110 { width: 110px; }
.w120 { width: 120px; }
.w140 { width: 140px; }
.w160 { width: 160px; }
.w180 { width: 180px; }
.audit-state {
  height: 100%;
}
.audit-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  background: var(--el-bg-color-overlay);
}
.audit-table {
  flex: 1 1 auto;
  min-height: 0;
}
.audit-table :deep(.el-table__row) {
  cursor: pointer;
}
.audit-pager {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  padding: 10px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}
.target-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.target-cell b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.target-cell em,
.detail-title em {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-style: normal;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-body {
  min-height: 320px;
}
.detail-hero,
.detail-card,
.detail-section {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
  padding: 12px;
  margin-bottom: 12px;
}
.detail-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.detail-title {
  min-width: 0;
}
.detail-title b {
  display: block;
  overflow-wrap: anywhere;
  font-size: 16px;
}
.detail-title em {
  display: block;
  margin-top: 3px;
  white-space: normal;
}
.detail-title span {
  display: block;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.detail-card h4,
.detail-section h4 {
  margin: 0 0 10px;
  font-size: 13px;
}
.info-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
}
.info-row:first-of-type {
  border-top: none;
}
.info-row span {
  flex: none;
  color: var(--el-text-color-secondary);
}
.info-row b {
  min-width: 0;
  overflow-wrap: anywhere;
  text-align: right;
  font-weight: 500;
}
.detail-section p {
  margin: 0;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.7;
}
.detail-section p.muted {
  color: var(--el-text-color-secondary);
}
.json {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-light);
  padding: 10px;
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}
@media (max-width: 980px) {
  .audit-summary {
    grid-template-columns: repeat(2, minmax(150px, 1fr));
  }
  .audit-date {
    width: 100%;
  }
  .audit-head {
    flex-direction: column;
  }
  .audit-actions {
    justify-content: flex-start;
  }
}
@media (max-width: 720px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>

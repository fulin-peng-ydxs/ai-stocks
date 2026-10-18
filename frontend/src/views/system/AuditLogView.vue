<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import AppAdvancedSearch from '@/components/AppAdvancedSearch.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppHoverInfo from '@/components/AppHoverInfo'
import {
  computed,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { ElMessage } from 'element-plus'
import AppDatePicker from '@/components/AppDatePicker.vue'
import AppControlItem from '@/components/AppControlItem.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppDetailDrawer from '@/components/AppDetailDrawer.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppDetailSection from '@/components/AppDetailSection.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { getAuditDetail, getAuditSummary, listAuditLogs, type AuditLog, type AuditQuery, type AuditSummary } from '@/api/audit'
import { getPublicDictItems } from '@/api/dict'
import { listTenants } from '@/api/tenant'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useTableSort } from '@/composables/useTableSort'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { dictTagStyleByCode } from '@/utils/dictColor'
import { getErrorStatus } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'
import { formatDateTimeSeconds } from '@/utils/dateTime'

const pageKey = 'audit-log'
const AUTO_REFRESH_MS = 30_000

interface OptionItem {
  value: string
  label: string
  color?: string | null
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
  componentLayerValuesOf, componentAllowedLayers, saveRemoteUserConfig,
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
  componentAllowedLayers,
  save: saveRemoteUserConfig,
}

const { settings, isDirty: bizDirty, reset: resetBiz } = usePageSettings(pageKey, {
  autoRefreshEnabled: false,
})
const settingsOpen = ref(false)
const autoRefreshEnabled = useDefaultedSessionValue(computed(() => settings.autoRefreshEnabled))
const filters = reactive({
  start_time: '',
  end_time: '',
  event_category: [] as string[],
  result: [] as string[],
  status: [] as string[],
  resource_code: '',
  actor_keyword: '',
  target_keyword: '',
  tenant_id: [] as string[],
})
const dateRange = ref<[string, string] | null>(null)
const hasFilters = computed(() => (
  dateRange.value !== null
  || filters.event_category.length > 0
  || filters.result.length > 0
  || filters.status.length > 0
  || filters.resource_code.trim() !== ''
  || filters.actor_keyword.trim() !== ''
  || filters.target_keyword.trim() !== ''
  || filters.tenant_id.length > 0
))

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

const { pageSize, changePageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('auditTable', 'pageSize'),
  fallback: 50,
  resetPage: () => {
    page.value = 1
  },
  reload: () => loadAll(true),
})
const AUDIT_SORT_FIELDS = ['event_time', 'event_category', 'result', 'status', 'duration_ms'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof AUDIT_SORT_FIELDS)[number]>({
  slotId: 'auditTable',
  defaultSort: 'event_time:desc',
  componentValueOf,
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
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

function tagType(value: string | null | undefined): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'success' || value === 'completed') return 'success'
  if (value === 'failed' || value === 'error' || value === 'denied') return 'danger'
  if (value === 'running' || value === 'processing') return 'warning'
  return 'info'
}

function eventTagType(value: string | null | undefined): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'security') return 'danger'
  if (value === 'task') return 'info'
  return 'success'
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

function eventTagStyle(value: string | null | undefined) {
  return dictTagStyleByCode(eventOptions.value, value)
}

function resultTagStyle(value: string | null | undefined) {
  return dictTagStyleByCode(resultOptions.value, value)
}

function statusTagStyle(value: string | null | undefined) {
  return dictTagStyleByCode(statusOptions.value, value)
}

function formatDuration(value: number | null | undefined): string {
  if (value == null) return '-'
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${value}ms`
}

function formatChangeValue(value: unknown): string {
  if (value == null || value === '') return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
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

async function loadSummary(silent = false) {
  const seq = ++summaryRequestSeq
  if (!silent) {
    summaryLoading.value = true
    summaryLoadingSeq = seq
  }
  if (!silent) summaryError.value = false
  const { page: _page, page_size: _size, sort_by: _sortBy, sort_order: _sortOrder, ...query } = buildQuery()
  try {
    const data = await getAuditSummary(query)
    if (seq !== summaryRequestSeq) return
    summary.value = data
    summaryError.value = false
  } catch {
    if (seq === summaryRequestSeq && !silent) summaryError.value = true
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
  if (!silent) {
    loadError.value = false
    permissionError.value = false
  }
  try {
    const data = await listAuditLogs(buildQuery())
    if (seq !== listRequestSeq) return
    loadError.value = false
    permissionError.value = false
    rows.value = data.list
    total.value = data.total
    if (data.list.length === 0 && page.value > 1) {
      page.value = Math.max(1, Math.ceil(data.total / pageSize.value))
      if (page.value > 1) await loadList(silent)
    }
  } catch (error) {
    if (seq === listRequestSeq) {
      if (getErrorStatus(error) === 403) permissionError.value = true
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

function auditRowActions(row: AuditLog): AppRowAction[] {
  return [
    { key: 'detail', label: '详情', onClick: () => openDetail(row) },
  ]
}

async function loadDictOptions() {
  const load = async (typeCode: string, fallback: OptionItem[]) => {
    try {
      const data = await getPublicDictItems(typeCode)
      return data.items.length
        ? data.items.map((item) => ({ value: item.code, label: item.label, color: item.color }))
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
  if (!autoRefreshEnabled.value) return
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

watch(autoRefreshEnabled, startTimer)

onMounted(async () => {
  await Promise.all([loadDictOptions(), loadTenantOptions()])
  await loadAll()
  startTimer()
})

onActivated(startTimer)
onDeactivated(stopTimer)
onBeforeUnmount(stopTimer)
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :component-value-of="componentValueOf" :layout="effective">
    <template #action>
      <div class="audit-head">
        <div class="audit-title">
          <h2 class="app-page-title">{{ menuPageTitle }}
            <HelpTip title="审计日志说明" :width="420" test-id="audit-help-tip">
              <HelpTipItem question="记录哪些事件">
                <ul>
                  <li>记录接口、任务、安全、权限、配置和字典事件。</li>
                </ul>
              </HelpTipItem>
              <HelpTipItem question="谁能查看哪些记录">
                <ul>
                  <li>系统管理员查看全局，租户管理员仅查看本租户事件。</li>
                </ul>
              </HelpTipItem>
            </HelpTip>
          </h2>
          <p class="page-subtitle">查询登录、配置变更、数据操作等审计记录。</p>
        </div>
        <div class="audit-actions">
          <el-switch v-model="autoRefreshEnabled" size="small" active-text="自动刷新" />
          <el-button :loading="tableLoading || summaryLoading" @click="refresh(false)">刷新</el-button>
          <AppHoverInfo content="导出能力不在本阶段范围" placement="bottom">
            <span><el-button disabled>导出</el-button></span>
          </AppHoverInfo>
          <PageSettingsTrigger :dirty="drawerDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </template>

    <template #summary>
      <AppAsyncRegion
        :loading="summaryLoading"
        :has-content="Boolean(summary)"
        :error="summaryError ? '请稍后重试' : ''"
        state-size="compact"
        loading-title="正在加载审计摘要…"
        error-title="审计摘要加载失败"
        empty-title="暂无审计摘要"
        retry
        @retry="loadSummary(false)"
      >
        <div class="audit-summary">
          <div class="metric">
            <span>范围事件</span>
            <b>{{ summary?.total ?? 0 }}</b>
            <em>{{ retentionHint }}</em>
          </div>
          <div class="metric">
            <span>失败 / 拒绝</span>
            <b class="warn">{{ summary?.failed ?? 0 }}</b>
            <em>含失败、拒绝和异常</em>
          </div>
          <div class="metric">
            <span>安全事件</span>
            <b class="danger">{{ summary?.by_category?.security ?? 0 }}</b>
            <em>登录失败、账号锁定等</em>
          </div>
        </div>
      </AppAsyncRegion>
    </template>

    <template #filters>
      <el-card shadow="never" class="filter-card">
        <AppAdvancedSearch
          group="audit"
          :states="{
            date: { range: true, value: dateRange, clear: () => { dateRange = null; search() } },
            event: { value: filters.event_category, options: eventOptions, clear: () => { filters.event_category = []; search() } },
            result: { value: filters.result, options: resultOptions, clear: () => { filters.result = []; search() } },
            status: { value: filters.status, options: statusOptions, clear: () => { filters.status = []; search() } },
            tenant: { value: filters.tenant_id, available: auth.isSystem, options: tenantOptions, clear: () => { filters.tenant_id = []; search() } },
            resource: { value: filters.resource_code, clear: () => { filters.resource_code = ''; search() } },
            actor: { value: filters.actor_keyword, clear: () => { filters.actor_keyword = ''; search() } },
            target: { value: filters.target_keyword, clear: () => { filters.target_keyword = ''; search() } }
          }"
        >
          <template #date>
            <AppControlItem>
              <AppDatePicker
                v-model="dateRange" @change="filterChanged"
                type="datetimerange"
                start-placeholder="开始时间"
                end-placeholder="结束时间"
                value-format="YYYY-MM-DDTHH:mm:ss"
                range-separator="至"
                class="audit-date"
              />
            </AppControlItem>
          </template>
          <template #event>
            <AppFilterSelect
              v-model="filters.event_category"
              :options="eventOptions"
              :visible-tag-count="1"
              placeholder="事件类型"
              @change="filterChanged"
            />
          </template>
          <template #result>
            <AppFilterSelect
              v-model="filters.result"
              :options="resultOptions"
              :visible-tag-count="1"
              placeholder="结果"
              @change="filterChanged"
            />
          </template>
          <template #status>
            <AppFilterSelect
              v-model="filters.status"
              :options="statusOptions"
              :visible-tag-count="1"
              placeholder="状态"
              @change="filterChanged"
            />
          </template>
          <template #tenant>
            <AppFilterSelect
              v-if="auth.isSystem"
              v-model="filters.tenant_id"
              :options="tenantOptions"
              :visible-tag-count="2"
              placeholder="租户"
              @change="filterChanged"
            />
          </template>
          <template #resource>
            <AppSearchInput v-model="filters.resource_code" placeholder="资源码" style="width: 160px" @search="search" />
          </template>
          <template #actor>
            <AppSearchInput v-model="filters.actor_keyword" placeholder="处理人" style="width: 140px" @search="search" />
          </template>
          <template #target>
            <AppSearchInput v-model="filters.target_keyword" placeholder="目标对象" style="width: 160px" @search="search" />
          </template>
          <template #commands>
            <el-button data-testid="audit-reset-filters" :disabled="!hasFilters" @click="resetFilters">重置筛选</el-button>
          </template>
        </AppAdvancedSearch>
      </el-card>
    </template>

    <template #auditTable>
      <AppStateBlock
        v-if="permissionError"
        state="error"
        variant="permission"
        title="无权限查看审计日志"
        description="请联系系统管理员调整审计查看权限"
        class="audit-state"
      />
      <AppStateBlock
        v-else-if="loadError"
        state="error"
        title="审计服务暂不可用"
        description="请稍后重试，已发生事件仍会在服务端继续写入"
        class="audit-state"
        retry
        @retry="loadAll()"
      />
      <div v-else class="audit-table-wrap">
        <AppDataTable
          :data="rows"
          kind="wide-table"
          :loading="tableLoading"
          row-key="id"
          :border="tableBorder('auditTable')"
          stripe
          framed
          clickable
          :default-sort="elementDefaultSort"
          :pagination="{ currentPage: page, pageSize, total }"
          @sort-change="onSortChange"
          @row-click="openDetail"
          @page-change="pageChanged"
          @size-change="changePageSize"
        >
          <AppTableColumn v-if="colVisible('event_time')" label="时间" prop="event_time" sortable="custom">
            <template #default="{ row }">{{ formatDateTimeSeconds(row.event_time, '-') }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('actor')" label="处理人">
            <template #default="{ row }">{{ actorText(row) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('event_category')" label="事件类型" prop="event_category" sortable="custom">
            <template #default="{ row }">
              <el-tag :type="eventTagType(row.event_category)" :style="eventTagStyle(row.event_category)" effect="plain">
                {{ eventLabel(row) }}
              </el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('resource_code')" label="资源码">
            <template #default="{ row }"><span class="mono">{{ row.resource_code || '-' }}</span></template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('target')" label="目标对象">
            <template #default="{ row }">
              <span class="target-cell">
                <b>{{ targetText(row) }}</b>
                <em v-if="targetDescription(row)">{{ targetDescription(row) }}</em>
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('result')" label="结果" prop="result" sortable="custom">
            <template #default="{ row }"><el-tag :type="tagType(row.result)" :style="resultTagStyle(row.result)" effect="plain">{{ resultLabel(row.result) }}</el-tag></template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('status')" label="状态" prop="status" sortable="custom">
            <template #default="{ row }"><el-tag :type="tagType(row.status)" :style="statusTagStyle(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag></template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('ip')" label="IP" prop="ip" />
          <AppTableColumn v-if="colVisible('duration_ms')" label="耗时" prop="duration_ms" sortable="custom">
            <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('error_summary')" label="错误摘要">
            <template #default="{ row }">{{ row.error_summary || '-' }}</template>
          </AppTableColumn>
          <AppTableColumn label="操作" role="action-compact" fixed="right">
            <template #default="{ row }">
              <AppRowActions :actions="auditRowActions(row)" :inline-limit="1" />
            </template>
          </AppTableColumn>
          <template #empty>
            <div class="app-table-empty">
              <span class="app-table-empty__description">暂无审计记录</span>
              <el-button v-if="hasFilters" @click="resetFilters">重置筛选</el-button>
            </div>
          </template>
        </AppDataTable>
      </div>
    </template>

    <template #overlays>
      <AppDetailDrawer
        v-model="detailOpen"
        title="审计详情"
        size="wide"
        class="audit-detail-drawer"
        data-testid="audit-detail-drawer"
        :state="detailLoading ? 'loading' : detailError ? 'error' : activeDetail ? 'ready' : 'empty'"
        :state-title="detailError ? '详情读取失败' : detailLoading ? '正在读取审计详情…' : '暂无审计详情'"
        :state-description="detailError ? '请关闭后重试' : ''"
      >
          <template v-if="activeDetail">
            <section class="detail-hero">
              <div class="detail-title">
                <b>{{ targetText(activeDetail) }}</b>
                <em v-if="targetDescription(activeDetail)">{{ targetDescription(activeDetail) }}</em>
                <span>{{ formatDateTimeSeconds(activeDetail.event_time, '-') }} · {{ actorText(activeDetail) }}</span>
              </div>
              <div class="detail-tags">
                <el-tag :type="eventTagType(activeDetail.event_category)" :style="eventTagStyle(activeDetail.event_category)" effect="plain">{{ eventLabel(activeDetail) }}</el-tag>
                <el-tag :type="tagType(activeDetail.result)" :style="resultTagStyle(activeDetail.result)" effect="plain">{{ resultLabel(activeDetail.result) }}</el-tag>
                <el-tag :type="tagType(activeDetail.status)" :style="statusTagStyle(activeDetail.status)" effect="plain">{{ statusLabel(activeDetail.status) }}</el-tag>
              </div>
            </section>

            <AppDetailSection title="基础信息" :bordered="false">
              <AppDetailFields :columns="2">
                <AppDetailField label="处理人" :value="actorText(activeDetail)" />
                <AppDetailField label="租户" :value="activeDetail.tenant_id" />
                <AppDetailField label="来源 IP" :value="activeDetail.ip" />
                <AppDetailField label="耗时" :value="formatDuration(activeDetail.duration_ms)" />
                <AppDetailField label="资源码" :value="activeDetail.resource_code" mono />
                <AppDetailField label="事件类型" :value="activeDetail.event_type" />
                <AppDetailField label="中文说明" :value="targetDescription(activeDetail)" />
                <AppDetailField label="请求方法" :value="activeDetail.method" />
                <AppDetailField label="请求路径" :value="activeDetail.path" span="full" mono />
              </AppDetailFields>
            </AppDetailSection>

            <AppDetailSection title="字段变更">
              <p v-if="!activeDetail.changes?.length" class="muted">无字段级变更</p>
              <AppScrollArea v-else class="change-table">
                <AppDataTable
                  :data="activeDetail.changes"
                  embedded
                  kind="wide-table"
                  row-key="field"
                  size="small"
                  aria-label="字段变更"
                >
                  <AppTableColumn label="字段" prop="field" role="key">
                    <template #default="{ row }"><span class="change-field">{{ row.field }}</span></template>
                  </AppTableColumn>
                  <AppTableColumn label="变更前" role="description">
                    <template #default="{ row }"><span class="change-before">{{ formatChangeValue(row.before) }}</span></template>
                  </AppTableColumn>
                  <AppTableColumn label="变更后" role="description">
                    <template #default="{ row }"><span class="change-after">{{ formatChangeValue(row.after) }}</span></template>
                  </AppTableColumn>
                </AppDataTable>
              </AppScrollArea>
            </AppDetailSection>

            <AppDetailSection title="错误摘要">
              <p :class="{ muted: !activeDetail.error_summary }">{{ activeDetail.error_summary || '无错误摘要' }}</p>
            </AppDetailSection>

            <AppDetailSection title="事件上下文">
              <AppScrollArea as="pre" class="json">{{ JSON.stringify(activeDetail.context || {}, null, 2) }}</AppScrollArea>
            </AppDetailSection>
          </template>
        <template #footer>
          <el-button @click="detailOpen = false">关闭</el-button>
        </template>
      </AppDetailDrawer>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="审计日志"
        :dirty="drawerDirty"
        :page-key="pageKey"
        :config="drawerConfig"
        @reset="resetBiz(); resetLayout()"
      >
        <template #business>
          <PageSettingSection section-key="refresh" title="刷新偏好" desc="设置进入页面时是否默认自动刷新；页面顶部开关只影响本次访问。">
            <PageSettingItem label="默认自动刷新" layout="inline">
              <el-switch v-model="settings.autoRefreshEnabled" />
            </PageSettingItem>
          </PageSettingSection>
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.audit-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.audit-title {
  min-width: 0;
}
.audit-title h2 {
  margin: 0;
}
.audit-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}
.audit-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--app-space-3);
}
.metric {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
  padding: 11px 12px;
  min-width: 0;
}
.metric > span,
.metric > em {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  font-style: normal;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.metric b {
  display: block;
  margin-top: 4px;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-page-title-sm);
  line-height: var(--app-line-height-tight);
}
.metric b.warn { color: var(--el-color-warning); }
.metric b.danger { color: var(--el-color-danger); }
.audit-date {
  width: 300px;
  max-width: 100%;
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
}
.mono {
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-caption);
}
.target-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--app-space-1);
}
.target-cell b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: var(--app-font-weight-medium);
}
.target-cell em,
.detail-title em {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  font-style: normal;
  line-height: var(--app-line-height-compact);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-hero {
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
  gap: var(--app-space-3);
}
.detail-title {
  min-width: 0;
}
.detail-title b {
  display: block;
  overflow-wrap: anywhere;
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-data);
  font-weight: var(--app-font-weight-section);
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
  font-size: var(--app-font-size-caption);
}
.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
  justify-content: flex-end;
}
.change-table {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}
.change-table :deep(.cell) {
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
  text-align: left;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.change-field {
  color: var(--el-color-primary);
  font-family: var(--app-font-family-mono);
}
.change-before {
  color: var(--el-text-color-secondary);
}
.change-after {
  color: var(--el-text-color-primary);
}
.json {
  margin: 0;
  max-height: 260px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--app-section-bg);
  --app-scroll-padding-top: 10px; --app-scroll-padding-right: 10px; --app-scroll-padding-bottom: 10px; --app-scroll-padding-left: 10px;
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-reading);
  white-space: pre-wrap;
}
@container app-viewport (max-width: 980px) {
  .audit-summary {
    grid-template-columns: repeat(2, minmax(150px, 1fr));
  }
  .audit-head {
    flex-direction: column;
  }
  .audit-actions {
    justify-content: flex-start;
  }
}
</style>

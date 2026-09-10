<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import {
  getDataQuality, fixQualityIssue, ignoreQualityIssue, restoreQualityMonitoring,
  resetQualityIssue, recoverQualityBatch, ignoreQualityBatch,
  markDelisted, createTask, getTask,
  ISSUE_TYPE_LABEL, ISSUE_TYPES_ACTIVE, SEVERITY_LABEL, ISSUE_STATUS_LABEL, ISSUE_LAYER, LAYER_LABEL,
  RECOVER_ACTION_LABEL,
  type DataQuality, type QualityIssue, type QualityIgnoreScope, type CheckupCheck, type CheckupReport,
  type CheckupStatus,
} from '@/api/data'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDatePicker from '@/components/AppDatePicker.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useTableSort } from '@/composables/useTableSort'
import { getErrorMessage, isTimeoutError } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'

const route = useRoute()
const router = useRouter()
const settingsOpen = ref(false)
// 默认筛选/隐藏已办属业务态偏好，保留 usePageSettings；默认排序与列显隐迁入组件配置层（plan.md §13.3）。
const qualityDefaults = {
  defaultStatus: 'todo' as 'todo' | 'all' | 'open',
  defaultSeverity: 'all' as 'all' | 'high',
  hideDoneRows: false,
}
const { settings, isDirty, reset } = usePageSettings('data-quality', qualityDefaults)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const qualityLayout = getPageLayout('data-quality')
const {
  effective: qualityEffective,
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
  componentLayerValuesOf, componentAllowedLayers,
} = useRemoteLayoutConfig(qualityLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }

// 抽屉写值由 ComponentAutoSettings 自动渲染；页面只保留渲染要读的 getter。
const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
const loading = ref(false)
const loadError = ref('')
const data = ref<DataQuality | null>(null)
const page = ref(1)
const applyFilter = () => {
  page.value = 1
  void load()
}
const { pageSize: size, changePageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('table', 'pageSize'),
  resetPage: () => {
    page.value = 1
  },
  reload: load,
})
// 类型/严重度/状态多选；默认勾选「未处理 + 修复中」（待办两态），code 为模糊文本
const filters = ref<{ issue_type: string[]; severity: string[]; status: string[]; code: string }>(
  { issue_type: [], severity: [], status: ['open', 'fixing'], code: '' })
const QUALITY_SORT_FIELDS = ['time', 'severity'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof QUALITY_SORT_FIELDS)[number]>({
  slotId: 'table',
  defaultSort: 'time:desc',
  componentValueOf,
  allowedFields: QUALITY_SORT_FIELDS,
  onChanged: () => {
    page.value = 1
    void load()
  },
})

const sevType: Record<string, 'danger' | 'warning' | 'info'> = { high: 'danger', mid: 'warning', low: 'info' }
const statType: Record<string, 'info' | 'warning' | 'success'> = {
  open: 'info', fixing: 'warning', resolved: 'success', ignored: 'info',
}
const displayList = computed(() => {
  let list = [...(data.value?.list ?? [])]
  if (settings.hideDoneRows) list = list.filter((row) => row.status !== 'resolved' && row.status !== 'ignored')
  return list
})

// 详情列展示文案：部分 issue_type 的 detail 是结构化 JSON（修复链路解析 periods/board_type 等
// 字段定向重采用），展示层只取人读文案（message/reason），非 JSON 或缺文案时原样显示。
function detailText(detail: string): string {
  const s = (detail ?? '').trim()
  if (!s.startsWith('{')) return detail
  try {
    const payload = JSON.parse(s)
    const msg = payload?.message ?? payload?.reason
    if (typeof msg === 'string' && msg) return msg
  } catch { /* 非 JSON，原样显示 */ }
  return detail
}

const defaultStatusFilters = computed(() => settings.defaultStatus === 'all'
  ? []
  : settings.defaultStatus === 'open'
    ? ['open']
    : ['open', 'fixing'])
const defaultSeverityFilters = computed(() => settings.defaultSeverity === 'high' ? ['high'] : [])
function applyDefaultFilters() {
  filters.value.status = [...defaultStatusFilters.value]
  filters.value.severity = [...defaultSeverityFilters.value]
}
const hasQueryFilters = computed(() => (
  filters.value.issue_type.length > 0
  || filters.value.code.trim() !== ''
  || filters.value.status.join(',') !== defaultStatusFilters.value.join(',')
  || filters.value.severity.join(',') !== defaultSeverityFilters.value.join(',')
))
let suppressFilterReload = false

const qualityListRequest = createLatestRequestGuard()
async function load() {
  const requestId = qualityListRequest.begin()
  loading.value = true
  loadError.value = ''
  try {
    const result = await getDataQuality({
      issue_type: filters.value.issue_type.join(',') || undefined,
      severity: filters.value.severity.join(',') || undefined,
      status: filters.value.status.join(',') || undefined,
      code: filters.value.code.trim() || undefined,
      page: page.value, size: size.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    })
    if (!qualityListRequest.isCurrent(requestId)) return
    data.value = result
  } catch (error) {
    if (!qualityListRequest.isCurrent(requestId)) return
    loadError.value = getErrorMessage(error, '数据质量加载失败')
  } finally {
    if (qualityListRequest.isCurrent(requestId)) loading.value = false
  }
}

// 筛选变更自动触发（列表交互标准）；多选数组用 deep 监听
watch(() => [filters.value.issue_type, filters.value.severity, filters.value.status],
  () => {
    if (suppressFilterReload) return
    page.value = 1
    load()
  }, { deep: true })

async function applyDefaultFiltersOnce(): Promise<void> {
  suppressFilterReload = true
  applyDefaultFilters()
  page.value = 1
  await nextTick()
  suppressFilterReload = false
  await load()
}
watch(() => [settings.defaultStatus, settings.defaultSeverity], () => { void applyDefaultFiltersOnce() })

async function resetQueryFilters(): Promise<void> {
  if (!hasQueryFilters.value) return
  suppressFilterReload = true
  filters.value.issue_type = []
  filters.value.code = ''
  applyDefaultFilters()
  page.value = 1
  await nextTick()
  suppressFilterReload = false
  await load()
}

// 轮询任务到终态后回调（完成即自动刷新列表，闭环4）。返回任务结果供按真实结果提示。
async function waitTask(taskId: string): Promise<{ status: string; message: string; result?: Record<string, any> | null }> {
  let timeoutWarned = false
  for (;;) {
    try {
      // 状态轮询的单次超时不代表后台任务失败：静默该请求的全局错误 toast，
      // 保留 task_id 并继续轮询，避免用户重复提交实际仍在运行的写任务。
      const t = await getTask(taskId, { silent: true })
      if (['done', 'failed', 'interrupted'].includes(t.status)) {
        return { status: t.status, message: t.message, result: t.result }
      }
    } catch (error) {
      if (!isTimeoutError(error)) throw error
      if (!timeoutWarned) {
        timeoutWarned = true
        ElMessage.warning('状态查询暂时超时，后台任务仍在运行，正在自动重试')
      }
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
}

const busyId = ref<number | null>(null)
async function fixOne(row: QualityIssue) {
  busyId.value = row.id
  row.status = 'fixing'
  try {
    const { task_id } = await fixQualityIssue(row.id)
    ElMessage.info(`正在${RECOVER_ACTION_LABEL[row.issue_type] ?? '恢复'}：${row.code}…`)
    const t = await waitTask(task_id)
    // 以任务结果(result.ok)而非仅任务状态判定成败：恢复中途失败的任务仍是 done，但 ok=false、
    // 问题已退回待处理——此时必须给警告而非"成功"（修复"日志失败却弹成功、状态卡修复中"）。
    const succeeded = t.status === 'done' && (t.result?.ok ?? false)
    if (succeeded) ElMessage.success(t.message || '恢复完成')
    else ElMessage.warning(t.message || '恢复未完成，问题已退回待处理')
    await load()
  } catch { row.status = 'open' } finally { busyId.value = null }
}

const ignoreDlg = ref(false)
const ignoreRow = ref<QualityIssue | null>(null)
const ignoreScope = ref<QualityIgnoreScope>('occurrence')
const ignoreBatch = ref(false)
const ignoreBatchLabel = ref('')
const ignoring = ref(false)
function openIgnore(row: QualityIssue) {
  ignoreRow.value = row
  ignoreBatch.value = false
  ignoreBatchLabel.value = ''
  ignoreScope.value = 'occurrence'
  ignoreDlg.value = true
}

async function confirmIgnore() {
  if (!ignoreBatch.value && !ignoreRow.value) return
  ignoring.value = true
  try {
    if (ignoreBatch.value) {
      const { count } = await ignoreQualityBatch(currentBatchFilter(), ignoreScope.value)
      ElMessage.success(ignoreScope.value === 'occurrence'
        ? `已将 ${count} 条问题标记为本次正常`
        : `已将 ${count} 条问题标记为整体正常；恢复监控前不再上报对应对象的同类问题`)
    } else {
      await ignoreQualityIssue(ignoreRow.value!.id, ignoreScope.value)
      ElMessage.success(ignoreScope.value === 'occurrence'
        ? '已忽略本次；问题消失后，本次忽略会自动失效'
        : '已整体忽略；恢复监控前不再上报该对象的同类问题')
    }
    ignoreDlg.value = false
    await load()
  } catch { /* 拦截器弹错 */ } finally { ignoring.value = false }
}

async function restoreMonitoring(row: QualityIssue) {
  try {
    await ElMessageBox.confirm(
      '恢复后，当前异常若仍存在，将在下一次质检或采集时重新上报。确认恢复监控？',
      '恢复监控',
      { type: 'warning' },
    )
  } catch { return }
  try {
    await restoreQualityMonitoring(row.id)
    ElMessage.success('已恢复监控')
    await load()
  } catch { /* 拦截器弹错 */ }
}

// 手动复位「修复中」→「未处理」：修复任务失败/中断/卡死时解套，让问题重新可恢复
async function resetOne(row: QualityIssue) {
  try {
    await resetQualityIssue(row.id)
    ElMessage.success('已复位为未处理，可重新发起恢复')
    await load()
  } catch { /* 拦截器弹错 */ }
}

// 标记退市：应对数据源退市识别不准（一直把已退市股报缺口/滞后）。指定退市日 → 写 delist_date +
// 解决该股缺口/滞后，覆盖鲜活扫描据 delist_date 自动排除，不再复发。仅缺口/滞后类可用。
const GAP_TYPES = ['data_gap', 'stale']
const delistDlg = ref(false)
const delistRow = ref<QualityIssue | null>(null)
const delistDate = ref('')
const delisting = ref(false)
function openDelist(row: QualityIssue) {
  delistRow.value = row
  delistDate.value = (row.trade_date || '').slice(0, 10)   // 截到 YYYY-MM-DD（trade_date 可能带 00:00:00）
  delistDlg.value = true
}

function qualityRowActions(row: QualityIssue): AppRowAction[] {
  if (row.status === 'ignored' && row.ignore_active) {
    return [{
      key: 'restore-monitoring',
      label: '恢复监控',
      testId: `quality-restore-monitoring-${row.id}`,
      type: 'warning',
      permission: 'data-quality:fix',
      onClick: () => restoreMonitoring(row),
    }]
  }
  if (row.status !== 'open' && row.status !== 'fixing') return []
  const busy = busyId.value !== null
  const fixingElsewhere = row.status === 'fixing' && busyId.value !== row.id
  return [
    {
      key: 'recover',
      label: fixingElsewhere ? '处理中…' : (RECOVER_ACTION_LABEL[row.issue_type] ?? '恢复'),
      type: 'primary',
      permission: 'data-quality:fix',
      loading: busyId.value === row.id,
      disabled: busy,
      onClick: () => fixOne(row),
    },
    {
      key: 'reset',
      label: '复位',
      type: 'warning',
      permission: 'data-quality:fix',
      visible: fixingElsewhere,
      onClick: () => resetOne(row),
    },
    {
      key: 'delist',
      label: '标记退市',
      type: 'danger',
      permission: 'data-quality:fix',
      visible: GAP_TYPES.includes(row.issue_type),
      disabled: busy,
      placement: 'more',
      onClick: () => openDelist(row),
    },
    {
      key: 'ignore',
      label: '标记正常',
      testId: `quality-ignore-${row.id}`,
      type: 'info',
      permission: 'data-quality:fix',
      disabled: busy,
      placement: 'more',
      onClick: () => openIgnore(row),
    },
  ]
}
async function confirmDelist() {
  if (!delistRow.value) return
  if (!delistDate.value) { ElMessage.warning('请指定退市日期'); return }
  delisting.value = true
  try {
    const r = await markDelisted(delistRow.value.id, delistDate.value)
    ElMessage.success(`已标记 ${r.code} 于 ${r.delist_date} 退市，解决 ${r.resolved} 项缺口/滞后`)
    delistDlg.value = false
    await load()
  } catch { /* 拦截器弹错 */ } finally { delisting.value = false }
}

function rowClass({ row }: { row: QualityIssue }): string {
  return row.status === 'resolved' || row.status === 'ignored' ? 'row-done' : ''
}

function toggleIssueType(issueType: string) {
  const selected = filters.value.issue_type
  filters.value.issue_type = selected.includes(issueType)
    ? selected.filter((t) => t !== issueType)
    : [...selected, issueType]
}

const verifyRunning = ref(false)
async function runVerify() {
  if (verifyRunning.value) return
  verifyRunning.value = true
  try {
    const { task_id } = await createTask('verify')
    ElMessage.info('质检任务已提交，可在「数据采集 › 任务中心」查看进度')
    const t = await waitTask(task_id)
    if (t.status === 'done') ElMessage.success(t.message || '质检完成')
    else if (t.status === 'failed') ElMessage.error(t.message || '质检失败，请前往任务中心查看日志')
    else ElMessage.warning(t.message || '质检已终止')
    await load()
  } catch { /* 并发/非超时错误由拦截器提示 */ } finally { verifyRunning.value = false }
}

// 结构体检（checkup 任务）：本地 SQL 的结构/价格正确性/字段契约核查，结果以只读报告弹窗呈现。
// 与质检互补——能查出质检盲区（如在市股逐行 total_mv 缺失），但不写台账、无修复闭环。
const checkupRunning = ref(false)
const checkupOpen = ref(false)
const checkupReport = ref<CheckupReport | null>(null)
function checkupStatus(check: CheckupCheck): CheckupStatus {
  return check.status ?? (check.ok ? 'pass' : 'fail')
}
function checkupTagType(check: CheckupCheck): 'success' | 'warning' | 'danger' {
  const status = checkupStatus(check)
  return status === 'pass' ? 'success' : status === 'warn' ? 'warning' : 'danger'
}
function checkupFlag(check: CheckupCheck): 'PASS' | 'WARN' | 'FAIL' {
  const status = checkupStatus(check)
  return status === 'pass' ? 'PASS' : status === 'warn' ? 'WARN' : 'FAIL'
}
const checkupWarningCount = computed(() => checkupReport.value?.warning_count
  ?? checkupReport.value?.groups.flatMap((group) => group.checks)
    .filter((check) => checkupStatus(check) === 'warn').length
  ?? 0)
const checkupHeaderType = computed<'success' | 'warning' | 'danger'>(() => {
  if (!checkupReport.value?.all_ok) return 'danger'
  return checkupWarningCount.value ? 'warning' : 'success'
})
const checkupHeaderText = computed(() => {
  if (!checkupReport.value) return ''
  if (!checkupReport.value.all_ok) return `${checkupReport.value.fails.length} 项未通过`
  return checkupWarningCount.value ? `体检通过，${checkupWarningCount.value} 项提醒` : '全部通过'
})
const checkupScoreText = computed(() => {
  if (!checkupReport.value) return ''
  const warning = checkupWarningCount.value ? ` · ${checkupWarningCount.value} 提醒` : ''
  return `${checkupReport.value.passed} 通过${warning} / ${checkupReport.value.total} 总项`
})
async function runCheckup() {
  checkupRunning.value = true
  try {
    const { task_id } = await createTask('checkup')
    ElMessage.info('数据结构体检中…（也可在「数据采集 › 任务中心」看实时日志）')
    const t = await waitTask(task_id)
    const report = (t.result?.checkup ?? null) as CheckupReport | null
    if (report) {
      checkupReport.value = report
      checkupOpen.value = true
    } else {
      ElMessage.warning(t.message || '体检未返回结果')
    }
  } catch { /* 并发/错误由拦截器提示 */ } finally { checkupRunning.value = false }
}

// 至少选一个筛选条件（类型/严重度/代码）才允许一键恢复，避免误整库恢复
const canBatch = computed(() =>
  !!(filters.value.issue_type.length || filters.value.severity.length || filters.value.code.trim()))
const batching = ref(false)
function currentBatchFilter() {
  const f = filters.value
  return {
    issue_type: f.issue_type.length ? f.issue_type : undefined,
    severity: f.severity.length ? f.severity : undefined,
    code: f.code.trim() || undefined,
  }
}

async function batchRecover() {
  const f = filters.value
  const scope = [f.issue_type.map((t) => ISSUE_TYPE_LABEL[t] ?? t).join('、'),
                 f.severity.map((s) => `${SEVERITY_LABEL[s]}危`).join('、'),
                 f.code.trim()].filter(Boolean).join(' / ')
  try {
    await ElMessageBox.confirm(
      `将对当前筛选【${scope}】下所有「待处理」问题按类型分派恢复（复检通过才标记已解决），`
      + '可能较久，可随时在任务中心「终止」。确认？', '一键恢复', { type: 'warning' })
  } catch { return }
  batching.value = true
  try {
    const { count } = await recoverQualityBatch(currentBatchFilter())
    ElMessage.success(`已提交批量恢复 ${count} 条，前往任务中心查看进度（可终止）`)
    router.push('/data/ingest')   // 跳任务中心看进度/实时日志
  } catch { /* 400无匹配/409并发 由拦截器提示 */ } finally { batching.value = false }
}

function batchMarkNormal() {
  const f = filters.value
  ignoreRow.value = null
  ignoreBatch.value = true
  ignoreBatchLabel.value = [f.issue_type.map((t) => ISSUE_TYPE_LABEL[t] ?? t).join('、'),
                            f.severity.map((s) => `${SEVERITY_LABEL[s]}危`).join('、'),
                            f.code.trim()].filter(Boolean).join(' / ')
  ignoreScope.value = 'occurrence'
  ignoreDlg.value = true
}

onMounted(() => {
  applyDefaultFilters()
  // 支持从概览/总览带参下钻：?severity=high（按严重度）或 ?code=600000.SH（按个股）
  const sev = route.query.severity
  if (typeof sev === 'string' && ['high', 'mid', 'low'].includes(sev)) filters.value.severity = [sev]
  const code = route.query.code
  if (typeof code === 'string' && code) { filters.value.code = code; filters.value.status = [] }
  const issueType = route.query.issue_type
  if (typeof issueType === 'string') {
    filters.value.issue_type = issueType.split(',').filter((x) => ISSUE_TYPES_ACTIVE.includes(x as any))
  }
  load()
})
</script>

<template>
  <LayoutHost :layout="qualityEffective">
    <template #action>
    <div class="lh-action">
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        数据质量
        <HelpTip title="数据质量怎么来的、怎么处理？" :width="480">
          <HelpTipItem question="质量问题如何闭环">
            <ul>
              <li>个股四层、ST 点时事实与板块专项质量台账中的每条问题按类型采用对应恢复手段，只有复检通过才标记「已解决」。</li>
            </ul>
          </HelpTipItem>
          <HelpTipItem question="质量口径是什么">
            <ul>
              <li>L1 入库闸门、L2 字段契约、L3 正确性、L4 覆盖鲜活；ST 层检查逐日事实缺失、非权威和投影不一致；板块另查指数、成分与资金流。</li>
            </ul>
          </HelpTipItem>
          <HelpTipItem question="问题从哪里来">
            <ul>
              <li>采集入库自动记录 L1 问题。</li>
              <li>本页「立即质检」与定时「数据质检」使用同一方法检查 L2 至 L4、ST、市场指数和板块专项问题。</li>
              <li>恢复后复检通过会解决问题，并重扫同类板块问题以同步收敛关联台账。</li>
            </ul>
          </HelpTipItem>
          <HelpTipItem question="何时恢复或标记正常">
            <ul>
              <li>缺口先按漏采重采，源端确无数据则确认为停牌且不再上报；新股首日大涨等真实极端值可标记正常。</li>
              <li>需要批量处理时，先按问题类型、严重度或对象筛选，再选择仅忽略本次或整体忽略。</li>
            </ul>
          </HelpTipItem>
        </HelpTip>
      </h2>
      <p class="page-subtitle">个股四层与板块专项质量台账，每条问题按类型恢复，复检通过才标记「已解决」。</p>
      </div>
      <div class="page-head-actions">
        <el-button v-permission="'data-quality:fix'" type="warning" plain :loading="batching" :disabled="!canBatch"
                   :title="canBatch ? '' : '请先选择类型/严重度/代码再批量恢复'" @click="batchRecover">
          一键恢复
        </el-button>
        <el-button v-permission="'data-quality:fix'" type="info" plain
                   :loading="ignoring && ignoreBatch" :disabled="!canBatch"
                   :title="canBatch ? '' : '请先选择类型/严重度/代码再批量标记正常'" @click="batchMarkNormal">
          一键标记正常
        </el-button>
        <el-button v-permission="'data-task:manage'" type="primary" plain
                   :loading="verifyRunning" :disabled="verifyRunning" @click="runVerify">立即质检</el-button>
        <el-button v-permission="'data-task:manage'" type="success" plain :loading="checkupRunning" @click="runCheckup">结构体检</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>

    <el-card shadow="never" class="filter-card">
    <AppControlRow class="filter-row">
      <el-select v-model="filters.status" placeholder="状态" multiple clearable collapse-tags
                 collapse-tags-tooltip :max-collapse-tags="3" style="width: 240px" @change="applyFilter">
        <el-option v-for="(l, k) in ISSUE_STATUS_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-select v-model="filters.severity" placeholder="严重度" multiple clearable collapse-tags
                 collapse-tags-tooltip :max-collapse-tags="3" style="width: 200px" @change="applyFilter">
        <el-option v-for="(l, k) in SEVERITY_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-select v-model="filters.issue_type" placeholder="问题类型" multiple clearable collapse-tags
                 collapse-tags-tooltip :max-collapse-tags="3" style="width: 280px" @change="applyFilter">
        <el-option v-for="(l, k) in ISSUE_TYPE_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <AppSearchInput v-model="filters.code" placeholder="股票/板块代码或名称" style="width: 210px" @search="applyFilter" />
      <el-button data-testid="quality-reset-filters" :disabled="!hasQueryFilters" @click="resetQueryFilters">重置筛选</el-button>
      <div class="summary app-inline-info">
        <el-tag
          v-for="s in data?.summary ?? []"
          :key="s.issue_type"
          size="small"
          type="warning"
          :effect="filters.issue_type.includes(s.issue_type) ? 'dark' : 'plain'"
          class="sm-tag"
          :class="{ active: filters.issue_type.includes(s.issue_type) }"
          tabindex="0"
          role="checkbox"
          :aria-checked="filters.issue_type.includes(s.issue_type)"
          @click="toggleIssueType(s.issue_type)"
          @keydown.enter.prevent="toggleIssueType(s.issue_type)"
          @keydown.space.prevent="toggleIssueType(s.issue_type)"
        >
          {{ ISSUE_TYPE_LABEL[s.issue_type] ?? s.issue_type }}: {{ s.n }}
        </el-tag>
      </div>
    </AppControlRow>
    </el-card>
    </div>
    </template>

    <template #main>
    <el-card shadow="never">
      <AppStateBlock
        v-if="loadError"
        state="error"
        :title="data ? '数据质量刷新失败' : '数据质量加载失败'"
        :description="loadError"
        retry
        @retry="load"
      />
      <AppDataTable
        v-else
        :data="displayList"
        size="small"
        :loading="loading"
        :border="tableBorder('table')"
        :row-class-name="rowClass"
        :default-sort="elementDefaultSort"
        :pagination="{ currentPage: page, pageSize: size, total: data?.total ?? 0, pageSizes: PAGE_SIZE_OPTIONS }"
        @sort-change="onSortChange"
        @page-change="(p: number) => { page = p; load() }"
        @size-change="changePageSize"
      >
        <AppTableColumn v-if="colVisible('severity')" label="严重度" prop="severity" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="sevType[row.severity] ?? 'info'" size="small" effect="dark">{{ SEVERITY_LABEL[row.severity] ?? row.severity }}</el-tag>
          </template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" />
        <AppTableColumn v-if="colVisible('name')" label="名称" prop="name" />
        <AppTableColumn v-if="colVisible('date')" label="日期">
          <template #default="{ row }">{{ (row.trade_date || '—').slice(0, 10) }}</template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('layer')" label="层">
          <template #default="{ row }">
            <el-tooltip :content="LAYER_LABEL[ISSUE_LAYER[row.issue_type]] ?? '—'" placement="top">
              <span class="layer-tag">{{ ISSUE_LAYER[row.issue_type] ?? '—' }}</span>
            </el-tooltip>
          </template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('type')" label="类型">
          <template #default="{ row }">{{ ISSUE_TYPE_LABEL[row.issue_type] ?? row.issue_type }}</template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('detail')" label="详情">
          <template #default="{ row }">{{ detailText(row.detail) }}</template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('status')" label="状态">
          <template #default="{ row }">
            <el-tag :type="statType[row.status] ?? 'info'" size="small" effect="plain">{{ ISSUE_STATUS_LABEL[row.status] ?? row.status }}</el-tag>
            <span v-if="row.status === 'ignored' && row.ignore_scope" class="ignore-scope-label">
              {{ row.ignore_active
                ? (row.ignore_scope === 'object' ? '整体' : '本次')
                : (row.ignore_scope === 'object' ? '整体忽略已结束' : '本次豁免已结束') }}
            </span>
          </template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('detectedAt')" label="检出时间" prop="time" sortable="custom">
          <template #default="{ row }">{{ (row.detected_at || '').slice(0, 19) }}</template>
        </AppTableColumn>
        <AppTableColumn label="操作" role="action" fixed="right">
          <template #default="{ row }">
            <AppRowActions :actions="qualityRowActions(row)" :inline-limit="2" />
          </template>
        </AppTableColumn>
      </AppDataTable>
    </el-card>
    </template>

    <template #overlays>
    <el-dialog v-model="ignoreDlg" title="选择忽略范围" width="440px" data-testid="quality-ignore-dialog">
      <p class="ignore-tip">
        <template v-if="ignoreBatch">
          当前筛选【{{ ignoreBatchLabel }}】下所有“待处理”问题
        </template>
        <template v-else>
          {{ ignoreRow?.code || ignoreRow?.name || '当前对象' }} ·
          {{ ignoreRow ? (ISSUE_TYPE_LABEL[ignoreRow.issue_type] ?? ignoreRow.issue_type) : '' }}
        </template>
      </p>
      <el-radio-group v-model="ignoreScope" class="ignore-scope-group" data-testid="quality-ignore-scope">
        <el-radio value="occurrence" border>
          <span class="ignore-option-title">仅忽略本次（推荐）</span>
          <span class="ignore-option-note">异常持续期间不重复上报；消失后再发生会重新报告。</span>
        </el-radio>
        <el-radio value="object" border>
          <span class="ignore-option-title">整体忽略</span>
          <span class="ignore-option-note">
            {{ ignoreBatch
              ? '持续忽略筛选结果中每个对象的同类问题，直到逐项恢复监控。'
              : '持续忽略该对象的同类问题，直到手动恢复监控。' }}
          </span>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="ignoreDlg = false">取消</el-button>
        <el-button v-permission="'data-quality:fix'" type="primary" :loading="ignoring"
                   data-testid="quality-ignore-confirm" @click="confirmIgnore">确认忽略</el-button>
      </template>
    </el-dialog>

    <!-- 标记退市对话框 -->
    <el-dialog v-model="delistDlg" title="标记退市" width="440px">
      <p class="delist-tip">
        用于<b>数据源退市识别不准</b>（已退市却仍被当在市股、持续报缺口/滞后）的场景。指定退市日后：
        写入该股退市日、解决其缺口/滞后问题，之后覆盖鲜活扫描会据退市日自动排除该股，不再复发。
      </p>
      <el-form label-width="84px">
        <el-form-item label="股票">
          <span>{{ delistRow?.code }} {{ delistRow?.name }}</span>
        </el-form-item>
        <el-form-item label="退市日期">
          <AppDatePicker v-model="delistDate" type="date" value-format="YYYY-MM-DD"
                         format="YYYY年MM月DD日" placeholder="该股最后有效交易日" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="delistDlg = false">取消</el-button>
        <el-button v-permission="'data-quality:fix'" type="warning" :loading="delisting" @click="confirmDelist">确认标记退市</el-button>
      </template>
    </el-dialog>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="数据质量"
      :dirty="isDirty || layoutDirty"
      page-key="data-quality"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="默认查询">
          <div class="setting-item">
            <div class="setting-label">状态筛选</div>
            <PageSegmented v-model="settings.defaultStatus" aria-label="状态筛选" :options="[
              { label: '待办两态', value: 'todo' },
              { label: '仅未处理', value: 'open' },
              { label: '全部', value: 'all' },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">严重度筛选</div>
            <PageSegmented v-model="settings.defaultSeverity" aria-label="严重度筛选" :options="[
              { label: '全部', value: 'all' },
              { label: '高危优先', value: 'high' },
            ]" />
          </div>
          <PageToggleRow v-model="settings.hideDoneRows" label="隐藏已解决/已忽略" />
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>

    <el-dialog v-model="checkupOpen" title="数据结构体检报告" width="640px" align-center>
      <template v-if="checkupReport">
        <div class="checkup-head">
          <el-tag :type="checkupHeaderType" effect="dark" size="large">
            {{ checkupHeaderText }}
          </el-tag>
          <span class="checkup-score">{{ checkupScoreText }}</span>
          <span class="checkup-note">结构合法性 + 价格正确性 + 字段契约 + 板块数据（本地核查，与质检台账互补，不写台账）</span>
        </div>
        <div v-for="g in checkupReport.groups" :key="g.group" class="checkup-group">
          <div class="checkup-group-title">{{ g.group }}</div>
          <div v-for="c in g.checks" :key="c.name" class="checkup-row"
               :class="{ bad: checkupStatus(c) === 'fail', warn: checkupStatus(c) === 'warn' }">
            <el-tooltip :disabled="checkupStatus(c) !== 'warn' || !(c.help || c.detail)"
                        :content="c.help || c.detail" placement="top">
              <el-tag :type="checkupTagType(c)" size="small" effect="plain" class="checkup-flag">
                {{ checkupFlag(c) }}
              </el-tag>
            </el-tooltip>
            <span class="checkup-name">{{ c.name }}</span>
            <span v-if="c.detail" class="checkup-detail">{{ c.detail }}</span>
          </div>
        </div>
      </template>
    </el-dialog>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; }
.setting-item { display: flex; flex-direction: column; gap: var(--app-space-2); }
.setting-label { font-size: var(--app-font-size-body); color: var(--page-settings-text-subtle); }
.layer-tag { font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.filter-row { flex-wrap: wrap; }
.summary { margin-left: auto; }
.sm-tag { cursor: pointer; user-select: none; }
.sm-tag:focus-visible {
  outline: 2px solid var(--el-color-warning-light-3);
  outline-offset: 2px;
}
.sm-tag.active {
  box-shadow: 0 0 0 1px var(--el-color-warning-light-3);
}
.muted { color: var(--el-text-color-secondary); }
.ignore-scope-label { margin-left: 6px; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.ignore-tip { margin: 0 0 var(--app-space-4); color: var(--el-text-color-secondary); }
.ignore-scope-group { display: flex; flex-direction: column; align-items: stretch; gap: var(--app-space-3); }
.ignore-scope-group :deep(.el-radio) { height: auto; margin: 0; padding: 12px; align-items: flex-start; }
.ignore-scope-group :deep(.el-radio__label) { display: flex; flex-direction: column; gap: var(--app-space-1); white-space: normal; }
.ignore-option-title { color: var(--el-text-color-primary); font-weight: var(--app-font-weight-section); }
.ignore-option-note { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); line-height: var(--app-line-height-comfy); }
:deep(.row-done) { opacity: 0.55; }
.checkup-head { display: flex; align-items: center; gap: var(--app-space-3); flex-wrap: wrap; margin-bottom: 16px; }
.checkup-score { font-size: var(--app-font-size-section-title); font-weight: var(--app-font-weight-section); }
.checkup-note { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); flex-basis: 100%; }
.checkup-group { margin-bottom: 14px; }
.checkup-group-title { font-weight: var(--app-font-weight-section); font-size: var(--app-font-size-table); color: var(--el-text-color-secondary); margin-bottom: 6px; }
.checkup-row { display: flex; align-items: center; gap: var(--app-space-2); padding: 4px 0; font-size: var(--app-font-size-table); }
.checkup-row.bad { color: var(--el-color-danger); }
.checkup-flag { width: 48px; text-align: center; flex-shrink: 0; }
.checkup-name { flex-shrink: 0; }
.checkup-detail { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); margin-left: auto; }
.checkup-row.bad .checkup-detail { color: var(--el-color-danger); }
</style>

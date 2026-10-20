<script setup lang="ts">
import AppFormHelp from '@/components/AppFormHelp.vue'
import { appendTaskLogs, taskLogMessage } from './taskLogs'
import IntradayTaskScopeFields from '@/components/data/IntradayTaskScopeFields.vue'
import { buildIntradayIngestParams, createIntradayIngestForm, type IntradayIngestForm } from '@/utils/intradayIngest'

import AppSelect from '@/components/AppSelect.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import {
  getUpdateLogs, listTasks, createTask, getTask, getTaskLogs, resumeTask, cancelTask, searchBoards,
  TASK_LABEL, STATUS_LABEL, taskDisplayLabel, SOURCE_LABEL,
  type AsyncTask, type TaskType, type TaskStatus, type TaskLogLine, type UpdateLog,
  type BoardIngestStage, type BoardTypeScope,
} from '@/api/data'
import AppDataTable from '@/components/AppDataTable.vue'
import AppDialog from '@/components/AppDialog.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTabToolbar from '@/components/AppTabToolbar.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import BoardTaskScopeFields from '@/components/data/BoardTaskScopeFields.vue'
import ResultMaintenanceTaskFields from '@/components/data/ResultMaintenanceTaskFields.vue'
import StockIngestScopeFields from '@/components/data/StockIngestScopeFields.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useLegacyPageSettingsMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useTableSort } from '@/composables/useTableSort'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getErrorMessage } from '@/utils/error'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import type { AppRowAction } from '@/components/rowActions'
import {
  STOCK_INGEST_RECIPE_LABEL,
  buildStockIngestParams,
  createStockIngestForm,
  type StockIngestFormValue,
  type StockIngestRecipe,
} from '@/utils/stockIngest'
import {
  buildResultMaintenanceTaskParams,
  consumeResultMaintenanceScheduleIntent,
  createResultMaintenanceTaskForm,
  isResultMaintenanceTask,
  queueResultMaintenanceScheduleIntent,
  type ResultMaintenanceTaskForm,
  type ResultMaintenanceTaskType,
} from '@/utils/resultMaintenanceTask'

const route = useRoute()
const router = useRouter()
const settingsOpen = ref(false)
const ingestDefaults = {
  taskStatus: 'active' as 'all' | 'active' | 'failed',
  logStatus: 'all' as 'all' | 'failed',
}
const {
  settings, isDirty, reset, save: savePageSettings,
  whenHydrated: whenPageSettingsHydrated, legacySnapshot,
} = usePageSettings('data-ingest', ingestDefaults, { deferUnknownFieldCleanup: true })

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const ingestLayout = getPageLayout('data-ingest')
const {
  effective: ingestEffective,
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
  whenRemoteHydrated, saveRemoteUserConfig, remoteSaveError,
} = useRemoteLayoutConfig(ingestLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }
useLegacyPageSettingsMigration({
  pageKey: 'data-ingest',
  componentSourceOf, setComponentKnob, whenRemoteHydrated,
  whenPageSettingsHydrated, legacySnapshot, savePageSettings,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value,
  legacyComponentMappings: [{
    legacyField: 'autoScroll',
    slotId: 'taskLogDrawer',
    componentField: 'autoScroll',
  }],
})
type IngestWorkspaceTab = 'tasks' | 'logs'
const workspaceTabDefault = computed<IngestWorkspaceTab>(() => (
  componentValueOf('workspace', 'defaultActive') === 'logs' ? 'logs' : 'tasks'
))
const activeWorkspaceTab = useDefaultedSessionValue(workspaceTabDefault)
const loading = ref(false)

// ── 任务中心：服务端分页 / 排序 / 筛选（M2.9.5）──
const tasks = ref<AsyncTask[]>([])
const taskError = ref('')
const taskLoading = ref(true)
const taskTotal = ref(0)
const taskPage = ref(1)
const { pageSize: taskSize, changePageSize: changeTaskPageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('taskTable', 'pageSize'),
  resetPage: () => {
    taskPage.value = 1
  },
  reload: loadTasks,
})
const defaultTaskStatus = computed(() => (
  settings.taskStatus === 'active' ? 'running' : settings.taskStatus === 'failed' ? 'failed' : ''
))
const taskFilter = ref<{ status: string; task_type: string }>({
  status: defaultTaskStatus.value,
  task_type: '',
})
const hasTaskFilters = computed(() => (
  taskFilter.value.status !== defaultTaskStatus.value || taskFilter.value.task_type !== ''
))
const TASK_SORT_FIELDS = ['time', 'type', 'status'] as const
const {
  sortBy: taskSortBy,
  sortOrder: taskSortOrder,
  elementDefaultSort: taskDefaultSort,
  onSortChange: onTaskSort,
} = useTableSort<(typeof TASK_SORT_FIELDS)[number]>({
  slotId: 'taskTable',
  defaultSort: 'time:desc',
  componentValueOf,
  allowedFields: TASK_SORT_FIELDS,
  onChanged: () => {
    taskPage.value = 1
    void loadTasks()
  },
})

// ── 采集日志：服务端分页 / 排序 / 筛选（M2.9.5）──
const updateLogList = ref<UpdateLog[]>([])
const logError = ref('')
const logLoading = ref(true)
const logTotal = ref(0)
const logPage = ref(1)
const { pageSize: logSize, changePageSize: changeLogPageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('logTable', 'pageSize'),
  resetPage: () => {
    logPage.value = 1
  },
  reload: loadLogs,
})
const logTables = ref<string[]>([])
const defaultLogStatus = computed(() => settings.logStatus === 'failed' ? 'failed' : '')
const logFilter = ref<{ status: string; table_name: string }>({
  status: defaultLogStatus.value,
  table_name: '',
})
const hasLogFilters = computed(() => (
  logFilter.value.status !== defaultLogStatus.value || logFilter.value.table_name !== ''
))
const LOG_SORT_FIELDS = ['time', 'table', 'status'] as const
const {
  sortBy: logSortBy,
  sortOrder: logSortOrder,
  elementDefaultSort: logDefaultSort,
  onSortChange: onLogSort,
} = useTableSort<(typeof LOG_SORT_FIELDS)[number]>({
  slotId: 'logTable',
  defaultSort: 'time:desc',
  componentValueOf,
  allowedFields: LOG_SORT_FIELDS,
  onChanged: () => {
    logPage.value = 1
    void loadLogs()
  },
})
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
const TASK_TYPE_OPTIONS: { v: TaskType; l: string }[] = [
  'stock_ingest', 'intraday_ingest', 'update', 'backfill', 'ingest_date', 'ingest_codes', 'rebuild_price_factors',
  'recompute', 'verify', 'checkup', 'fix', 'enrich_basic', 'board', 'stock_board_correlation',
  'limit_ladder_invalidate', 'limit_ladder_recompute', 'stock_special_trading_day',
].map((v) => ({ v: v as TaskType, l: TASK_LABEL[v as TaskType] }))
const TASK_STATUS_OPTIONS: { v: TaskStatus; l: string }[] = (
  ['pending', 'running', 'done', 'failed', 'interrupted'] as TaskStatus[]).map((v) => ({ v, l: STATUS_LABEL[v] }))

const statusType: Record<TaskStatus, 'success' | 'danger' | 'info' | 'warning'> = {
  done: 'success', failed: 'danger', running: 'warning', pending: 'info', interrupted: 'danger',
}
function isCancellingTask(t: AsyncTask | null | undefined): boolean {
  return !!t && t.status === 'running' && Boolean(t.cancel_requested_at)
}
const PHASE_LABEL: Record<string, string> = {
  daily_bar: '行情采集',
  valuation_latest: '最新日市值补采',
  share_capital_history: '逐日股本补采',
  valuation_history: '历史市值补采',
  valuation_gap: '市值缺口回补',
  price_factor: '价格因子',
  fix_issue: '问题修复',
  board_dict: '板块字典',
  board_members: '板块成分',
  board_bar: '板块指数',
  board_fund_flow: '板块资金流',
  delisted_history: '退市股历史',
  st_status: 'ST 状态',
  stock_basic: '基础资料',
  read_candidates: '读取候选',
  load_prices: '加载行情',
  calculate: '批量计算',
  validate: '结果校验',
  switch: '原子切换',
  limit_ladder: '连板天梯快照',
}
function taskPhaseText(t: AsyncTask): string {
  const cap = t.capability
  const phase = cap?.current_phase
  const item = cap?.current_item
  const phaseText = phase ? (PHASE_LABEL[phase] ?? phase) : ''
  // 实时计数：phase_done/phase_total 随每只处理逐只更新（来自 checkpoint），
  // 串行慢任务也能在列表/日志抽屉看到进展在动，不必等进度条按批刷新。
  const cp = cap?.checkpoint
  const done = cp?.phase_done
  const total = cp?.phase_total
  const count = (typeof done === 'number' && typeof total === 'number' && total > 0) ? `${done}/${total}` : ''
  return [phaseText, count, item ? String(item) : ''].filter(Boolean).join(' · ')
}
function canCancelTask(t: AsyncTask): boolean {
  return (t.status === 'pending' || t.status === 'running') && Boolean(t.capability?.can_cancel)
}
function canResumeTask(t: AsyncTask): boolean {
  if (!t.capability?.can_resume) return false
  if (t.status === 'interrupted') return true
  return t.status === 'failed' && Boolean(t.capability?.checkpoint)
}
function taskStatusLabel(t: AsyncTask): string {
  return isCancellingTask(t) ? '终止中' : (STATUS_LABEL[t.status as TaskStatus] ?? t.status)
}
function taskStatusType(t: AsyncTask): 'success' | 'danger' | 'info' | 'warning' {
  return isCancellingTask(t) ? 'warning' : (statusType[t.status as TaskStatus] ?? 'info')
}
const updateLogType: Record<string, 'success' | 'danger' | 'info' | 'warning'> = {
  success: 'success', failed: 'danger', partial: 'warning',
}
function logRowClass({ row }: { row: { status: string } }): string {
  return row.status === 'failed' ? 'row-fail' : row.status === 'partial' ? 'row-partial' : ''
}
const writeRunning = computed(() =>
  tasks.value.some((t) => ['pending', 'running'].includes(t.status)
    && ['update', 'backfill', 'ingest_date', 'ingest_codes', 'rebuild_price_factors',
      'verify', 'fix', 'enrich_basic', 'board', 'stock_ingest', 'intraday_ingest',
      'stock_board_correlation', 'limit_ladder_invalidate', 'limit_ladder_recompute',
      'stock_special_trading_day'].includes(t.task_type)))

// 总耗时：进行中=开始到现在(随 now 每秒刷新)；已结束/人工终止=开始到截止时间(updated_at)。
const now = ref(Date.now())
let nowTimer: number | undefined
function startNowTimer() {
  if (nowTimer) return
  nowTimer = window.setInterval(() => { now.value = Date.now() }, 1000)
}
function stopNowTimer() {
  if (!nowTimer) return
  window.clearInterval(nowTimer)
  nowTimer = undefined
}
function taskDuration(t: AsyncTask): string {
  if (!t.created_at) return '—'
  const start = Date.parse(t.created_at.slice(0, 19).replace(' ', 'T'))
  if (Number.isNaN(start)) return '—'
  const live = t.status === 'running' || t.status === 'pending'
  const end = live
    ? now.value
    : (t.updated_at ? Date.parse(t.updated_at.slice(0, 19).replace(' ', 'T')) : now.value)
  let s = Math.max(0, Math.floor((end - start) / 1000))
  const h = Math.floor(s / 3600); s -= h * 3600
  const m = Math.floor(s / 60); const sec = s - m * 60
  return h ? `${h}h${m}m${sec}s` : m ? `${m}m${sec}s` : `${sec}s`
}

// ── 采集执行对话框 ──
const optDlg = ref(false)
const optSubmitting = ref(false)
const optType = ref<'stock_ingest' | 'board' | 'intraday_ingest'>('stock_ingest')
type OptionForm = {
  codes: string[]
  mode: 'backfill' | 'update'
  board_type: BoardTypeScope
  board_stages: BoardIngestStage[]
  force_members: boolean
  board_force_current_day: boolean
  board_date_start: string
  board_date_end: string
  stock: StockIngestFormValue
  intraday: IntradayIngestForm
}
const defaultOptionForm = (): OptionForm => ({
  codes: [], mode: 'update', board_type: '', board_stages: ['dict', 'members', 'bar', 'fund'],
  force_members: false, board_force_current_day: false,
  board_date_start: '', board_date_end: '', stock: createStockIngestForm(), intraday: createIntradayIngestForm(),
})
const optForm = ref<OptionForm>(defaultOptionForm())

// 结果维护与任务调度复用同一份字段组件和参数构造器，避免两个入口口径分叉。
const resultDlg = ref(false)
const resultSubmitting = ref(false)
const resultType = ref<ResultMaintenanceTaskType>('stock_board_correlation')
const resultForm = ref<ResultMaintenanceTaskForm>(createResultMaintenanceTaskForm())

function openResultMaintenance(type: ResultMaintenanceTaskType, tradeDate = '') {
  resultType.value = type
  resultForm.value = createResultMaintenanceTaskForm(
    tradeDate ? { target_mode: 'fixed', trade_date: tradeDate } : {},
  )
  resultDlg.value = true
}

async function submitResultMaintenance() {
  if (resultSubmitting.value) return
  const built = buildResultMaintenanceTaskParams(resultType.value, resultForm.value)
  if (built.error) { ElMessage.warning(built.error); return }
  resultSubmitting.value = true
  try {
    if (await submit(resultType.value, built.params)) resultDlg.value = false
  } finally {
    resultSubmitting.value = false
  }
}

async function configureResultSchedule(type: ResultMaintenanceTaskType) {
  queueResultMaintenanceScheduleIntent(type)
  try {
    await router.push('/data/schedule')
  } finally {
    // 导航被守卫拦截时清掉意图，避免用户以后正常进入调度页却误弹新建窗口。
    if (route.path !== '/data/schedule') consumeResultMaintenanceScheduleIntent()
  }
}

// 指定板块下拉：个股搜索由共享 StockIngestScopeFields 承担，采集页/调度页口径一致。
const codeOptions = ref<{ code: string; label: string }[]>([])
const codeOptLoading = ref(false)
async function remoteCode(q: string) {
  if (!q) { codeOptions.value = []; return }
  codeOptLoading.value = true
  try {
    const r = await searchBoards({ keyword: q, size: 30 })
    codeOptions.value = r.list.map((x) => ({ code: x.code, label: `${x.code} ${x.name}` }))
  } finally {
    codeOptLoading.value = false
  }
}

function openIngestExecution(type: 'stock_ingest' | 'board' | 'intraday_ingest') {
  optType.value = type
  optForm.value = defaultOptionForm()
  codeOptions.value = []
  optDlg.value = true
}

function hasExecutionQuery(q: typeof route.query): boolean {
  return q.task_type === 'board'
    || isResultMaintenanceTask(String(q.task_type || ''))
    || (q.task_type === 'stock_ingest' && typeof q.recipe === 'string')
    || (typeof q.code === 'string' && !!q.code)
}

// 从概览/质量页带 ?code=&start=&end= 跳来 → 预填「指定日期采集」对话框（重采该股缺口区间）
function openFromQuery() {
  const q = route.query
  const queryTaskType = typeof q.task_type === 'string' ? q.task_type : ''
  if (isResultMaintenanceTask(queryTaskType)) {
    const tradeDate = typeof q.trade_date === 'string' ? q.trade_date : ''
    openResultMaintenance(queryTaskType, tradeDate)
    return
  }
  if (q.task_type === 'board') {
    optType.value = 'board'
    optForm.value = defaultOptionForm()
    optForm.value.mode = q.mode === 'backfill' ? 'backfill' : 'update'
    codeOptions.value = []
    optDlg.value = true
    return
  }
  const requestedRecipe = typeof q.recipe === 'string'
    && Object.prototype.hasOwnProperty.call(STOCK_INGEST_RECIPE_LABEL, q.recipe)
    ? q.recipe as StockIngestRecipe
    : null
  if (queryTaskType === 'stock_ingest' && requestedRecipe) {
    const code = typeof q.code === 'string' ? q.code : ''
    const start = typeof q.start === 'string' ? q.start : ''
    const end = typeof q.end === 'string' ? q.end : start
    optType.value = 'stock_ingest'
    optForm.value = defaultOptionForm()
    optForm.value.stock = createStockIngestForm({
      recipe: requestedRecipe,
      scope: code ? 'selected' : 'all',
      codes: code ? [code] : [],
      date_start: start,
      date_end: end,
    })
    optDlg.value = true
    return
  }
  const code = typeof q.code === 'string' ? q.code : ''
  if (!code) return
  const start = typeof q.start === 'string' ? q.start : ''
  const end = typeof q.end === 'string' ? q.end : start
  const recipe = q.recipe === 'daily_update' ? 'daily_update' : 'range_refetch'
  optType.value = 'stock_ingest'
  optForm.value = defaultOptionForm()
  optForm.value.stock = createStockIngestForm({
    recipe, scope: 'selected', codes: [code],
    date_start: start, date_end: end,
  })
  optDlg.value = true
  if (start) ElMessage.info(`已带入 ${code} 的待补区间 ${start}~${end}，点「执行」即重采`)
}

async function submitOptions() {
  if (optSubmitting.value) return
  const f = optForm.value
  const params: Record<string, unknown> = {}
  if (optType.value === 'stock_ingest') {
    const built = buildStockIngestParams(f.stock)
    if (built.error) { ElMessage.warning(built.error); return }
    Object.assign(params, built.params)
  } else if (optType.value === 'intraday_ingest') {
    const built = buildIntradayIngestParams(f.intraday)
    if (built.error) { ElMessage.warning(built.error); return }
    Object.assign(params, built.params)
  } else {
    if (f.codes.length) params.codes = f.codes
    if (!f.board_stages.length) { ElMessage.warning('请至少选择一项板块采集内容'); return }
    params.mode = f.mode
    params.only = f.board_stages
    if (f.board_type) params.board_type = f.board_type
    if (f.force_members && f.board_stages.includes('members')) params.force_members = true
    if (f.board_date_end && !f.board_date_start) {
      ElMessage.warning('指定指数结束日期时必须同时指定开始日期'); return
    }
    if (f.board_date_start && f.board_date_end && f.board_date_start > f.board_date_end) {
      ElMessage.warning('指数开始日期不能晚于结束日期'); return
    }
    if (f.board_date_start && f.board_force_current_day) {
      ElMessage.warning('指定指数区间不能与强制采集当日同时使用'); return
    }
    if (f.mode === 'update' && f.board_stages.includes('bar') && f.board_date_start) {
      params.date_start = f.board_date_start
      params.date_end = f.board_date_end || f.board_date_start
    }
    if (
      f.mode === 'update'
      && f.board_force_current_day
      && (f.board_stages.includes('bar') || f.board_stages.includes('fund'))
    ) params.force_current_day = true
  }
  optSubmitting.value = true
  try {
    if (await submit(optType.value, params)) optDlg.value = false
  } finally {
    optSubmitting.value = false
  }
}

// ── 提交任务 ──
async function submit(type: TaskType, params?: Record<string, unknown>): Promise<boolean> {
  try {
    const { task_id } = await createTask(type, params)
    ElMessage.success(`已提交：${TASK_LABEL[type]}`)
    await refreshTasks()
    openLogs(task_id)
    return true
  } catch (e) {
    /* 409 等错误由 http 拦截器已弹出提示 */
    return false
  }
}

let taskTimer: number | undefined
const taskListRequest = createLatestRequestGuard()
const ingestLogRequest = createLatestRequestGuard()
function activeCount() {
  return tasks.value.filter((t) => t.status === 'pending' || t.status === 'running').length
}
async function loadTasks(silent = false) {
  const requestId = taskListRequest.begin()
  const before = activeCount()
  if (!silent) taskLoading.value = true
  if (!silent) taskError.value = ''
  try {
    const r = await listTasks({
      page: taskPage.value, size: taskSize.value,
      status: taskFilter.value.status || undefined, task_type: taskFilter.value.task_type || undefined,
      sort: taskSortBy.value, order: taskSortOrder.value,
    })
    if (!taskListRequest.isCurrent(requestId)) return
    tasks.value = r.tasks
    taskTotal.value = r.total ?? r.tasks.length
  } catch (error) {
    if (!taskListRequest.isCurrent(requestId)) return
    // 自动轮询失败不把仍可使用的旧任务列表切成整区 error；用户主动请求仍由四态接管。
    if (!silent) taskError.value = getErrorMessage(error, '任务中心加载失败')
  } finally {
    if (taskListRequest.isCurrent(requestId)) taskLoading.value = false
  }
  const after = activeCount()
  if (before > 0 && after === 0) {
    await loadLogs(true)
  }
  if (taskTimer) { clearTimeout(taskTimer); taskTimer = undefined }
  // 自动轮询只更新任务数据，不反复触发表格 loading 遮罩，避免页面每两秒闪烁。
  if (pageActive && after > 0) {
    taskTimer = window.setTimeout(() => { void loadTasks(true) }, 2000)
  }
}
const refreshTasks = loadTasks   // 兼容旧调用名
async function loadLogs(silent = false) {
  const requestId = ingestLogRequest.begin()
  if (!silent) logLoading.value = true
  else logLoading.value = false
  if (!silent) logError.value = ''
  try {
    const r = await getUpdateLogs({
      page: logPage.value, size: logSize.value,
      status: logFilter.value.status || undefined, table_name: logFilter.value.table_name || undefined,
      sort: logSortBy.value, order: logSortOrder.value,
    })
    if (!ingestLogRequest.isCurrent(requestId)) return
    updateLogList.value = r.list
    logTotal.value = r.total
    if (r.tables?.length) logTables.value = r.tables
  } catch (error) {
    if (!ingestLogRequest.isCurrent(requestId)) return
    if (!silent) logError.value = getErrorMessage(error, '采集日志加载失败')
  } finally {
    if (!silent && ingestLogRequest.isCurrent(requestId)) logLoading.value = false
  }
}
async function load() {
  loading.value = true
  try {
    await Promise.all([loadTasks(), loadLogs()])
  } finally {
    loading.value = false
  }
}

async function resetTaskFilters(): Promise<void> {
  if (!hasTaskFilters.value) return
  taskFilter.value = { status: defaultTaskStatus.value, task_type: '' }
  taskPage.value = 1
  await loadTasks()
}

async function resetLogFilters(): Promise<void> {
  if (!hasLogFilters.value) return
  logFilter.value = { status: defaultLogStatus.value, table_name: '' }
  logPage.value = 1
  await loadLogs()
}

// ── 中断后继续 / 失败后重试未完成项 ──
async function resume(t: AsyncTask) {
  try {
    await resumeTask(t.id)
    ElMessage.success(t.status === 'failed' ? '已重新开始，将跳过已完成部分' : '任务已继续')
    await refreshTasks()
    openLogs(t.id)
  } catch { /* 拦截器弹错 */ }
}

// ── 终止（协作式：到下一只股票/下一步停下，可续跑）──
async function cancel(t: AsyncTask) {
  const tip = t.capability?.cancel_message || '会在下一个安全检查点停止'
  const preservation = t.task_type === 'stock_board_correlation'
    ? '终止后不会保存本次未切换结果，重新执行会从头开始。'
    : t.capability?.can_resume
      ? '终止后已完成的部分会保留。'
      : '该任务不支持续跑，终止后需重新创建任务。'
  try {
    await ElMessageBox.confirm(`${preservation}${tip}。确认终止该任务？`,
                               '终止任务', { type: 'warning' })
  } catch { return }
  try {
    await cancelTask(t.id)
    ElMessage.success('已请求终止，到下一个检查点会停下')
    await refreshTasks()
  } catch { /* 拦截器弹错 */ }
}

// ── 实时日志抽屉 ──
const logDrawer = ref(false)
const logTask = ref<AsyncTask | null>(null)
const logs = ref<TaskLogLine[]>([])
const logTaskFinished = computed(() => {
  const status = logTask.value?.status
  return status === 'done' || status === 'failed' || status === 'interrupted'
})
const correlationResult = computed<Record<string, any> | null>(() => {
  if (!logTaskFinished.value || logTask.value?.task_type !== 'stock_board_correlation') return null
  return logTask.value.result && typeof logTask.value.result === 'object'
    ? logTask.value.result
    : null
})
const ladderResult = computed<Record<string, any> | null>(() => {
  if (!logTaskFinished.value || logTask.value?.task_type !== 'limit_ladder_recompute') return null
  const result = logTask.value.result && typeof logTask.value.result === 'object'
    ? logTask.value.result
    : {}
  return {
    ...result,
    trade_date: result.trade_date || logTask.value.params?.trade_date,
    snapshot_status: result.snapshot_status || STATUS_LABEL[logTask.value.status],
  }
})
function correlationWriteStatus(): string {
  if (!correlationResult.value) return '—'
  if (logTask.value?.status === 'failed' || Number(correlationResult.value.failed_count) > 0) {
    return '未切换（失败）'
  }
  return correlationResult.value.switched ? '已原子切换' : '安全跳过'
}
function correlationBenchmarkText(): string {
  const counts = correlationResult.value?.benchmark_counts
  if (!counts || typeof counts !== 'object') return '—'
  const items = Object.entries(counts)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([code, count]) => `${code} ${count}`)
  return items.join(' · ') || '—'
}
// autoScroll 单向：抽屉默认值 → 会话 ref；日志抽屉复选框改动只进会话态，不写回默认。
const autoScroll = useDefaultedSessionValue(computed(() => (
  componentValueOf('taskLogDrawer', 'autoScroll') !== false
)))
function applyTaskPrefs(status = defaultTaskStatus.value) {
  taskFilter.value.status = status
  taskPage.value = 1
  // 远端偏好可能在首屏任务已返回后才完成 hydration；此时重新套用默认筛选属于后台刷新，
  // 不应把已经可读的任务表重新盖上 loading。首次尚无数据时仍保留完整加载态。
  void loadTasks(tasks.value.length > 0)
}
function applyLogPrefs(status = defaultLogStatus.value) {
  logFilter.value.status = status
  logPage.value = 1
  loadLogs(updateLogList.value.length > 0)
}
useDefaultedSessionValue(defaultTaskStatus, { onSynced: applyTaskPrefs })
useDefaultedSessionValue(defaultLogStatus, { onSynced: applyLogPrefs })
const logBody = ref<InstanceType<typeof AppScrollArea> | null>(null)
let logTimer: number | undefined
let lastSeq = 0

async function openLogs(id: string) {
  logDrawer.value = true
  logs.value = []
  lastSeq = 0
  logTask.value = await getTask(id).catch(() => null)
  pollLogs(id)
}

function taskRowActions(row: AsyncTask): AppRowAction[] {
  return [
    {
      key: 'waiting',
      label: '等待检查点',
      type: 'warning',
      visible: isCancellingTask(row),
      disabled: true,
      tooltip: taskPhaseText(row) || row.message || undefined,
    },
    {
      key: 'cancel',
      label: '终止',
      type: 'danger',
      visible: !isCancellingTask(row) && canCancelTask(row),
      onClick: () => cancel(row),
    },
    {
      key: 'resume',
      label: row.status === 'failed' ? '重试未完成项' : '继续任务',
      type: 'warning',
      visible: canResumeTask(row),
      onClick: () => resume(row),
    },
    { key: 'logs', label: '日志', type: 'primary', onClick: () => openLogs(row.id) },
  ]
}

function pollLogs(id: string) {
  if (logTimer) clearTimeout(logTimer)
  logTimer = undefined
  if (!pageActive || !logDrawer.value) return
  const tick = async () => {
    if (!pageActive || !logDrawer.value) return
    try {
      logTask.value = await getTask(id)
      const { logs: lines } = await getTaskLogs(id, lastSeq)
      if (lines.length) {
        logs.value = appendTaskLogs(logs.value, lines)
        lastSeq = lines[lines.length - 1].seq
        if (autoScroll.value) requestAnimationFrame(() => {
          if (logBody.value?.viewport) logBody.value.viewport.scrollTop = logBody.value.viewport.scrollHeight
        })
      }
      const st = logTask.value?.status
      if (st === 'done' || st === 'failed' || st === 'interrupted') {
        await loadTasks(true)
        if (st === 'done') await loadLogs(true)
        return
      }
    } catch { /* 下一拍重试 */ }
    if (pageActive && logDrawer.value) logTimer = window.setTimeout(tick, 1200)
  }
  tick()
}

function closeLogs() {
  logDrawer.value = false
  if (logTimer) clearTimeout(logTimer)
  logTimer = undefined
}

async function goToDataResult(path: '/data/overview' | '/data/quality') {
  closeLogs()
  await router.push(path)
}

let pageActive = false
let pageInitialized = false
function stopBackgroundWork() {
  pageActive = false
  if (logTimer) clearTimeout(logTimer)
  if (taskTimer) clearTimeout(taskTimer)
  logTimer = undefined
  taskTimer = undefined
  stopNowTimer()
}

onActivated(() => {
  pageActive = true
  startNowTimer()
  if (!pageInitialized) return
  void loadTasks()
  if (logDrawer.value && logTask.value) pollLogs(logTask.value.id)
})
onDeactivated(stopBackgroundWork)
onUnmounted(stopBackgroundWork)
onMounted(async () => {
  pageActive = true
  startNowTimer()
  await load()
  if (hasExecutionQuery(route.query)) {
    openFromQuery()
    await router.replace({ query: {} }).catch(() => {})
  }
  pageInitialized = true
})

// 概览「补采中」/质量页缺口跳转会改 route.query；keep-alive 缓存下二次跳转不重挂载，
// 须 watch query 变化重新消费参数弹采集框（onMounted 仅覆盖首次冷打开）。
// 消费后清理 query：避免参数残留，用户关闭弹框再切页回来重复弹框。
watch(
  () => route.query,
  (q) => {
    // keep-alive 下本页的 watch 在切到任务调度后仍存活，只消费属于数据采集页的参数，
    // 避免“配置调度”跳转时在后台误开手动执行弹窗，返回后才突然显示。
    if (!pageInitialized || route.path !== '/data/ingest') return
    // 仅当 query 实际带本次跳转参数时弹框；避免页面内其他 query 变化误弹
    if (hasExecutionQuery(q)) {
      openFromQuery()
      router.replace({ query: {} }).catch(() => {})
    }
  },
)
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="ingestEffective">
    <template #action>
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        {{ menuPageTitle }}
        <HelpTip title="这页能做什么？" :width="420">
          <HelpTipItem question="手动任务怎么执行">
            <ul>
              <li>数据采集、补数和结果维护在后台异步执行；可离开页面，之后回到任务中心查看实时日志。</li>
              <li>采集不会自动刷新走势、天梯或榜单；是否联动由你在「任务调度」中配置。</li>
            </ul>
          </HelpTipItem>
          <HelpTipItem question="定时任务在哪里看">
            <ul>
              <li>定时任务的执行也会进入任务中心，标注「定时·任务名」，并可查看每一步日志。</li>
            </ul>
          </HelpTipItem>
        </HelpTip>
      </h2>
      <p class="page-subtitle">手动触发数据采集与结果维护；自动执行时间和依赖关系由任务调度配置。</p>
      </div>
      <div class="page-head-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #body>
      <div class="ingest-top">
      <!-- 采集区 -->
      <el-card shadow="never" class="blk">
        <template #header>
          <div class="blk-head"><span>数据采集</span>
            <span class="app-caption-text">采集对象＝数据资产表中的：日线行情 / 分钟分时 / 市值指标 / 指数 / 交易日历 / 概念与行业板块。同类采集任务不可并发。</span></div>
        </template>
        <div class="act-grid">
          <div class="act">
            <div class="act-t">个股采集</div>
            <div class="act-d">日常同步 / 历史行情 / 区间重采 / 市值 / 基础资料 / 退市股历史</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small" :disabled="writeRunning"
                       data-testid="manual-stock-ingest"
                       @click="openIngestExecution('stock_ingest')">手动执行</el-button>
          </div>
          <div class="act">
            <div class="act-t">分时采集</div>
            <div class="act-d">已收盘1分钟分时 / 近期补采 / 区间重采 / 长期归档</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small"
                       :disabled="writeRunning" data-testid="manual-intraday-ingest"
                       @click="openIngestExecution('intraday_ingest')">手动执行</el-button>
          </div>
          <div class="act">
            <div class="act-t">板块采集</div>
            <div class="act-d">板块字典 / 成分 / 指数 / 资金流，可选增量或全量回填</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small" :disabled="writeRunning"
                       data-testid="manual-board-ingest"
                       @click="openIngestExecution('board')">手动执行</el-button>
          </div>
        </div>
      </el-card>

      <!-- 结果维护区 -->
      <el-card shadow="never" class="blk">
        <template #header><div class="blk-head"><span>结果维护</span>
          <span class="app-caption-text">立即执行与调度配置相互独立；自动执行参数和触发时机在任务调度保存。</span></div></template>
        <div class="act-grid">
          <div class="act">
            <div class="act-t">走势相关重算</div>
            <div class="act-d">强制重算股票与行业、概念板块的走势相关结果，并原子发布</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small"
                       data-testid="manual-stock-board-correlation"
                       @click="openResultMaintenance('stock_board_correlation')">手动执行</el-button>
            <el-button v-permission="'data-schedule:manage'" text size="small"
                       @click="configureResultSchedule('stock_board_correlation')">配置调度</el-button>
          </div>
          <div class="act">
            <div class="act-t">连板天梯失效</div>
            <div class="act-d">只标记指定日期起的快照失效；访问对应日期时再重算</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small"
                       data-testid="manual-limit-ladder-invalidate"
                       @click="openResultMaintenance('limit_ladder_invalidate')">手动执行</el-button>
            <el-button v-permission="'data-schedule:manage'" text size="small"
                       @click="configureResultSchedule('limit_ladder_invalidate')">配置调度</el-button>
          </div>
          <div class="act">
            <div class="act-t">每日榜单失效</div>
            <div class="act-d">只标记评分快照失效；下次读取对应榜单时按需重算</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small"
                       data-testid="manual-score-snapshot-invalidate"
                       @click="openResultMaintenance('recompute')">手动执行</el-button>
            <el-button v-permission="'data-schedule:manage'" text size="small"
                       @click="configureResultSchedule('recompute')">配置调度</el-button>
          </div>
        </div>
      </el-card>
      </div>
    </template>

    <template #workspace>
      <div class="ingest-bottom">
      <el-card shadow="never" class="app-workspace-card" data-testid="ingest-workspace">
        <el-tabs v-model="activeWorkspaceTab" class="app-workspace-tabs" data-testid="ingest-workspace-tabs">
          <el-tab-pane label="任务中心" name="tasks">
            <div class="app-workspace-panel">
          <AppTabToolbar label="任务中心操作栏" data-testid="ingest-tasks-toolbar">
            <template #actions>
              <AppSelect
                v-model="taskFilter.task_type"
                data-testid="task-type-filter"
                placeholder="类型"
                clearable
                size="small"
                @change="() => { taskPage = 1; loadTasks() }"
                width="medium"
              >
                <el-option v-for="o in TASK_TYPE_OPTIONS" :key="o.v" :label="o.l" :value="o.v" />
              </AppSelect>
              <AppSelect
                v-model="taskFilter.status"
                data-testid="task-status-filter"
                placeholder="状态"
                clearable
                size="small"
                @change="() => { taskPage = 1; loadTasks() }"
                width="short"
              >
                <el-option v-for="o in TASK_STATUS_OPTIONS" :key="o.v" :label="o.l" :value="o.v" />
              </AppSelect>
              <el-button data-testid="task-reset-filters" size="small" :disabled="!hasTaskFilters" @click="resetTaskFilters">重置筛选</el-button>
            </template>
            <template #description>筛选变更后自动刷新；点击任务行查看运行日志</template>
          </AppTabToolbar>
        <div class="panel-table-wrap" data-testid="task-center-panel">
          <AppStateBlock
            v-if="taskLoading && !tasks.length"
            state="loading"
            title="正在加载任务中心…"
          />
          <AppStateBlock
            v-else-if="taskError"
            state="error"
            :title="tasks.length ? '任务中心刷新失败' : '任务中心加载失败'"
            :description="taskError"
            retry
            @retry="loadTasks"
          />
          <AppDataTable
            v-else
            :data="tasks"
            :loading="taskLoading"
            row-key="id"
            size="small"
            :border="tableBorder('taskTable')"
            :default-sort="taskDefaultSort"
            table-class="clk-tbl"
            clickable
            :pagination="{ currentPage: taskPage, pageSize: taskSize, total: taskTotal, pageSizes: PAGE_SIZE_OPTIONS }"
            @row-click="(r: AsyncTask) => openLogs(r.id)"
            @sort-change="onTaskSort"
            @page-change="(p: number) => { taskPage = p; loadTasks() }"
            @size-change="changeTaskPageSize"
          >
            <AppTableColumn label="任务ID">
              <template #default="{ row }"><span class="task-id">{{ row.id }}</span></template>
            </AppTableColumn>
            <AppTableColumn label="类型" prop="type" sortable="custom">
              <template #default="{ row }">
                {{ taskDisplayLabel(row.task_type, row.params) }}
              </template>
            </AppTableColumn>
            <AppTableColumn label="来源">
              <template #default="{ row }">
                <el-tag v-if="row.trigger_source === 'scheduled'" type="warning" size="small" effect="plain">
                  定时{{ row.job_name ? `·${row.job_name}` : '' }}
                </el-tag>
                <el-tag v-else-if="row.trigger_source === 'dependency'" type="primary" size="small" effect="plain">
                  依赖{{ row.job_name ? `·${row.job_name}` : '' }}
                </el-tag>
                <el-tag v-else-if="row.trigger_source === 'retry'" type="danger" size="small" effect="plain">
                  重试{{ row.job_name ? `·${row.job_name}` : '' }}{{ row.retry_count ? ` #${row.retry_count}` : '' }}
                </el-tag>
                <el-tag v-else-if="row.trigger_source === 'system'" type="primary" size="small" effect="plain">
                  系统{{ row.job_name ? `·${row.job_name}` : '' }}
                </el-tag>
                <el-tag v-else size="small" effect="plain" type="info">
                  {{ row.job_name ? `手动·${row.job_name}` : '手动' }}
                </el-tag>
              </template>
            </AppTableColumn>
            <AppTableColumn label="状态" prop="status" sortable="custom">
              <template #default="{ row }">
                <el-tag :type="taskStatusType(row)" size="small" effect="dark">
                  {{ taskStatusLabel(row) }}
                </el-tag>
              </template>
            </AppTableColumn>
            <AppTableColumn label="进度">
              <template #default="{ row }">
                <el-progress :percentage="Math.round((row.progress ?? 0) * 100)" :stroke-width="10"
                  :status="row.status === 'failed' || row.status === 'interrupted' ? 'exception' : row.status === 'done' ? 'success' : undefined" />
              </template>
            </AppTableColumn>
            <AppTableColumn label="信息" prop="message" role="description" single-line />
            <AppTableColumn label="截止时间" prop="time" sortable="custom">
              <template #default="{ row }">{{ formatDateTimeSeconds(row.updated_at, '') }}</template>
            </AppTableColumn>
            <AppTableColumn label="总耗时">
              <template #default="{ row }">{{ taskDuration(row) }}</template>
            </AppTableColumn>
            <AppTableColumn label="操作" role="action">
              <template #default="{ row }">
                <AppRowActions :actions="taskRowActions(row)" :inline-limit="2" />
              </template>
            </AppTableColumn>
          </AppDataTable>
        </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="采集日志" name="logs" lazy>
            <div class="app-workspace-panel" data-testid="ingest-log-panel">
          <AppTabToolbar label="采集日志操作栏" data-testid="ingest-logs-toolbar">
            <template #actions>
              <AppSelect
                v-model="logFilter.table_name"
                placeholder="目标表"
                clearable
                size="small"
                @change="() => { logPage = 1; loadLogs() }"
                width="short"
              >
                <el-option v-for="t in logTables" :key="t" :label="t" :value="t" />
              </AppSelect>
              <AppSelect
                v-model="logFilter.status"
                placeholder="结果"
                clearable
                size="small"
                @change="() => { logPage = 1; loadLogs() }"
                width="compact"
              >
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
                <el-option label="部分" value="partial" />
                <el-option label="已复查" value="checked" />
              </AppSelect>
              <el-button data-testid="log-reset-filters" size="small" :disabled="!hasLogFilters" @click="resetLogFilters">重置筛选</el-button>
            </template>
            <template #description>失败行可见原因；逐股明细见任务中心「日志」</template>
          </AppTabToolbar>
        <div class="panel-table-wrap">
          <AppStateBlock
            v-if="logLoading && !updateLogList.length"
            state="loading"
            title="正在加载采集日志…"
          />
          <AppStateBlock
            v-else-if="logError"
            state="error"
            :title="updateLogList.length ? '采集日志刷新失败' : '采集日志加载失败'"
            :description="logError"
            retry
            @retry="loadLogs"
          />
          <AppDataTable
            v-else
            :data="updateLogList"
            :loading="logLoading"
            size="small"
            :border="tableBorder('logTable')"
            :default-sort="logDefaultSort"
            :row-class-name="logRowClass"
            :pagination="{ currentPage: logPage, pageSize: logSize, total: logTotal, pageSizes: PAGE_SIZE_OPTIONS }"
            @sort-change="onLogSort"
            @page-change="(p: number) => { logPage = p; loadLogs() }"
            @size-change="changeLogPageSize"
          >
            <AppTableColumn label="目标表" prop="table" sortable="custom">
              <template #default="{ row }">{{ row.table_name }}</template>
            </AppTableColumn>
            <AppTableColumn label="数据源">
              <template #default="{ row }">{{ (SOURCE_LABEL as Record<string, string>)[row.source] ?? row.source }}</template>
            </AppTableColumn>
            <AppTableColumn label="结果" prop="status" sortable="custom">
              <template #default="{ row }">
                <el-tag :type="updateLogType[row.status] ?? 'info'" size="small" effect="plain">
                  {{ row.status === 'success' ? '成功' : row.status === 'failed' ? '失败' : row.status === 'partial' ? '部分' : row.status === 'checked' ? '已复查' : row.status }}
                </el-tag>
              </template>
            </AppTableColumn>
            <AppTableColumn label="行数" prop="row_count" role="number" />
            <AppTableColumn label="区间">
              <template #default="{ row }">{{ row.date_start ? `${row.date_start} ~ ${row.date_end || row.date_start}` : '—' }}</template>
            </AppTableColumn>
            <AppTableColumn label="详情 / 失败原因" single-line>
              <template #default="{ row }">
                <span :class="{ 'fail-detail': row.status === 'failed', 'partial-detail': row.status === 'partial' }">{{ row.detail || (row.status === 'success' ? '—' : '') }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn label="时间" prop="time" sortable="custom">
              <template #default="{ row }">{{ formatDateTimeSeconds(row.updated_at, '') }}</template>
            </AppTableColumn>
          </AppDataTable>
        </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-card>
      </div>
    </template>

    <template #overlays>
    <!-- 采集执行对话框 -->
    <AppDialog
      v-model="optDlg"
      :title="TASK_LABEL[optType]"
      size="large"
      align-center
      :close-on-click-modal="!optSubmitting"
      :close-on-press-escape="!optSubmitting"
      :show-close="!optSubmitting"
      data-testid="ingest-options-dialog"
    >
      <el-form label-width="92px">
        <IntradayTaskScopeFields
          v-if="optType === 'intraday_ingest'"
          v-model="optForm.intraday"
          test-id-prefix="ingest-intraday"
        />
        <StockIngestScopeFields
          v-if="optType === 'stock_ingest'"
          v-model="optForm.stock"
          test-id-prefix="ingest-stock"
        />
        <BoardTaskScopeFields
          v-if="optType === 'board'"
          v-model:mode="optForm.mode"
          v-model:board-type="optForm.board_type"
          v-model:stages="optForm.board_stages"
          v-model:force-members="optForm.force_members"
          v-model:force-current-day="optForm.board_force_current_day"
          v-model:date-start="optForm.board_date_start"
          v-model:date-end="optForm.board_date_end"
          allow-date-range
          test-id-prefix="ingest-board"
        />
        <el-form-item v-if="optType === 'board'" label="指定板块">
          <AppSelect
            v-model="optForm.codes"
            multiple
            filterable
            remote
            clearable
            collapse-tags
            :remote-method="remoteCode"
            :loading="codeOptLoading"
            :reserve-keyword="false"
            placeholder="输入板块代码或名称搜索"
            width="fill"
          >
            <el-option v-for="o in codeOptions" :key="o.code" :label="o.label" :value="o.code" />
          </AppSelect>
          <AppFormHelp>可多选；留空=全部板块</AppFormHelp>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="optSubmitting" @click="optDlg = false">取消</el-button>
        <el-button
          v-permission="'data-task:manage'"
          type="primary"
          :loading="optSubmitting"
          data-testid="ingest-execute-submit"
          @click="submitOptions"
        >按以上参数执行</el-button>
      </template>
    </AppDialog>

    <AppDialog
      v-model="resultDlg"
      :title="TASK_LABEL[resultType]"
      size="large"
      align-center
      :close-on-click-modal="!resultSubmitting"
      :close-on-press-escape="!resultSubmitting"
      :show-close="!resultSubmitting"
      data-testid="result-maintenance-dialog"
    >
      <el-form label-width="92px">
        <ResultMaintenanceTaskFields
          v-model="resultForm"
          :task-type="resultType"
          test-id-prefix="manual-result"
        />
      </el-form>
      <template #footer>
        <el-button :disabled="resultSubmitting" @click="resultDlg = false">取消</el-button>
        <el-button
          v-permission="'data-task:manage'"
          type="primary"
          :loading="resultSubmitting"
          data-testid="result-maintenance-execute-submit"
          @click="submitResultMaintenance"
        >
          按以上参数执行
        </el-button>
      </template>
    </AppDialog>

    <!-- 实时日志抽屉 -->
    <PageDrawer
      v-model="logDrawer"
      :title="logTask ? `${taskDisplayLabel(logTask.task_type, logTask.params)} · 实时日志` : '实时日志'"
      size="wide"
      :body-scroll="false"
      body-layout="fill"
      data-testid="task-log-drawer"
      @close="closeLogs"
    >
      <div v-if="logTask" class="log-meta">
        <el-tag :type="taskStatusType(logTask)" size="small" effect="dark">{{ taskStatusLabel(logTask) }}</el-tag>
        <span class="lm-msg">{{ logTask.message }}</span>
        <span v-if="taskPhaseText(logTask)" class="lm-phase">{{ taskPhaseText(logTask) }}</span>
        <el-progress :percentage="Math.round((logTask.progress ?? 0) * 100)" :stroke-width="8" style="flex:1" />
        <el-checkbox v-model="autoScroll" size="small">自动滚动</el-checkbox>
      </div>
      <div v-if="logTaskFinished" class="log-followups">
        <span>任务结果可继续在数据页核验</span>
        <el-button link type="primary" @click="goToDataResult('/data/overview')">查看数据概览</el-button>
        <el-button link type="primary" @click="goToDataResult('/data/quality')">查看数据质量</el-button>
      </div>
      <AppDetailFields
        v-if="correlationResult"
        :columns="3"
        class="correlation-task-result"
        data-testid="correlation-task-result"
      >
        <AppDetailField label="目标日期" :value="correlationResult.target_date" />
        <AppDetailField label="目标股票" :value="correlationResult.target_stock_count ?? 0" />
        <AppDetailField label="候选关系" :value="correlationResult.candidate_relation_count ?? 0" />
        <AppDetailField label="行业冠军" :value="correlationResult.industry_champion_count ?? 0" />
        <AppDetailField label="概念冠军" :value="correlationResult.concept_champion_count ?? 0" />
        <AppDetailField label="空结果" :value="correlationResult.empty_result_count ?? 0" />
        <AppDetailField label="回退上证" :value="correlationResult.fallback_count ?? 0" />
        <AppDetailField label="跳过股票" :value="correlationResult.skipped_count ?? 0" />
        <AppDetailField label="失败数" :value="correlationResult.failed_count ?? 0" />
        <AppDetailField label="计算耗时" :value="`${correlationResult.calculation_seconds ?? 0} 秒`" />
        <AppDetailField label="写入耗时" :value="`${correlationResult.write_seconds ?? 0} 秒`" />
        <AppDetailField label="基准分布" :value="correlationBenchmarkText()" />
        <AppDetailField label="写入状态" :value="correlationWriteStatus()" />
      </AppDetailFields>
      <AppDetailFields
        v-if="ladderResult"
        :columns="3"
        class="correlation-task-result"
        data-testid="limit-ladder-task-result"
      >
        <AppDetailField label="交易日" :value="ladderResult.trade_date" />
        <AppDetailField label="快照状态" :value="ladderResult.snapshot_status" />
        <AppDetailField label="快照 ID" :value="ladderResult.snapshot_id" mono />
        <AppDetailField label="股票池" :value="ladderResult.coverage?.pool_count ?? 0" />
        <AppDetailField label="有效行情" :value="ladderResult.coverage?.valid_bar_count ?? 0" />
        <AppDetailField label="确认停牌" :value="ladderResult.coverage?.confirmed_suspension_count ?? 0" />
        <AppDetailField label="缺失" :value="ladderResult.coverage?.missing_count ?? 0" />
        <AppDetailField label="非法行情" :value="ladderResult.coverage?.invalid_bar_count ?? 0" />
        <AppDetailField label="未知规则" :value="ladderResult.coverage?.unsupported_rule_count ?? 0" />
        <AppDetailField label="采集终态" :value="ladderResult.coverage?.ingest_terminal_status" />
      </AppDetailFields>
      <AppScrollArea ref="logBody" class="log-body">
        <div v-for="l in logs" :key="l.seq" class="log-line" :class="l.level">
          <span class="lt">{{ (l.ts || '').slice(11, 19) }}</span>
          <span class="lm">{{ taskLogMessage(l.message) }}</span>
        </div>
        <div v-if="!logs.length" class="app-empty-inline">暂无日志…</div>
      </AppScrollArea>
    </PageDrawer>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="数据采集"
      :dirty="isDirty || layoutDirty"
      page-key="data-ingest"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection section-key="task-center" title="任务中心">
          <PageSettingItem label="默认任务筛选">
            <PageSegmented v-model="settings.taskStatus" aria-label="默认任务筛选"
                           test-id="task-status-default" :options="[
              { label: '全部', value: 'all' },
              { label: '运行中', value: 'active' },
              { label: '失败项', value: 'failed' },
            ]" />
          </PageSettingItem>
        </PageSettingSection>
        <PageSettingSection section-key="collection-log" title="采集日志">
          <PageSettingItem label="采集日志筛选">
            <PageSegmented v-model="settings.logStatus" aria-label="采集日志筛选" :options="[
              { label: '全部', value: 'all' },
              { label: '仅失败', value: 'failed' },
            ]" />
          </PageSettingItem>
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; }
/* 顶部操作卡固定，底部成长工作区以 Tab 切换两张表。 */
.ingest-top {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}
.ingest-bottom {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.panel-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.blk { margin-bottom: 16px; }
.blk-head { display: flex; justify-content: space-between; align-items: center; gap: var(--app-space-3); }
.flt { display: flex; align-items: center; gap: var(--app-space-2); }
.act-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--app-space-3); }
.act { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 12px 14px; }
.act-t { font-weight: var(--app-font-weight-section); }
.act-d { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin: 4px 0 10px; }
.task-id { font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.log-meta { flex: 0 0 auto; display: flex; align-items: center; gap: var(--app-space-2); margin-bottom: 10px; }
.log-followups { flex: 0 0 auto; display: flex; align-items: center; justify-content: flex-end; gap: var(--app-space-2); margin: -2px 0 10px; font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.correlation-task-result { flex: 0 0 auto; margin-bottom: var(--app-space-3); }
.lm-msg { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lm-phase { font-size: var(--app-font-size-caption); color: var(--el-color-warning); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-body { flex: 1 1 auto; min-height: 0; background: var(--el-fill-color-darker); border-radius: 6px; --app-scroll-padding-top: 10px; --app-scroll-padding-right: 10px; --app-scroll-padding-bottom: 10px; --app-scroll-padding-left: 10px; font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); }
.log-line { display: flex; gap: var(--app-space-2); padding: 1px 0; }
.log-line.warn { color: var(--app-warning-text); }
.log-line.error { color: var(--app-danger-text); }
.lt { color: var(--el-text-color-secondary); flex-shrink: 0; }
:deep(.row-fail) { background: var(--el-color-danger-light-9); }
:deep(.row-partial) { background: var(--el-color-warning-light-9); }
.fail-detail { color: var(--app-danger-text); }
.partial-detail { color: var(--app-warning-text); }
</style>

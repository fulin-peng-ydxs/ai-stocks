<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import { computed, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  listSchedules, createSchedule, updateSchedule, setScheduleEnabled, deleteSchedule, runSchedule,
  listScheduleTriggerEvents,
  getSources, testSources, SOURCE_LABEL, TASK_LABEL, ISSUE_TYPE_LABEL, ISSUE_TYPES_ACTIVE,
  taskDisplayLabel, getSettingsView, saveSettings, resetSettings,
  type ScheduledJob, type ScheduledJobInput, type ScheduledTriggerEvent,
  type SourceStatus, type TaskStatus, type TaskType, type FreqType, type TriggerMode,
  type TriggerCondition,
  type DelayUnit,
  type BoardIngestStage, type BoardTypeScope,
} from '@/api/data'
import AppRowActions from '@/components/AppRowActions.vue'
import type { AppRowAction } from '@/components/rowActions'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useTableSort } from '@/composables/useTableSort'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getErrorMessage } from '@/utils/error'
import { compareScheduleFrequency } from '@/utils/scheduleFrequencySort'
import BoardTaskScopeFields from '@/components/data/BoardTaskScopeFields.vue'
import StockIngestScopeFields from '@/components/data/StockIngestScopeFields.vue'
import ResultMaintenanceTaskFields from '@/components/data/ResultMaintenanceTaskFields.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import {
  buildStockIngestParams,
  createStockIngestForm,
  isHeavyStockIngestRecipe,
  stockIngestFormFromTask,
  type StockIngestFormValue,
} from '@/utils/stockIngest'
import {
  buildResultMaintenanceTaskParams,
  consumeResultMaintenanceScheduleIntent,
  createResultMaintenanceTaskForm,
  isResultMaintenanceTask,
  resultMaintenanceTaskFormFromParams,
  type ResultMaintenanceTaskForm,
} from '@/utils/resultMaintenanceTask'

const router = useRouter()
const settingsOpen = ref(false)
const scheduleDefaults = { sourceMode: 'all' as 'all' | 'primary', timeMode: 'full' as 'full' | 'hm' }
const { settings, isDirty, reset } = usePageSettings('data-schedule', scheduleDefaults)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const scheduleLayout = getPageLayout('data-schedule')
const {
  effective: scheduleEffective,
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
} = useRemoteLayoutConfig(scheduleLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }

// 表格列显隐/边框消费（对齐 QualityView 模式）：字段由 pageRegistry.componentMeta.columns 提供候选
const jobHiddenColumns = computed<string[]>(() => (componentValueOf('jobTable', 'hiddenColumns') as string[]) ?? [])
const sourceHiddenColumns = computed<string[]>(() => (componentValueOf('sourceTable', 'hiddenColumns') as string[]) ?? [])
function jobColVisible(key: string): boolean { return !jobHiddenColumns.value.includes(key) }
function sourceColVisible(key: string): boolean { return !sourceHiddenColumns.value.includes(key) }
function tableBorder(slotId: string): boolean { return componentValueOf(slotId, 'border') === true }

// 列头排序（单向默认机制）：任务列表全量在前端，排序走本地 computed，不回源。
const JOB_SORT_FIELDS = ['name', 'freq'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof JOB_SORT_FIELDS)[number]>({
  slotId: 'jobTable',
  defaultSort: 'name:asc',
  componentValueOf,
  allowedFields: JOB_SORT_FIELDS,
  defaultOrder: 'asc',
})
// 频率按真实配置排序（每日时间、每周星期与时间、每月日期与时间、cron 表达式）。
const sortedJobs = computed(() => {
  const factor = sortOrder.value === 'desc' ? -1 : 1
  const byName = (a: ScheduledJob, b: ScheduledJob) => a.name.localeCompare(b.name, 'zh')
  return [...jobs.value].sort((a, b) => {
    const primary = sortBy.value === 'freq' ? compareScheduleFrequency(a, b) : byName(a, b)
    return (primary || byName(a, b)) * factor
  })
})

const loading = ref(true)
const loadError = ref('')
const jobs = ref<ScheduledJob[]>([])
const taskTypes = ref<TaskType[]>([])
const qualityIssueTypes = ref<string[]>([...ISSUE_TYPES_ACTIVE])
const togglingId = ref('')

const sources = ref<SourceStatus[]>([])
const pinging = ref(false)
const sourceLoading = ref(true)
const sourceError = ref('')
const displaySources = computed(() => settings.sourceMode === 'primary' ? sources.value.filter((s) => s.role === 'primary') : sources.value)
function sourceRoleLabel(role: string): string {
  if (role === 'primary') return '主源'
  if (role === 'board') return '板块源'
  return '备用源'
}
function boardSourceRowActions(): AppRowAction[] {
  return [{
    key: 'cookie',
    label: '授权配置',
    permission: 'data-settings:manage',
    testId: 'ths-login-cookie-btn',
    onClick: () => openCookieConfig(),
  }]
}

const FREQ_OPTIONS: { label: string; value: FreqType }[] = [
  { label: '每日', value: 'daily' }, { label: '每周', value: 'weekly' },
  { label: '每月', value: 'monthly' }, { label: '高级(cron)', value: 'cron' },
]
const TRIGGER_MODE_OPTIONS: { label: string; value: TriggerMode }[] = [
  { label: '按时间', value: 'time' }, { label: '按任务依赖', value: 'dependency' },
]
const CONDITION_OPTIONS: { label: string; value: TriggerCondition }[] = [
  { label: '成功后', value: 'success' }, { label: '失败后', value: 'failure' },
  { label: '完成后', value: 'completion' },
]
const DELAY_UNIT_OPTIONS: { label: string; value: DelayUnit }[] = [
  { label: '秒', value: 'second' }, { label: '分钟', value: 'minute' }, { label: '小时', value: 'hour' },
]
const WEEKDAYS = [
  { label: '一', value: 1 }, { label: '二', value: 2 }, { label: '三', value: 3 },
  { label: '四', value: 4 }, { label: '五', value: 5 }, { label: '六', value: 6 }, { label: '日', value: 7 },
]
// 新建调度只展示统一个股采集；历史原子任务仅保留展示、执行与编辑转换兼容。
function taskTypeOptions() {
  const legacyStockTypes = new Set<TaskType>(['update', 'backfill', 'ingest_date', 'ingest_codes'])
  // 对滚动更新期的旧列表响应容错：页面的统一入口始终可选，保存仍由服务端二次校验。
  return Array.from(new Set<TaskType>(['stock_ingest', ...taskTypes.value]))
    .filter((value) => !legacyStockTypes.has(value))
    .map((v) => ({ value: v, label: TASK_LABEL[v] ?? v }))
}

function fmtTime(value?: string | null): string {
  const text = (value || '—').slice(0, 19)
  if (text === '—') return text
  return settings.timeMode === 'hm' ? text.slice(11, 16) : text
}

// ── 新建/编辑对话框 ──
const dlg = ref(false)
const editingId = ref('')
const saving = ref(false)
const form = reactive({
  name: '', task_type: 'stock_ingest' as TaskType,
  stock: createStockIngestForm() as StockIngestFormValue,
  resultMaintenance: createResultMaintenanceTaskForm() as ResultMaintenanceTaskForm,
  issue_type: 'null_close',
  board_mode: 'update' as 'update' | 'backfill',
  board_type: '' as BoardTypeScope,
  board_stages: ['dict', 'members', 'bar', 'fund'] as BoardIngestStage[],
  board_force_members: false,
  board_force_current_day: false,
  freq_type: 'daily' as FreqType,
  time: '15:30', weekdays: [1, 2, 3, 4, 5] as number[], day: 1, cron: '',
  trigger_mode: 'time' as TriggerMode,
  dependency_job_id: '', dependency_condition: 'completion' as TriggerCondition,
  dependency_delay_value: 0, dependency_delay_unit: 'minute' as DelayUnit,
  retry_enabled: false, retry_condition: 'failure' as TriggerCondition,
  retry_delay_value: 5, retry_delay_unit: 'minute' as DelayUnit, max_retries: 1,
  trading_day_only: true, enabled: true,
})
const dlgTitle = computed(() => (editingId.value ? '编辑调度任务' : '新建调度任务'))
const dependencyOptions = computed(() => jobs.value.filter((job) => job.id !== editingId.value))
// 采集类任务（逐股拉取）才有并发概念；结果维护/质检无需并发。
watch(() => form.task_type, (type, prev) => {
  if (type === 'audit_cleanup') form.trading_day_only = false
  else if (prev === 'audit_cleanup' && !editingId.value) form.trading_day_only = true
})

function changeTaskType(type: TaskType) {
  if (isResultMaintenanceTask(type)) {
    form.resultMaintenance = createResultMaintenanceTaskForm()
  }
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, {
    name: '', task_type: 'stock_ingest', stock: createStockIngestForm(),
    resultMaintenance: createResultMaintenanceTaskForm(),
    issue_type: qualityIssueTypes.value[0] || 'null_close',
    board_mode: 'update', board_type: '', board_stages: ['dict', 'members', 'bar', 'fund'],
    board_force_members: false, board_force_current_day: false,
    freq_type: 'daily', time: '15:30', weekdays: [1, 2, 3, 4, 5], day: 1, cron: '',
    trigger_mode: 'time', dependency_job_id: '', dependency_condition: 'completion',
    dependency_delay_value: 0, dependency_delay_unit: 'minute',
    retry_enabled: false, retry_condition: 'failure', retry_delay_value: 5,
    retry_delay_unit: 'minute', max_retries: 1,
    trading_day_only: true, enabled: true,
  })
  dlg.value = true
}

function openResultScheduleFromIntent() {
  const queryTaskType = consumeResultMaintenanceScheduleIntent()
  if (!queryTaskType) return
  openCreate()
  form.task_type = queryTaskType
}

function openEdit(j: ScheduledJob) {
  editingId.value = j.id
  const stock = stockIngestFormFromTask(j.task_type, j.params)
  Object.assign(form, {
    name: j.name, task_type: stock ? 'stock_ingest' : j.task_type,
    stock: stock || createStockIngestForm(),
    resultMaintenance: isResultMaintenanceTask(j.task_type)
      ? resultMaintenanceTaskFormFromParams(j.task_type, j.params)
      : createResultMaintenanceTaskForm(),
    issue_type: j.params?.issue_type || qualityIssueTypes.value[0] || 'null_close',
    board_mode: j.params?.mode === 'backfill' ? 'backfill' : 'update',
    board_type: j.params?.board_type === 'concept' || j.params?.board_type === 'industry'
      ? j.params.board_type : '',
    board_stages: Array.isArray(j.params?.only) && j.params.only.length
      ? j.params.only.filter((x): x is BoardIngestStage => ['dict', 'members', 'bar', 'fund'].includes(x))
      : ['dict', 'members', 'bar', 'fund'],
    board_force_members: j.params?.force_members === true,
    board_force_current_day: j.params?.force_current_day === true,
    freq_type: j.freq_type,
    time: j.freq_config?.time || '15:30',
    weekdays: j.freq_config?.weekdays?.length ? [...j.freq_config.weekdays] : [1, 2, 3, 4, 5],
    day: j.freq_config?.day ?? 1,
    cron: j.freq_config?.cron || '',
    trigger_mode: j.trigger_mode || 'time', dependency_job_id: j.dependency_job_id || '',
    dependency_condition: j.dependency_condition || 'completion',
    dependency_delay_value: j.dependency_delay?.value ?? 0,
    dependency_delay_unit: j.dependency_delay?.unit || 'minute',
    retry_enabled: j.retry_config?.enabled === true,
    retry_condition: j.retry_config?.condition || 'failure',
    retry_delay_value: j.retry_config?.delay?.value ?? 5,
    retry_delay_unit: j.retry_config?.delay?.unit || 'minute',
    max_retries: j.retry_config?.max_retries ?? 1,
    trading_day_only: j.trading_day_only, enabled: j.enabled,
  })
  dlg.value = true
}

function buildPayload(): ScheduledJobInput | null {
  if (!form.name.trim()) { ElMessage.warning('请填写任务名称'); return null }
  const params: Record<string, unknown> = {}
  if (form.task_type === 'stock_ingest') {
    const built = buildStockIngestParams(form.stock)
    if (built.error) { ElMessage.warning(built.error); return null }
    Object.assign(params, built.params)
  } else if (isResultMaintenanceTask(form.task_type)) {
    const built = buildResultMaintenanceTaskParams(form.task_type, form.resultMaintenance)
    if (built.error) { ElMessage.warning(built.error); return null }
    Object.assign(params, built.params)
  } else if (form.task_type === 'fix') {
    if (!form.issue_type) { ElMessage.warning('质检问题恢复需选择问题类型'); return null }
    params.issue_type = form.issue_type
  } else if (form.task_type === 'board') {
    if (!form.board_stages.length) { ElMessage.warning('请至少选择一项板块采集内容'); return null }
    params.mode = form.board_mode
    params.only = form.board_stages
    if (form.board_type) params.board_type = form.board_type
    if (form.board_force_members && form.board_stages.includes('members')) params.force_members = true
    if (
      form.board_mode === 'update'
      && form.board_force_current_day
      && (form.board_stages.includes('bar') || form.board_stages.includes('fund'))
    ) params.force_current_day = true
  }
  if (form.trigger_mode === 'dependency' && !form.dependency_job_id) {
    ElMessage.warning('请选择上游任务'); return null
  }
  const fc: Record<string, unknown> = {}
  if (form.trigger_mode === 'time' && form.freq_type === 'daily') fc.time = form.time
  else if (form.trigger_mode === 'time' && form.freq_type === 'weekly') {
    if (!form.weekdays.length) { ElMessage.warning('每周任务请至少选一个星期'); return null }
    fc.weekdays = [...form.weekdays].sort((a, b) => a - b); fc.time = form.time
  } else if (form.trigger_mode === 'time' && form.freq_type === 'monthly') { fc.day = form.day; fc.time = form.time }
  else if (form.trigger_mode === 'time' && form.freq_type === 'cron') {
    if (!form.cron.trim()) { ElMessage.warning('请填写 cron 表达式'); return null }
    fc.cron = form.cron.trim()
  }
  return {
    name: form.name.trim(), task_type: form.task_type, params,
    freq_type: form.freq_type, freq_config: fc,
    trigger_mode: form.trigger_mode,
    dependency_job_id: form.trigger_mode === 'dependency' ? form.dependency_job_id : null,
    dependency_condition: form.trigger_mode === 'dependency' ? form.dependency_condition : null,
    dependency_delay: {
      value: form.dependency_delay_value, unit: form.dependency_delay_unit,
    },
    retry_config: {
      enabled: form.retry_enabled, condition: form.retry_condition,
      delay: { value: form.retry_delay_value, unit: form.retry_delay_unit },
      max_retries: form.max_retries,
    },
    trading_day_only: form.trading_day_only, enabled: form.enabled,
  }
}

async function save() {
  const payload = buildPayload()
  if (!payload) return
  if (form.task_type === 'stock_ingest' && isHeavyStockIngestRecipe(form.stock.recipe)) {
    try {
      await ElMessageBox.confirm(
        '该采集方案耗时较长，周期触发可能与其他 DuckDB 写任务冲突。确认保存调度任务？',
        '重任务调度确认',
        { type: 'warning' },
      )
    } catch { return }
  }
  saving.value = true
  try {
    if (editingId.value) { await updateSchedule(editingId.value, payload); ElMessage.success('调度任务已更新') }
    else { await createSchedule(payload); ElMessage.success('调度任务已创建') }
    dlg.value = false
    await load()
  } catch { /* 拦截器弹错 */ } finally { saving.value = false }
}

async function toggleEnabled(j: ScheduledJob) {
  if (j.enabled && j.waiting_trigger_count > 0) {
    try {
      await ElMessageBox.confirm(
        `停用后会取消当前 ${j.waiting_trigger_count} 条等待或触发中的事件，重新启用不会自动恢复。确认停用「${j.name}」？`,
        '停用调度任务',
        { type: 'warning', confirmButtonText: '确认停用' },
      )
    } catch { return }
  }
  togglingId.value = j.id
  try {
    await setScheduleEnabled(j.id, !j.enabled)
    await load()
  } catch { /* 拦截器弹错 */ } finally { togglingId.value = '' }
}

async function remove(j: ScheduledJob) {
  try {
    await ElMessageBox.confirm(`确认删除调度任务「${j.name}」？删除后不再自动触发。`, '删除调度任务', { type: 'warning' })
  } catch { return }
  try { await deleteSchedule(j.id); ElMessage.success('已删除'); await load() } catch { /* */ }
}

async function runNow(j: ScheduledJob) {
  try {
    await ElMessageBox.confirm(
      `立即执行一次「${j.name}」（${taskDisplayLabel(j.task_type, j.params)}）？`
      + '将直接创建任务，不等待定时点，并按当前任务参数执行。',
      '立即执行', { type: 'warning' })
  } catch { return }
  try {
    await runSchedule(j.id)
    ElMessage.success('已触发，前往任务中心查看实时日志')
    router.push('/data/ingest')
  } catch { /* 409 等由拦截器弹出 */ }
}

const eventDrawer = ref(false)
const eventJob = ref<ScheduledJob | null>(null)
const triggerEvents = ref<ScheduledTriggerEvent[]>([])
const eventLoading = ref(false)
const eventError = ref('')
async function loadTriggerEvents() {
  if (!eventJob.value) return
  eventLoading.value = true
  eventError.value = ''
  try {
    triggerEvents.value = (await listScheduleTriggerEvents(eventJob.value.id)).events
  } catch (error) {
    eventError.value = getErrorMessage(error, '触发记录加载失败')
  } finally {
    eventLoading.value = false
  }
}
async function openTriggerEvents(job: ScheduledJob) {
  eventJob.value = job
  triggerEvents.value = []
  eventDrawer.value = true
  await loadTriggerEvents()
}
const CONDITION_LABEL: Record<TriggerCondition, string> = {
  success: '成功后', failure: '失败后', completion: '完成后',
}
const SOURCE_STATUS_LABEL: Partial<Record<TaskStatus, string>> = {
  done: '成功', failed: '失败', interrupted: '已终止',
}
const EVENT_STATUS_LABEL: Record<ScheduledTriggerEvent['status'], string> = {
  waiting: '等待中', dispatching: '触发中', dispatched: '已触发', cancelled: '已取消',
  exhausted: '已达上限', failed: '触发失败',
}
function eventStatusLabel(status: ScheduledTriggerEvent['status']): string {
  return EVENT_STATUS_LABEL[status] || status
}
function sourceStatusLabel(status: TaskStatus): string {
  return SOURCE_STATUS_LABEL[status] || status
}
function triggerConditionLabel(condition?: TriggerCondition | null): string {
  return condition ? CONDITION_LABEL[condition] : '—'
}
function retryText(job: ScheduledJob): string {
  const retry = job.retry_config
  if (!retry?.enabled) return '关闭'
  const unit = DELAY_UNIT_OPTIONS.find((item) => item.value === retry.delay.unit)?.label || ''
  return `${CONDITION_LABEL[retry.condition]}延迟${retry.delay.value}${unit}，最多${retry.max_retries}次`
}

function scheduleRowActions(row: ScheduledJob): AppRowAction[] {
  return [
    {
      key: 'run',
      label: '立即执行',
      type: 'primary',
      permission: 'data-schedule:manage',
      onClick: () => runNow(row),
    },
    { key: 'edit', label: '编辑', permission: 'data-schedule:manage', onClick: () => openEdit(row) },
    {
      key: 'events', label: '触发记录', permission: 'data-schedule:manage', placement: 'more',
      onClick: () => openTriggerEvents(row),
    },
    {
      key: 'delete',
      label: '删除',
      type: 'danger',
      permission: 'data-schedule:manage',
      placement: 'more',
      onClick: () => remove(row),
    },
  ]
}

async function loadSources(ping = false) {
  sourceLoading.value = true
  pinging.value = ping
  sourceError.value = ''
  try {
    sources.value = (ping ? await testSources() : await getSources(false)).sources
  } catch (error) {
    sourceError.value = getErrorMessage(error, '数据源健康加载失败')
  } finally {
    sourceLoading.value = false
    pinging.value = false
  }
}

const cookieDlg = ref(false)
const cookieSaving = ref(false)
const cookieValue = ref('')
type CookieDialogStatus = 'loading' | 'error' | 'unset' | 'usable' | 'unavailable'
const cookieStatus = ref<CookieDialogStatus>('loading')
const cookieStatusError = ref('')
let cookieStatusRequestVersion = 0
// 与系统配置页同一掩码：已设置时输入框回显「已设置」占位，明文不回显，留空/掩码即不修改。
const COOKIE_SET_MASK = '••••••已设置'
async function loadCookieStatus() {
  const version = ++cookieStatusRequestVersion
  cookieStatus.value = 'loading'
  cookieStatusError.value = ''
  try {
    const view = await getSettingsView()
    if (version !== cookieStatusRequestVersion) return
    const ths = view.groups.find((group) => group.key === 'ths_board')
    const field = ths?.fields.find((item) => item.path === 'ths_board.login_cookie')
    cookieStatus.value = field?.secret_status ?? 'unset'
    // 对齐系统配置页：usable 时输入框回显掩码，避免「已设置」被显示成空白输入框。
    cookieValue.value = cookieStatus.value === 'usable' ? COOKIE_SET_MASK : ''
  } catch (error) {
    if (version !== cookieStatusRequestVersion) return
    cookieStatus.value = 'error'
    cookieStatusError.value = getErrorMessage(error, '授权配置状态加载失败')
  }
}
function openCookieConfig() {
  cookieDlg.value = true
  cookieSaving.value = false
  cookieValue.value = ''
  void loadCookieStatus()
}
async function saveCookie() {
  const value = cookieValue.value.trim()
  if (cookieSaving.value || !value || value === COOKIE_SET_MASK) return
  cookieSaving.value = true
  try {
    await saveSettings({ 'ths_board.login_cookie': value })
    ElMessage.success('登录 Cookie 已加密保存')
    cookieDlg.value = false
    void loadSources(false)
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '保存登录 Cookie 失败'))
  } finally {
    cookieSaving.value = false
  }
}
async function clearCookie() {
  if (cookieSaving.value || !['usable', 'unavailable'].includes(cookieStatus.value)) return
  cookieSaving.value = true
  try {
    await resetSettings(['ths_board.login_cookie'])
    ElMessage.success('页面 Cookie 配置已清除')
    cookieDlg.value = false
    void loadSources(false)
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '清除登录 Cookie 失败'))
  } finally {
    cookieSaving.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const r = await listSchedules()
    jobs.value = r.jobs
    taskTypes.value = r.task_types
    qualityIssueTypes.value = r.quality_issue_types?.length
      ? r.quality_issue_types
      : [...ISSUE_TYPES_ACTIVE]
  } catch (error) {
    loadError.value = getErrorMessage(error, '调度任务加载失败')
  } finally { loading.value = false }
}

onMounted(async () => {
  await Promise.all([load(), loadSources(false)])
  openResultScheduleFromIntent()
})

// keep-alive 缓存页再次进入时不会重新执行 onMounted，激活时消费一次性新建意图。
onActivated(openResultScheduleFromIntent)
</script>

<template>
  <LayoutHost :layout="scheduleEffective">
    <template #action>
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        任务调度
        <HelpTip title="这页管什么？" :width="440">
          <HelpTipItem question="调度任务管什么">
            <ul>
              <li>可自定义数据采集、结果维护、数据质检、按问题类型恢复和审计清理任务。</li>
              <li>可选择时间或任务依赖触发，配置延迟与受控重试，也可启停或立即执行。</li>
              <li>实际执行记录进入「数据采集」任务中心，并标注「定时·任务名」。</li>
            </ul>
          </HelpTipItem>
          <HelpTipItem question="数据源健康看什么">
            <ul>
              <li>用于查看 AKShare、BaoStock 和同花顺板块源的连通性。</li>
            </ul>
          </HelpTipItem>
        </HelpTip>
      </h2>
      <p class="page-subtitle">按时间或上游任务结果编排采集、结果维护、质检、恢复与审计任务，支持延迟触发和有上限重试。</p>
      </div>
      <div class="page-head-actions">
        <el-button
          v-permission="'data-schedule:manage'"
          data-testid="schedule-create"
          type="primary"
          @click="openCreate"
        >新建调度任务</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <div class="schedule-body">
      <!-- ① 调度任务列表 -->
      <el-card shadow="never" class="blk jobs-card">
        <template #header>
          <div class="blk-head"><span>调度任务</span>
            <span class="hint">时间任务到点触发；依赖任务命中上游结果后可靠等待并按配置延迟执行。</span></div>
        </template>
        <AppStateBlock
          v-if="loading && !jobs.length"
          state="loading"
          title="正在加载调度任务…"
        />
        <AppStateBlock
          v-else-if="loadError"
          state="error"
          :title="jobs.length ? '调度任务刷新失败' : '调度任务加载失败'"
          :description="loadError"
          retry
          @retry="load"
        />
        <AppDataTable
          v-else
          :data="sortedJobs"
          size="small"
          class="jobs-tbl"
          :loading="loading"
          :border="tableBorder('jobTable')"
          :default-sort="elementDefaultSort"
          @sort-change="onSortChange"
        >
          <AppTableColumn v-if="jobColVisible('name')" label="名称" prop="name" show-overflow-tooltip sortable="custom" />
          <AppTableColumn v-if="jobColVisible('taskType')" label="任务类型">
            <template #default="{ row }">{{ taskDisplayLabel(row.task_type, row.params) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('freq')" label="触发规则" prop="freq" show-overflow-tooltip sortable="custom">
            <template #default="{ row }"><span data-testid="schedule-frequency">{{ row.trigger_text || row.freq_text }}</span></template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('tradingDay')" label="仅交易日" align="center">
            <template #default="{ row }">
              <el-tag :type="row.trading_day_only ? 'success' : 'info'" size="small" effect="plain">
                {{ row.trading_day_only ? '是' : '否' }}
              </el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('enabled')" label="启用" align="center">
            <template #default="{ row }">
              <el-switch
                v-permission="'data-schedule:manage'"
                :model-value="row.enabled"
                :loading="togglingId === row.id"
                :data-testid="`schedule-enabled-${row.id}`"
                @change="toggleEnabled(row)"
              />
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('nextRun')" label="下次触发">
            <template #default="{ row }">
              <span class="app-inline-info app-inline-info--nowrap">
                <span v-if="!row.enabled">—</span>
                <span v-else-if="row.trigger_mode === 'dependency' && !row.next_run_time">等待上游</span>
                <span v-else>{{ fmtTime(row.next_run_time) }}</span>
                <el-tag v-if="row.waiting_trigger_count" size="small" effect="plain" type="warning">
                  等待 {{ row.waiting_trigger_count }}
                </el-tag>
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('retry')" label="自身重试" show-overflow-tooltip>
            <template #default="{ row }">{{ retryText(row) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('lastRun')" label="最近触发">
            <template #default="{ row }">{{ fmtTime(row.last_run_at) }}</template>
          </AppTableColumn>
          <AppTableColumn label="操作" role="action" fixed="right">
            <template #default="{ row }">
              <AppRowActions :actions="scheduleRowActions(row)" :inline-limit="2" />
            </template>
          </AppTableColumn>
          <template #empty>暂无调度任务，点右上「新建调度任务」添加</template>
        </AppDataTable>
      </el-card>

      <!-- ② 数据源健康 -->
      <el-card shadow="never" class="blk">
        <template #header>
          <div class="blk-head"><span>数据源健康</span>
            <el-button v-permission="'data-source:test'" size="small" type="primary" plain :loading="pinging || sourceLoading" @click="loadSources(true)">测试连通</el-button></div>
        </template>
        <AppStateBlock
          v-if="sourceLoading && !displaySources.length"
          state="loading"
          title="正在加载数据源健康…"
        />
        <AppStateBlock
          v-else-if="sourceError"
          state="error"
          :title="displaySources.length ? '数据源健康刷新失败' : '数据源健康加载失败'"
          :description="sourceError"
          retry
          @retry="loadSources(false)"
        />
        <div v-else v-loading="sourceLoading">
        <AppDataTable :data="displaySources" size="small" class="srcs-tbl" embedded :border="tableBorder('sourceTable')">
          <AppTableColumn v-if="sourceColVisible('source')" label="数据源" prop="source">
            <template #default="{ row }">{{ SOURCE_LABEL[row.source] ?? row.source }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="sourceColVisible('role')" label="角色" align="center">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.role === 'primary' ? 'primary' : 'info'">
                {{ sourceRoleLabel(row.role) }}
              </el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="sourceColVisible('status')" label="状态" align="center">
            <template #default="{ row }">
              <span class="src-status">
                <span class="dot" :class="row.up === true ? 'up' : row.up === false ? 'down' : 'unknown'" />
                {{ row.up === true ? '连通' : row.up === false ? '不可达' : '未测试' }}
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="sourceColVisible('lastSuccess')" label="最近成功">
            <template #default="{ row }">{{ fmtTime(row.last_success_at) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="sourceColVisible('timeout')" label="超时">
            <template #default="{ row }">{{ row.timeout_sec }}s</template>
          </AppTableColumn>
          <AppTableColumn label="操作" role="action-compact" fixed="right">
            <template #default="{ row }">
              <AppRowActions v-if="row.source === 'ths_board'" :actions="boardSourceRowActions()" :inline-limit="1" />
            </template>
          </AppTableColumn>
          <template #empty>点「测试连通」检查行情源与板块源可达性</template>
        </AppDataTable>
        </div>
      </el-card>
    </div>
    </template>

    <template #overlays>
    <el-dialog v-model="cookieDlg" title="配置同花顺登录 Cookie" width="480px" data-testid="ths-login-cookie-dialog">
      <AppStateBlock
        v-if="cookieStatus === 'loading'"
        data-testid="ths-login-cookie-status"
        state="loading"
        size="tiny"
        title="正在确认授权配置状态"
        :skeleton-rows="2"
      />
      <AppStateBlock
        v-else-if="cookieStatus === 'error'"
        data-testid="ths-login-cookie-status"
        state="error"
        size="tiny"
        title="授权配置状态加载失败"
        :description="`${cookieStatusError}。状态确认前不会修改或清除已有配置。`"
        retry
        retry-text="重新加载"
        @retry="loadCookieStatus"
      />
      <el-form v-else label-width="92px">
        <el-form-item label="登录 Cookie">
          <el-input
            v-model="cookieValue"
            type="password"
            show-password
            autocomplete="new-password"
            readonly
            placeholder="粘贴登录后的完整 Cookie；数据库只保存加密密文"
            data-testid="ths-login-cookie-input"
            @focus="($event.target as HTMLInputElement).removeAttribute('readonly')"
          />
          <span v-if="cookieStatus === 'unavailable'" class="cookie-field-hint">
            已存密文无法解密，当前采集不会使用它；请检查主密钥，或输入新 Cookie 重新加密覆盖。
          </span>
        </el-form-item>
      </el-form>
      <p v-if="cookieStatus !== 'loading' && cookieStatus !== 'error'" class="cookie-note">
        浏览器登录同花顺后，从开发者工具 Network 复制完整 Cookie 头。
        环境变量或受控文件仍优先于页面配置；数据库只保存加密密文，明文不会回显。
      </p>
      <template #footer>
        <el-button v-if="cookieStatus === 'usable' || cookieStatus === 'unavailable'" :disabled="cookieSaving" @click="clearCookie">清除页面配置</el-button>
        <el-button @click="cookieDlg = false">取消</el-button>
        <el-button
          v-if="cookieStatus !== 'loading' && cookieStatus !== 'error'"
          type="primary"
          :loading="cookieSaving"
          :disabled="!cookieValue.trim() || cookieValue.trim() === COOKIE_SET_MASK"
          data-testid="ths-login-cookie-save"
          @click="saveCookie"
        >
          加密保存
        </el-button>
      </template>
    </el-dialog>

    <PageDrawer
      v-model="eventDrawer"
      size="xl"
      :title="eventJob ? `${eventJob.name} · 触发记录` : '触发记录'"
      class="schedule-trigger-events-drawer"
    >
      <AppStateBlock
        v-if="eventLoading && !triggerEvents.length"
        state="loading"
        title="正在加载触发记录…"
      />
      <AppStateBlock
        v-else-if="eventError"
        state="error"
        title="触发记录加载失败"
        :description="eventError"
        retry
        @retry="loadTriggerEvents"
      />
      <AppDataTable v-else :data="triggerEvents" embedded size="small">
        <AppTableColumn label="来源任务" show-overflow-tooltip>
          <template #default="{ row }">{{ row.source_job_name || row.source_task_id }}</template>
        </AppTableColumn>
        <AppTableColumn label="来源结果" align="center">
          <template #default="{ row }">{{ sourceStatusLabel(row.source_status) }}</template>
        </AppTableColumn>
        <AppTableColumn label="类型" align="center">
          <template #default="{ row }">{{ row.trigger_kind === 'retry' ? `重试 ${row.retry_count}` : '任务依赖' }}</template>
        </AppTableColumn>
        <AppTableColumn label="命中规则" align="center">
          <template #default="{ row }">{{ triggerConditionLabel(row.trigger_condition) }}</template>
        </AppTableColumn>
        <AppTableColumn label="计划时间">
          <template #default="{ row }">{{ fmtTime(row.due_at) }}</template>
        </AppTableColumn>
        <AppTableColumn label="实际触发">
          <template #default="{ row }">{{ fmtTime(row.dispatched_at) }}</template>
        </AppTableColumn>
        <AppTableColumn label="状态" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.status === 'failed' || row.status === 'exhausted' ? 'danger' : row.status === 'waiting' || row.status === 'dispatching' ? 'warning' : row.status === 'dispatched' ? 'success' : 'info'">
              {{ eventStatusLabel(row.status) }}
            </el-tag>
          </template>
        </AppTableColumn>
        <AppTableColumn label="下游任务" show-overflow-tooltip>
          <template #default="{ row }">{{ row.task_id || row.message || '—' }}</template>
        </AppTableColumn>
        <template #empty>暂无依赖或自身重试触发记录</template>
      </AppDataTable>
    </PageDrawer>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dlg" :title="dlgTitle" width="520px" data-testid="schedule-dialog">
      <el-form label-width="92px">
        <el-form-item label="任务名称">
          <el-input
            v-model="form.name"
            data-testid="schedule-name"
            placeholder="如：盘后增量更新"
            maxlength="40"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select
            v-model="form.task_type"
            data-testid="schedule-task-type"
            style="width: 100%"
            @change="changeTaskType"
          >
            <el-option v-for="o in taskTypeOptions()" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <!-- 按类型的动态参数 -->
        <el-form-item v-if="form.task_type === 'fix'" label="问题类型">
          <el-select v-model="form.issue_type" data-testid="schedule-issue-type" style="width: 100%">
            <el-option
              v-for="issueType in qualityIssueTypes"
              :key="issueType"
              :label="ISSUE_TYPE_LABEL[issueType] ?? issueType"
              :value="issueType"
            />
          </el-select>
          <span class="hint">每次触发时动态恢复该类型当前所有“未处理”问题，无问题时正常结束</span>
        </el-form-item>
        <BoardTaskScopeFields
          v-if="form.task_type === 'board'"
          v-model:mode="form.board_mode"
          v-model:board-type="form.board_type"
          v-model:stages="form.board_stages"
          v-model:force-members="form.board_force_members"
          v-model:force-current-day="form.board_force_current_day"
          test-id-prefix="schedule-board"
        />
        <StockIngestScopeFields
          v-if="form.task_type === 'stock_ingest'"
          v-model="form.stock"
          test-id-prefix="schedule-stock"
        />
        <ResultMaintenanceTaskFields
          v-if="isResultMaintenanceTask(form.task_type)"
          v-model="form.resultMaintenance"
          :task-type="form.task_type"
          test-id-prefix="schedule-result"
        />
        <el-alert
          v-if="isResultMaintenanceTask(form.task_type)"
          type="warning"
          :closable="false"
          title="保存只会登记调度，不会立即执行；以后自动触发或在调度列表点击“立即执行”时，均使用这里保存的结果参数。"
          data-testid="schedule-result-execution-scope"
        />

        <el-divider
          content-position="left"
          class="form-section-divider"
          data-testid="schedule-trigger-divider"
        >触发方式</el-divider>
        <el-form-item label="触发方式">
          <PageSegmented v-model="form.trigger_mode" :options="TRIGGER_MODE_OPTIONS" test-id="schedule-trigger-mode" aria-label="触发方式" />
        </el-form-item>
        <template v-if="form.trigger_mode === 'time'">
        <el-form-item label="频率">
          <PageSegmented v-model="form.freq_type" :options="FREQ_OPTIONS" aria-label="频率" />
        </el-form-item>
        <el-form-item v-if="form.freq_type === 'weekly'" label="星期">
          <el-checkbox-group v-model="form.weekdays">
            <el-checkbox-button v-for="w in WEEKDAYS" :key="w.value" :value="w.value">{{ w.label }}</el-checkbox-button>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item v-if="form.freq_type === 'monthly'" label="每月几号">
          <el-input-number v-model="form.day" :min="1" :max="28" />
          <span class="hint">1–28（避开月末不确定）</span>
        </el-form-item>
        <el-form-item v-if="form.freq_type === 'cron'" label="cron 表达式">
          <el-input v-model="form.cron" placeholder="分 时 日 月 周，如 30 15 * * 1-5" />
        </el-form-item>
        <el-form-item v-if="form.freq_type !== 'cron'" label="执行时间">
          <el-time-picker v-model="form.time" value-format="HH:mm" format="HH:mm" placeholder="HH:mm" :clearable="false" />
        </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="上游任务">
            <el-select
              v-model="form.dependency_job_id"
              data-testid="schedule-dependency-job"
              placeholder="选择上游任务"
              filterable
              style="width: 100%"
            >
              <el-option
                v-for="job in dependencyOptions"
                :key="job.id"
                :label="`${job.name}${job.enabled ? '' : '（已停用）'}`"
                :value="job.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="结果条件">
            <PageSegmented v-model="form.dependency_condition" :options="CONDITION_OPTIONS" test-id="schedule-dependency-condition" aria-label="依赖结果条件" />
            <span class="hint">“完成后”包含成功和失败；人工终止不会触发</span>
          </el-form-item>
          <el-form-item label="触发延迟">
            <el-input-number v-model="form.dependency_delay_value" data-testid="schedule-dependency-delay" :min="0" :precision="0" />
            <el-select v-model="form.dependency_delay_unit" data-testid="schedule-dependency-delay-unit" class="delay-unit-select">
              <el-option v-for="item in DELAY_UNIT_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </template>

        <el-divider content-position="left" class="form-section-divider">自身重试</el-divider>
        <el-form-item label="启用重试">
          <el-switch v-model="form.retry_enabled" data-testid="schedule-retry-enabled" />
          <span class="hint">本任务结果持续命中条件时循环执行，达到上限后结束</span>
        </el-form-item>
        <template v-if="form.retry_enabled">
          <el-form-item label="循环条件">
            <PageSegmented v-model="form.retry_condition" :options="CONDITION_OPTIONS" test-id="schedule-retry-condition" aria-label="循环结果条件" />
            <span v-if="form.retry_condition === 'completion'" class="hint warn-hint">
              成功和失败都会继续循环，直到达到次数上限；人工终止除外
            </span>
          </el-form-item>
          <el-form-item label="重试延迟">
            <el-input-number v-model="form.retry_delay_value" data-testid="schedule-retry-delay" :min="0" :precision="0" />
            <el-select v-model="form.retry_delay_unit" data-testid="schedule-retry-delay-unit" class="delay-unit-select">
              <el-option v-for="item in DELAY_UNIT_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="最大重试">
            <el-input-number v-model="form.max_retries" data-testid="schedule-max-retries" :min="1" :max="20" :precision="0" />
            <span class="hint">不含首次执行；最多 20 次</span>
          </el-form-item>
        </template>

        <el-divider content-position="left" class="form-section-divider">选项</el-divider>
        <el-form-item v-if="form.trigger_mode === 'time'" label="仅交易日">
          <el-switch v-model="form.trading_day_only" />
          <span class="hint">开启后非交易日自动跳过（行情/质检类建议开）</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" data-testid="schedule-enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button
          v-permission="'data-schedule:manage'"
          data-testid="schedule-save"
          type="primary"
          :loading="saving"
          @click="save"
        >保存调度</el-button>
      </template>
    </el-dialog>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="任务调度"
      :dirty="isDirty || layoutDirty"
      page-key="data-schedule"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="显示">
          <div class="setting-item">
            <div class="setting-label">时间显示</div>
            <PageSegmented v-model="settings.timeMode" aria-label="时间显示" :options="[
              { label: '完整时间', value: 'full' },
              { label: '仅时分', value: 'hm' },
            ]" />
          </div>
        </PageSettingSection>
        <PageSettingSection title="数据源视图">
          <div class="setting-item">
            <div class="setting-label">显示范围</div>
            <PageSegmented v-model="settings.sourceMode" aria-label="显示范围" :options="[
              { label: '全部源', value: 'all' },
              { label: '只主源', value: 'primary' },
            ]" />
          </div>
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; }
.page-head-actions { display: flex; gap: var(--app-space-2); align-items: center; }
/* 填满 LayoutHost 的条件成长区；放不下时整区内滚（兜底阶梯第 3 级） */
.schedule-body { flex: 1 1 auto; overflow: auto; min-height: 0; display: flex; flex-direction: column; }
.delay-unit-select { width: 96px; margin-left: var(--space-2); }
.warn-hint { color: var(--el-color-warning-dark-2); }
.jobs-card {
  flex: 1 1 auto;
  min-height: 300px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
}
.jobs-card :deep(.el-card__body) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.jobs-tbl { width: 100%; flex: 1 1 auto; min-height: 0; }
.setting-item { display: flex; flex-direction: column; gap: var(--app-space-2); }
.setting-label { font-size: var(--app-font-size-body); color: var(--page-settings-text-subtle); }
.blk { margin-bottom: 16px; }
.blk:last-child { margin-bottom: 0; }
.blk-head { display: flex; justify-content: space-between; align-items: center; }
.hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-left: 10px; }
.form-section-divider { margin: var(--app-space-4) 0 14px; }
.src-status { display: inline-flex; align-items: center; gap: var(--app-space-control-gap); }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dot.up { background: var(--el-color-success); box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-success) 18%, transparent); }
.dot.down { background: var(--app-danger-text); box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-danger-text) 18%, transparent); }
.dot.unknown { background: var(--app-placeholder-text); }
.cookie-note { margin: 10px 0 0; font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); color: var(--el-text-color-secondary); }
.cookie-field-hint { display: block; margin-top: 4px; font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); color: var(--el-text-color-secondary); }
</style>

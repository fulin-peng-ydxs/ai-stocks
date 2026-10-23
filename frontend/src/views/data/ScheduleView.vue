<script setup lang="ts">
import AppTableCard from '@/components/AppTableCard.vue'
import { enumText, businessMessage } from '@/utils/displayText'
import AppFormHelp from '@/components/AppFormHelp.vue'
import IntradayTaskScopeFields from '@/components/data/IntradayTaskScopeFields.vue'
import { buildIntradayIngestParams, createIntradayIngestForm } from '@/utils/intradayIngest'

import AppSelect from '@/components/AppSelect.vue'
import AppHoverInfo from '@/components/AppHoverInfo'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppDetailDrawer from '@/components/AppDetailDrawer.vue'
import ScheduleDownstreamDrawer from '@/components/data/ScheduleDownstreamDrawer.vue'
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  listSchedules, listScheduleOptions, createSchedule, updateSchedule, setScheduleEnabled, deleteSchedule, runSchedule,
  listScheduleTriggerEvents,
  TASK_LABEL, STATUS_LABEL, ISSUE_TYPE_LABEL, ISSUE_TYPES_ACTIVE, sortQualityIssueTypes,
  taskDisplayLabel,
  type ScheduledJob, type ScheduledJobInput, type ScheduledJobOption, type ScheduledTriggerEvent,
  type TaskStatus, type TaskType, type FreqType, type TriggerMode,
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
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useTableSort } from '@/composables/useTableSort'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getErrorMessage } from '@/utils/error'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import {
  APP_BOTTOM_FLOATING_FALLBACKS,
  APP_BOTTOM_FLOATING_PLACEMENT,
} from '@/utils/floatingPlacement'
import BoardTaskScopeFields from '@/components/data/BoardTaskScopeFields.vue'
import StockIngestScopeFields from '@/components/data/StockIngestScopeFields.vue'
import ResultMaintenanceTaskFields from '@/components/data/ResultMaintenanceTaskFields.vue'
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
const scheduleDefaults = { timeMode: 'full' as 'full' | 'hm' }
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
function jobColVisible(key: string): boolean { return !jobHiddenColumns.value.includes(key) }
function tableBorder(slotId: string): boolean { return componentValueOf(slotId, 'border') === true }

const loading = ref(true)
const loadError = ref('')
const jobs = ref<ScheduledJob[]>([])
const jobTotal = ref(0)
const jobPage = ref(1)
const scheduleListRequest = createLatestRequestGuard()
const { pageSize: jobPageSize, changePageSize: changeJobPageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('jobTable', 'pageSize'),
  fallback: DEFAULT_PAGE_SIZE,
  resetPage: () => {
    jobPage.value = 1
  },
  reload: load,
})

// 调度任务按完整结果集在服务端排序，列头和设置抽屉共享同一排序会话。
const JOB_SORT_FIELDS = ['name', 'freq'] as const
const { sortBy, sortOrder, elementDefaultSort, onSortChange } = useTableSort<(typeof JOB_SORT_FIELDS)[number]>({
  slotId: 'jobTable',
  defaultSort: 'name:asc',
  componentValueOf,
  allowedFields: JOB_SORT_FIELDS,
  defaultOrder: 'asc',
  onChanged: () => {
    jobPage.value = 1
    void load()
  },
})
const taskTypes = ref<TaskType[]>([])
const qualityIssueTypes = ref<string[]>([...ISSUE_TYPES_ACTIVE])
const togglingId = ref('')

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
    .map((v) => ({ value: v, label: enumText(TASK_LABEL, v, '未识别任务类型') }))
}

function fmtTime(value?: string | null): string {
  const text = formatDateTimeSeconds(value)
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
  intraday: createIntradayIngestForm(),
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
  dependency_job_ids: [] as string[], dependency_condition: 'completion' as TriggerCondition,
  dependency_delay_value: 0, dependency_delay_unit: 'minute' as DelayUnit,
  retry_enabled: false, retry_condition: 'failure' as TriggerCondition,
  retry_delay_value: 5, retry_delay_unit: 'minute' as DelayUnit, max_retries: 1,
  trading_day_only: true, enabled: true,
})
const dlgTitle = computed(() => (editingId.value ? '编辑调度任务' : '新建调度任务'))
const dependencyOptions = ref<ScheduledJobOption[]>([])
const dependencyOptionsLoading = ref(false)
const dependencyOptionsRequest = createLatestRequestGuard()
async function loadDependencyOptions(query = '') {
  const requestId = dependencyOptionsRequest.begin()
  dependencyOptionsLoading.value = true
  try {
    const result = await listScheduleOptions(query)
    if (!dependencyOptionsRequest.isCurrent(requestId)) return
    const selected = dependencyOptions.value.filter((item) => form.dependency_job_ids.includes(item.id))
    const next = result.list.filter((item) => item.id !== editingId.value)
    const nextIds = new Set(next.map((item) => item.id))
    dependencyOptions.value = [...selected.filter((item) => !nextIds.has(item.id)), ...next]
  } catch (error) {
    if (dependencyOptionsRequest.isCurrent(requestId)) {
      ElMessage.error(getErrorMessage(error, '上游任务候选加载失败'))
    }
  } finally {
    if (dependencyOptionsRequest.isCurrent(requestId)) dependencyOptionsLoading.value = false
  }
}
const {
  hasChanges: scheduleFormChanged,
  captureBaseline: captureScheduleBaseline,
} = useFormChangeTracker(() => ({ ...form }))
// 采集类任务（逐股拉取）才有并发概念；结果维护/质检无需并发。
watch(() => form.task_type, (type, prev) => {
  if (type === 'audit_cleanup') form.trading_day_only = false
  else if (prev === 'audit_cleanup' && !editingId.value) form.trading_day_only = true
})
watch(() => form.trigger_mode, (mode) => {
  if (mode === 'dependency' && !dependencyOptions.value.length) void loadDependencyOptions()
})

function changeTaskType(type: TaskType) {
  if (type === 'intraday_ingest' && !editingId.value) form.enabled = false
  if (isResultMaintenanceTask(type)) {
    form.resultMaintenance = createResultMaintenanceTaskForm()
  }
}

function openCreate() {
  dependencyOptionsRequest.invalidate()
  dependencyOptionsLoading.value = false
  editingId.value = ''
  Object.assign(form, {
    name: '', task_type: 'stock_ingest', stock: createStockIngestForm(), intraday: createIntradayIngestForm(),
    resultMaintenance: createResultMaintenanceTaskForm(),
    issue_type: qualityIssueTypes.value[0] || 'null_close',
    board_mode: 'update', board_type: '', board_stages: ['dict', 'members', 'bar', 'fund'],
    board_force_members: false, board_force_current_day: false,
    freq_type: 'daily', time: '15:30', weekdays: [1, 2, 3, 4, 5], day: 1, cron: '',
    trigger_mode: 'time', dependency_job_ids: [], dependency_condition: 'completion',
    dependency_delay_value: 0, dependency_delay_unit: 'minute',
    retry_enabled: false, retry_condition: 'failure', retry_delay_value: 5,
    retry_delay_unit: 'minute', max_retries: 1,
    trading_day_only: true, enabled: true,
  })
  dependencyOptions.value = []
  captureScheduleBaseline()
  dlg.value = true
}

function openResultScheduleFromIntent() {
  const queryTaskType = consumeResultMaintenanceScheduleIntent()
  if (!queryTaskType) return
  openCreate()
  form.task_type = queryTaskType
}

function openEdit(j: ScheduledJob) {
  dependencyOptionsRequest.invalidate()
  dependencyOptionsLoading.value = false
  editingId.value = j.id
  const stock = stockIngestFormFromTask(j.task_type, j.params)
  Object.assign(form, {
    name: j.name, task_type: stock ? 'stock_ingest' : j.task_type,
    stock: stock || createStockIngestForm(),
    intraday: createIntradayIngestForm(j.params),
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
    trigger_mode: j.trigger_mode || 'time',
    dependency_job_ids: [...(j.dependency_job_ids ?? (j.dependency_job_id ? [j.dependency_job_id] : []))],
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
  dependencyOptions.value = j.dependency_jobs?.length ? [...j.dependency_jobs] : j.dependency_job_id
    ? [{
        id: j.dependency_job_id,
        name: j.dependency_job_name || j.dependency_job_id,
        enabled: true,
      }]
    : []
  if (form.trigger_mode === 'dependency') void loadDependencyOptions()
  captureScheduleBaseline()
  dlg.value = true
}

function buildPayload(): ScheduledJobInput | null {
  if (!form.name.trim()) { ElMessage.warning('请填写任务名称'); return null }
  const params: Record<string, unknown> = {}
  if (form.task_type === 'stock_ingest') {
    const built = buildStockIngestParams(form.stock)
    if (built.error) { ElMessage.warning(built.error); return null }
    Object.assign(params, built.params)
  } else if (form.task_type === 'intraday_ingest') {
    const built = buildIntradayIngestParams(form.intraday)
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
  if (form.trigger_mode === 'dependency' && !form.dependency_job_ids.length) {
    ElMessage.warning('请选择上游任务'); return null
  }
  if (form.trigger_mode === 'dependency'
    && (!Number.isInteger(form.dependency_delay_value) || form.dependency_delay_value < 0)) {
    ElMessage.warning('触发延迟必须是非负整数'); return null
  }
  const fc: Record<string, unknown> = {}
  if (form.trigger_mode === 'time' && form.freq_type !== 'cron' && !form.time) {
    ElMessage.warning('请选择执行时间'); return null
  }
  if (form.trigger_mode === 'time' && form.freq_type === 'daily') fc.time = form.time
  else if (form.trigger_mode === 'time' && form.freq_type === 'weekly') {
    if (!form.weekdays.length) { ElMessage.warning('每周任务请至少选一个星期'); return null }
    fc.weekdays = [...form.weekdays].sort((a, b) => a - b); fc.time = form.time
  } else if (form.trigger_mode === 'time' && form.freq_type === 'monthly') {
    if (!Number.isInteger(form.day) || form.day < 1 || form.day > 28) {
      ElMessage.warning('每月执行日必须是 1–28 的整数'); return null
    }
    fc.day = form.day; fc.time = form.time
  }
  else if (form.trigger_mode === 'time' && form.freq_type === 'cron') {
    if (!form.cron.trim()) { ElMessage.warning('请填写 cron 表达式'); return null }
    fc.cron = form.cron.trim()
  }
  if (form.retry_enabled && (
    !Number.isInteger(form.retry_delay_value) || form.retry_delay_value < 0
    || !Number.isInteger(form.max_retries) || form.max_retries < 1 || form.max_retries > 20
  )) {
    ElMessage.warning('重试延迟须为非负整数，最大重试须为 1–20 的整数'); return null
  }
  return {
    name: form.name.trim(), task_type: form.task_type, params,
    freq_type: form.freq_type, freq_config: fc,
    trigger_mode: form.trigger_mode,
    dependency_job_ids: form.trigger_mode === 'dependency' ? [...form.dependency_job_ids] : [],
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
  if (!scheduleFormChanged.value) return
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

const downstreamDrawer = ref(false)
const downstreamJob = ref<ScheduledJob | null>(null)

const eventDrawer = ref(false)
const eventJob = ref<ScheduledJob | null>(null)
const triggerEvents = ref<ScheduledTriggerEvent[]>([])
const eventLoading = ref(false)
const eventError = ref('')
const eventRequests = createLatestRequestGuard()
async function loadTriggerEvents() {
  if (!eventJob.value || !eventDrawer.value) return
  const request = eventRequests.begin()
  eventLoading.value = true
  eventError.value = ''
  try {
    const result = await listScheduleTriggerEvents(eventJob.value.id)
    if (eventRequests.isCurrent(request)) triggerEvents.value = result.events
  } catch (error) {
    if (eventRequests.isCurrent(request)) eventError.value = getErrorMessage(error, '触发记录加载失败')
  } finally {
    if (eventRequests.isCurrent(request)) eventLoading.value = false
  }
}
async function openTriggerEvents(job: ScheduledJob) {
  eventJob.value = job
  triggerEvents.value = []
  eventDrawer.value = true
  await loadTriggerEvents()
}
watch(eventDrawer, (open) => {
  if (!open) {
    eventRequests.invalidate()
    eventLoading.value = false
  }
})
onBeforeUnmount(() => eventRequests.invalidate())
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
  return enumText(EVENT_STATUS_LABEL, status, '状态未识别')
}
function sourceStatusLabel(status: TaskStatus): string {
  return enumText({ ...STATUS_LABEL, ...SOURCE_STATUS_LABEL }, status, '状态未识别')
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
      key: 'downstream', label: '下游任务', permission: 'data-schedule:manage', placement: 'more',
      onClick: () => { downstreamJob.value = row; downstreamDrawer.value = true },
    },
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

async function load() {
  const requestId = scheduleListRequest.begin()
  loading.value = true
  loadError.value = ''
  try {
    let r = await listSchedules({
      page: jobPage.value,
      size: jobPageSize.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    })
    if (!scheduleListRequest.isCurrent(requestId)) return
    const lastPage = Math.max(1, Math.ceil(r.total / jobPageSize.value))
    if (jobPage.value > lastPage) {
      jobPage.value = lastPage
      r = await listSchedules({
        page: jobPage.value,
        size: jobPageSize.value,
        sort_by: sortBy.value,
        sort_order: sortOrder.value,
      })
      if (!scheduleListRequest.isCurrent(requestId)) return
    }
    jobs.value = r.jobs
    jobTotal.value = r.total
    taskTypes.value = r.task_types
    qualityIssueTypes.value = sortQualityIssueTypes(r.quality_issue_types?.length
      ? r.quality_issue_types
      : ISSUE_TYPES_ACTIVE)
  } catch (error) {
    if (scheduleListRequest.isCurrent(requestId)) {
      loadError.value = getErrorMessage(error, '调度任务加载失败')
    }
  } finally {
    if (scheduleListRequest.isCurrent(requestId)) loading.value = false
  }
}

onMounted(async () => {
  await load()
  openResultScheduleFromIntent()
})

// keep-alive 缓存页再次进入时不会重新执行 onMounted，激活时消费一次性新建意图。
onActivated(openResultScheduleFromIntent)
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="scheduleEffective">
    <template #action>
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        {{ menuPageTitle }}
        <HelpTip title="这页管什么？" :width="440">
          <HelpTipItem question="调度任务管什么">
            <ul>
              <li>可自定义数据采集、结果维护、数据质检、按问题类型恢复和审计清理任务。</li>
              <li>可选择时间或任务依赖触发，配置延迟与受控重试，也可启停或立即执行。</li>
              <li>实际执行记录进入「数据采集」任务中心，并标注「定时·任务名」。</li>
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
      <AppTableCard class="blk">
        <template #header>
          <div class="blk-head"><span>调度任务</span>
            <span class="app-caption-text">时间任务到点触发；依赖任务命中上游结果后可靠等待并按配置延迟执行。</span></div>
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
          :data="jobs"
          size="small"
          :loading="loading"
          :border="tableBorder('jobTable')"
          :default-sort="elementDefaultSort"
          :pagination="{ currentPage: jobPage, pageSize: jobPageSize, total: jobTotal, pageSizes: PAGE_SIZE_OPTIONS }"
          @sort-change="onSortChange"
          @page-change="(page: number) => { jobPage = page; load() }"
          @size-change="changeJobPageSize"
        >
          <AppTableColumn v-if="jobColVisible('name')" label="名称" prop="name" sortable="custom" />
          <AppTableColumn v-if="jobColVisible('taskType')" label="任务类型">
            <template #default="{ row }">{{ taskDisplayLabel(row.task_type, row.params) }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('freq')" label="触发规则" prop="freq" sortable="custom">
            <template #default="{ row }"><span data-testid="schedule-frequency">{{ row.trigger_text || row.freq_text }}</span></template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('tradingDay')" label="仅交易日" role="status">
            <template #default="{ row }">
              <el-tag :type="row.trading_day_only ? 'success' : 'info'" size="small" effect="plain">
                {{ row.trading_day_only ? '是' : '否' }}
              </el-tag>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('enabled')" label="启用" role="status">
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
          <AppTableColumn v-if="jobColVisible('retry')" label="自身重试">
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
      </AppTableCard>
    </template>

    <template #overlays>
    <ScheduleDownstreamDrawer v-model="downstreamDrawer" :job="downstreamJob" />

    <AppDetailDrawer
      v-model="eventDrawer"
      size="xl"
      :title="eventJob ? `${eventJob.name} · 触发记录` : '触发记录'"
      subtitle="仅包含任务依赖和自身重试事件；手动、定时执行记录请在任务中心查看。"
      :body-scroll="false"
      body-layout="fill"
      class="schedule-trigger-events-drawer"
      :state="eventLoading ? 'loading' : eventError ? 'error' : 'ready'"
      :state-title="eventLoading ? '正在加载触发记录…' : '触发记录加载失败'"
      :state-description="eventError"
      :retry="Boolean(eventError)"
      @retry="loadTriggerEvents"
    >
      <AppDataTable :data="triggerEvents" size="small" aria-label="调度触发记录表" data-testid="schedule-trigger-events-table">
        <AppTableColumn label="来源任务">
          <template #default="{ row }">{{ row.source_job_name || row.source_task_id }}</template>
        </AppTableColumn>
        <AppTableColumn label="来源结果" role="status">
          <template #default="{ row }">{{ sourceStatusLabel(row.source_status) }}</template>
        </AppTableColumn>
        <AppTableColumn label="类型" role="status">
          <template #default="{ row }">{{ row.trigger_kind === 'retry' ? `重试 ${row.retry_count}` : '任务依赖' }}</template>
        </AppTableColumn>
        <AppTableColumn label="命中规则" role="status">
          <template #default="{ row }">{{ triggerConditionLabel(row.trigger_condition) }}</template>
        </AppTableColumn>
        <AppTableColumn label="计划时间">
          <template #default="{ row }">{{ fmtTime(row.due_at) }}</template>
        </AppTableColumn>
        <AppTableColumn label="实际触发">
          <template #default="{ row }">{{ fmtTime(row.dispatched_at) }}</template>
        </AppTableColumn>
        <AppTableColumn label="状态" role="status">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.status === 'failed' || row.status === 'exhausted' ? 'danger' : row.status === 'waiting' || row.status === 'dispatching' ? 'warning' : row.status === 'dispatched' ? 'success' : 'info'">
              {{ eventStatusLabel(row.status) }}
            </el-tag>
          </template>
        </AppTableColumn>
        <AppTableColumn label="下游任务">
          <template #default="{ row }">{{ row.task_id || businessMessage(row.message, '尚未创建任务，详情请查看触发记录') }}</template>
        </AppTableColumn>
        <template #empty>暂无依赖或自身重试触发记录</template>
      </AppDataTable>
    </AppDetailDrawer>

    <!-- 新建/编辑对话框 -->
    <AppDetailDrawer v-model="dlg" :title="dlgTitle" size="xl" data-testid="schedule-dialog">
      <el-form label-width="92px">
        <el-form-item label="任务名称" required>
          <el-input
            v-model="form.name"
            data-testid="schedule-name"
            placeholder="如：盘后增量更新"
            maxlength="40"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="任务类型" required>
          <AppSelect
            v-model="form.task_type"
            data-testid="schedule-task-type"
            @change="changeTaskType"
            width="fill"
          >
            <el-option v-for="o in taskTypeOptions()" :key="o.value" :label="o.label" :value="o.value" />
          </AppSelect>
        </el-form-item>
        <!-- 按类型的动态参数 -->
        <el-form-item v-if="form.task_type === 'fix'" label="问题类型" required>
          <AppSelect
            v-model="form.issue_type"
            data-testid="schedule-issue-type"
            width="fill"
          >
            <el-option
              v-for="issueType in [...new Set([...qualityIssueTypes, ...(form.issue_type ? [form.issue_type] : [])])]"
              :key="issueType"
              :label="enumText(ISSUE_TYPE_LABEL, issueType, '未识别问题类型')"
              :value="issueType"
            />
          </AppSelect>
          <AppFormHelp>每次触发时动态恢复该类型当前所有“未处理”问题，无问题时正常结束</AppFormHelp>
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
        <IntradayTaskScopeFields
          v-if="form.task_type === 'intraday_ingest'"
          v-model="form.intraday"
          test-id-prefix="schedule-intraday"
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
        <el-divider
          content-position="left"
          class="form-section-divider"
          data-testid="schedule-trigger-divider"
        >触发方式</el-divider>
        <el-form-item label="触发方式" required>
          <PageSegmented v-model="form.trigger_mode" :options="TRIGGER_MODE_OPTIONS" test-id="schedule-trigger-mode" aria-label="触发方式" />
        </el-form-item>
        <template v-if="form.trigger_mode === 'time'">
        <el-form-item label="频率" required>
          <PageSegmented v-model="form.freq_type" :options="FREQ_OPTIONS" aria-label="频率" />
        </el-form-item>
        <el-form-item v-if="form.freq_type === 'weekly'" label="星期" required>
          <el-checkbox-group v-model="form.weekdays">
            <el-checkbox-button v-for="w in WEEKDAYS" :key="w.value" :value="w.value">{{ w.label }}</el-checkbox-button>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item v-if="form.freq_type === 'monthly'" label="每月几号" required>
          <el-input-number v-model="form.day" :min="1" :max="28" />
          <AppFormHelp>1–28（避开月末不确定）</AppFormHelp>
        </el-form-item>
        <el-form-item v-if="form.freq_type === 'cron'" label="cron 表达式" required>
          <el-input v-model="form.cron" placeholder="分 时 日 月 周，如 30 15 * * 1-5" />
        </el-form-item>
        <el-form-item v-if="form.freq_type !== 'cron'" label="执行时间" required>
          <el-time-picker v-model="form.time" value-format="HH:mm" format="HH:mm" placeholder="HH:mm" :clearable="false"
                          :placement="APP_BOTTOM_FLOATING_PLACEMENT"
                          :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS" />
        </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="上游任务" required>
            <AppSelect
              v-model="form.dependency_job_ids"
              data-testid="schedule-dependency-job"
              placeholder="选择上游任务"
              multiple
              clearable
              collapse-tags
              filterable
              remote
              :remote-method="loadDependencyOptions"
              :loading="dependencyOptionsLoading"
              :reserve-keyword="false"
              width="fill"
            >
              <el-option
                v-for="job in dependencyOptions"
                :key="job.id"
                :label="`${job.name}${job.enabled ? '' : '（已停用）'}`"
                :value="job.id"
              />
            </AppSelect>
            <AppFormHelp>可多选；每个上游满足结果条件后分别触发一次，不等待其他上游。</AppFormHelp>
          </el-form-item>
          <el-form-item label="结果条件" required>
            <PageSegmented v-model="form.dependency_condition" :options="CONDITION_OPTIONS" test-id="schedule-dependency-condition" aria-label="依赖结果条件" />
            <AppFormHelp>“完成后”包含成功和失败；人工终止不会触发</AppFormHelp>
          </el-form-item>
          <el-form-item label="触发延迟" required>
            <el-input-number v-model="form.dependency_delay_value" data-testid="schedule-dependency-delay" :min="0" :precision="0" />
            <AppSelect
              v-model="form.dependency_delay_unit"
              data-testid="schedule-dependency-delay-unit"
              class="delay-unit-select"
            >
              <el-option v-for="item in DELAY_UNIT_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </AppSelect>
          </el-form-item>
        </template>

        <el-divider content-position="left" class="form-section-divider">自身重试</el-divider>
        <el-form-item label="启用重试">
          <el-switch v-model="form.retry_enabled" data-testid="schedule-retry-enabled" />
          <AppFormHelp>本任务结果持续命中条件时循环执行，达到上限后结束</AppFormHelp>
        </el-form-item>
        <template v-if="form.retry_enabled">
          <el-form-item label="循环条件" required>
            <PageSegmented v-model="form.retry_condition" :options="CONDITION_OPTIONS" test-id="schedule-retry-condition" aria-label="循环结果条件" />
            <AppFormHelp v-if="form.retry_condition === 'completion'" tone="warning">
              成功和失败都会继续循环，直到达到次数上限；人工终止除外
            </AppFormHelp>
          </el-form-item>
          <el-form-item label="重试延迟" required>
            <el-input-number v-model="form.retry_delay_value" data-testid="schedule-retry-delay" :min="0" :precision="0" />
            <AppSelect
              v-model="form.retry_delay_unit"
              data-testid="schedule-retry-delay-unit"
              class="delay-unit-select"
            >
              <el-option v-for="item in DELAY_UNIT_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </AppSelect>
          </el-form-item>
          <el-form-item label="最大重试" required>
            <el-input-number v-model="form.max_retries" data-testid="schedule-max-retries" :min="1" :max="20" :precision="0" />
            <AppFormHelp>不含首次执行；最多 20 次</AppFormHelp>
          </el-form-item>
        </template>

        <el-divider content-position="left" class="form-section-divider">选项</el-divider>
        <el-form-item v-if="form.trigger_mode === 'time'" label="仅交易日">
          <el-switch v-model="form.trading_day_only" />
          <AppFormHelp>开启后非交易日自动跳过（行情/质检类建议开）</AppFormHelp>
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
          :disabled="!scheduleFormChanged"
          @click="save"
        >保存调度</el-button>
      </template>
    </AppDetailDrawer>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="任务调度"
      :dirty="isDirty || layoutDirty"
      page-key="data-schedule"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection section-key="display" title="显示">
          <PageSettingItem label="时间显示">
            <PageSegmented v-model="settings.timeMode" aria-label="时间显示" :options="[
              { label: '完整时间', value: 'full' },
              { label: '仅时分', value: 'hm' },
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
.page-head-actions { display: flex; gap: var(--app-space-2); align-items: center; }
.delay-unit-select { width: 96px; margin-left: var(--space-2); }
.blk-head { display: flex; justify-content: space-between; align-items: center; }
.form-section-divider { margin: var(--app-space-4) 0 14px; }
</style>

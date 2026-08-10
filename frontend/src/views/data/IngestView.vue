<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import {
  getDataStatus, getUpdateLogs, listTasks, createTask, getTask, getTaskLogs, resumeTask, cancelTask, getStockQuality, searchBoards,
  TASK_LABEL, STATUS_LABEL, taskDisplayLabel, SOURCE_LABEL,
  type DataStatus, type AsyncTask, type TaskType, type TaskStatus, type TaskLogLine, type UpdateLog,
} from '@/api/data'
import AppDataTable from '@/components/AppDataTable.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useTableSort } from '@/composables/useTableSort'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getErrorMessage } from '@/utils/error'
import type { AppRowAction } from '@/components/rowActions'

const route = useRoute()
const settingsOpen = ref(false)
const ingestDefaults = {
  taskStatus: 'active' as 'all' | 'active' | 'failed',
  logStatus: 'all' as 'all' | 'failed',
  autoScroll: true,
  defaultTaskType: 'ingest_date' as TaskType,
}
const { settings, isDirty, reset } = usePageSettings('data-ingest', ingestDefaults)

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
  componentLayerValuesOf,
} = useRemoteLayoutConfig(ingestLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }
const loading = ref(false)
const statusError = ref('')
const status = ref<DataStatus | null>(null)

// ── 任务中心：服务端分页 / 排序 / 筛选（M2.9.5）──
const tasks = ref<AsyncTask[]>([])
const taskError = ref('')
const taskLoading = ref(true)
const taskTotal = ref(0)
const taskPage = ref(1)
const taskSize = ref(DEFAULT_PAGE_SIZE)
const taskFilter = ref<{ status: string; task_type: string }>({ status: '', task_type: '' })
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
  setComponentKnob,
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
const logSize = ref(DEFAULT_PAGE_SIZE)
const logTables = ref<string[]>([])
const logFilter = ref<{ status: string; table_name: string }>({ status: '', table_name: '' })
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
  setComponentKnob,
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
  'update', 'backfill', 'ingest_date', 'ingest_codes', 'rebuild_price_factors',
  'recompute', 'verify', 'checkup', 'fix', 'enrich_basic', 'board',
].map((v) => ({ v: v as TaskType, l: TASK_LABEL[v as TaskType] }))
const TASK_STATUS_OPTIONS: { v: TaskStatus; l: string }[] = (
  ['pending', 'running', 'done', 'failed', 'interrupted'] as TaskStatus[]).map((v) => ({ v, l: STATUS_LABEL[v] }))

const statusType: Record<TaskStatus, 'success' | 'danger' | 'info' | 'warning'> = {
  done: 'success', failed: 'danger', running: 'warning', pending: 'info', interrupted: 'danger',
}
function isCancellingTask(t: AsyncTask | null | undefined): boolean {
  return !!t && t.status === 'running' && String(t.message || '').includes('终止中')
}
const PHASE_LABEL: Record<string, string> = {
  daily_bar: '行情采集',
  valuation_latest: '最新日市值补采',
  valuation_history: '历史市值补采',
  valuation_gap: '市值缺口回补',
  price_factor: '价格因子',
  fix_issue: '问题修复',
  board_dict: '板块字典',
  board_members: '板块成分',
  board_bar: '板块指数',
  board_fund_flow: '板块资金流',
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
      'verify', 'fix', 'enrich_basic', 'board'].includes(t.task_type)))

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

// ── 更多选项对话框 ──
const optDlg = ref(false)
const optType = ref<TaskType>('ingest_date')
const optForm = ref<{ codes: string[]; date_start: string; date_end: string; years: number | null; mode: 'backfill' | 'update' }>(
  { codes: [], date_start: '', date_end: '', years: null, mode: 'update' })

// 指定股票/板块：下拉多选，输入代码或名称远程搜索（DM-D17）。
// optType=board 搜板块（board_dict 代码/名称）；其余搜股票。
const codeOptions = ref<{ code: string; label: string }[]>([])
const codeOptLoading = ref(false)
async function remoteCode(q: string) {
  if (!q) { codeOptions.value = []; return }
  codeOptLoading.value = true
  try {
    if (optType.value === 'board') {
      const r = await searchBoards({ keyword: q, size: 30 })
      codeOptions.value = r.list.map((x) => ({ code: x.code, label: `${x.code} ${x.name}` }))
    } else {
      const r = await getStockQuality({ keyword: q, size: 30 })
      codeOptions.value = r.list.map((x) => ({ code: x.code, label: `${x.code} ${x.name}` }))
    }
  } finally {
    codeOptLoading.value = false
  }
}

function openOptions(type: TaskType) {
  optType.value = type
  optForm.value = { codes: [], date_start: '', date_end: '', years: null, mode: 'update' }
  codeOptions.value = []
  optDlg.value = true
}

// 从概览/质量页带 ?code=&start=&end= 跳来 → 预填「指定日期采集」对话框（重采该股缺口区间）
function openFromQuery() {
  const q = route.query
  if (q.task_type === 'board') {
    optType.value = 'board'
    optForm.value = {
      codes: [], date_start: '', date_end: '', years: null,
      mode: q.mode === 'backfill' ? 'backfill' : 'update',
    }
    codeOptions.value = []
    optDlg.value = true
    return
  }
  const code = typeof q.code === 'string' ? q.code : ''
  if (!code) return
  const start = typeof q.start === 'string' ? q.start : ''
  const end = typeof q.end === 'string' ? q.end : start
  optType.value = 'ingest_date'
  optForm.value = { codes: [code], date_start: start, date_end: end, years: null, mode: 'backfill' }
  codeOptions.value = [{ code, label: code }]   // 让多选框显示该代码
  optDlg.value = true
  if (start) ElMessage.info(`已带入 ${code} 的待补区间 ${start}~${end}，点「执行」即重采`)
}

async function submitOptions() {
  const f = optForm.value
  const codes = f.codes
  const params: Record<string, unknown> = {}
  if (codes.length) params.codes = codes
  if (optType.value === 'ingest_date') {
    if (!f.date_start) { ElMessage.warning('请选择起始日期'); return }
    params.date_start = f.date_start
    params.date_end = f.date_end || f.date_start
  } else if (optType.value === 'backfill') {
    if (f.years) params.years = f.years
  } else if (optType.value === 'ingest_codes') {
    if (!codes.length) { ElMessage.warning('请填写股票代码'); return }
  } else if (optType.value === 'board') {
    params.mode = f.mode  // 板块采集：增量（默认）/ 全量回填
  }
  optDlg.value = false
  await submit(optType.value, params)
}

// ── 提交任务 ──
async function submit(type: TaskType, params?: Record<string, unknown>, confirm?: string) {
  if (confirm) {
    try { await ElMessageBox.confirm(confirm, TASK_LABEL[type], { type: 'warning' }) } catch { return }
  }
  try {
    const { task_id } = await createTask(type, params)
    ElMessage.success(`已提交：${TASK_LABEL[type]}`)
    await refreshTasks()
    openLogs(task_id)
  } catch (e) {
    /* 409 等错误由 http 拦截器已弹出提示 */
  }
}

let taskTimer: number | undefined
function activeCount() {
  return tasks.value.filter((t) => t.status === 'pending' || t.status === 'running').length
}
async function loadTasks(silent = false) {
  const before = activeCount()
  if (!silent) taskLoading.value = true
  taskError.value = ''
  try {
    const r = await listTasks({
      page: taskPage.value, size: taskSize.value,
      status: taskFilter.value.status || undefined, task_type: taskFilter.value.task_type || undefined,
      sort: taskSortBy.value, order: taskSortOrder.value,
    })
    tasks.value = r.tasks
    taskTotal.value = r.total ?? r.tasks.length
  } catch (error) {
    taskError.value = getErrorMessage(error, '任务中心加载失败')
  } finally {
    if (!silent) taskLoading.value = false
  }
  const after = activeCount()
  if (before > 0 && after === 0) {
    await loadLogs()
    try {
      statusError.value = ''
      status.value = await getDataStatus()
    } catch (error) {
      statusError.value = getErrorMessage(error, '数据状态刷新失败')
    }
  }
  if (taskTimer) { clearTimeout(taskTimer); taskTimer = undefined }
  // 自动轮询只更新任务数据，不反复触发表格 loading 遮罩，避免页面每两秒闪烁。
  if (pageActive && after > 0) {
    taskTimer = window.setTimeout(() => { void loadTasks(true) }, 2000)
  }
}
const refreshTasks = loadTasks   // 兼容旧调用名
async function loadLogs() {
  logLoading.value = true
  logError.value = ''
  try {
    const r = await getUpdateLogs({
      page: logPage.value, size: logSize.value,
      status: logFilter.value.status || undefined, table_name: logFilter.value.table_name || undefined,
      sort: logSortBy.value, order: logSortOrder.value,
    })
    updateLogList.value = r.list
    logTotal.value = r.total
    if (r.tables?.length) logTables.value = r.tables
  } catch (error) {
    logError.value = getErrorMessage(error, '采集日志加载失败')
  } finally {
    logLoading.value = false
  }
}
async function load() {
  loading.value = true
  statusError.value = ''
  try {
    status.value = await getDataStatus()
  } catch (error) {
    statusError.value = getErrorMessage(error, '数据状态刷新失败')
  } finally { loading.value = false }
  await loadTasks()
  await loadLogs()
}

// ── 续跑 ──
async function resume(t: AsyncTask) {
  try {
    await resumeTask(t.id)
    ElMessage.success('已续跑')
    await refreshTasks()
    openLogs(t.id)
  } catch { /* 拦截器弹错 */ }
}

// ── 终止（协作式：到下一只股票/下一步停下，可续跑）──
async function cancel(t: AsyncTask) {
  const tip = t.capability?.cancel_message || '会在下一个安全检查点停止'
  try {
    await ElMessageBox.confirm(`终止后已完成的部分会保留。${tip}。确认终止该任务？`,
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
const autoScroll = ref(Boolean(settings.autoScroll))
watch(() => settings.autoScroll, (value) => { autoScroll.value = Boolean(value) })
function applyTaskPrefs() {
  taskFilter.value.status = settings.taskStatus === 'active'
    ? 'running'
    : settings.taskStatus === 'failed'
      ? 'failed'
      : ''
  taskPage.value = 1
  loadTasks()
}
function applyLogPrefs() {
  logFilter.value.status = settings.logStatus === 'failed' ? 'failed' : ''
  logPage.value = 1
  loadLogs()
}
watch(() => settings.taskStatus, () => { applyTaskPrefs() })
watch(() => settings.logStatus, () => { applyLogPrefs() })
watch(() => settings.defaultTaskType, (value) => {
  if (!optDlg.value) optType.value = value
})
const logBody = ref<HTMLElement | null>(null)
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
      title: taskPhaseText(row) || row.message || undefined,
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
      label: '续跑',
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
        logs.value.push(...lines)
        lastSeq = lines[lines.length - 1].seq
        if (autoScroll.value) requestAnimationFrame(() => {
          if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight
        })
      }
      const st = logTask.value?.status
      if (st === 'done' || st === 'failed' || st === 'interrupted') {
        await refreshTasks()
        if (st === 'done') await load()
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
  optType.value = settings.defaultTaskType
  if (settings.taskStatus === 'active') taskFilter.value.status = 'running'
  else if (settings.taskStatus === 'failed') taskFilter.value.status = 'failed'
  if (settings.logStatus === 'failed') logFilter.value.status = 'failed'
  await load()
  openFromQuery()
  pageInitialized = true
})
</script>

<template>
  <LayoutHost :layout="ingestEffective">
    <template #action>
    <div class="page-head">
      <h2>
        数据采集
        <HelpTip title="这页能做什么？" :width="420">
          手动触发数据采集 / 补数 / 评分维护，后台异步执行：可离开页面，回来在「任务中心」点开看实时日志、
          断点续跑。定时任务触发的执行也会出现在任务中心（标注「定时·任务名」），同样可看每一步日志。
        </HelpTip>
      </h2>
      <div class="page-head-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <div class="ingest-body">
      <AppStateBlock
        v-if="statusError"
        state="error"
        size="compact"
        title="数据状态刷新失败"
        :description="statusError"
        retry
        @retry="load"
      />
      <div class="ingest-top">
      <!-- 采集区 -->
      <el-card shadow="never" class="blk">
        <template #header>
          <div class="blk-head"><span>数据采集</span>
            <span class="hint">采集对象＝数据资产表中的：日线行情 / 市值指标 / 指数 / 交易日历 / 概念与行业板块。同类采集任务不可并发。</span></div>
        </template>
        <div class="act-grid">
          <div class="act">
            <div class="act-t">增量更新</div>
            <div class="act-d">拉取至最新交易日</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small" :disabled="writeRunning" @click="submit('update')">执行</el-button>
            <el-button v-permission="'data-task:manage'" text size="small" @click="openOptions('ingest_codes')">指定股票…</el-button>
          </div>
          <div class="act">
            <div class="act-t">历史补数</div>
            <div class="act-d">回补缺失历史（可能较久）</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small" :disabled="writeRunning"
                       @click="submit('backfill', undefined, '历史补数耗时可能较长，确认开始？')">执行</el-button>
            <el-button v-permission="'data-task:manage'" text size="small" @click="openOptions('backfill')">更多选项…</el-button>
          </div>
          <div class="act">
            <div class="act-t">指定日期采集</div>
            <div class="act-d">补单日 / 区间行情，可选指定股票（重采缺口即走这里）</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small" :disabled="writeRunning" @click="openOptions('ingest_date')">设置并执行</el-button>
          </div>
          <div class="act">
            <div class="act-t">板块采集</div>
            <div class="act-d">板块字典/成分/指数/资金流（执行=增量，更多选项可选回填）</div>
            <el-button v-permission="'data-task:manage'" type="primary" plain size="small" :disabled="writeRunning"
                       @click="submit('board', { mode: 'update' }, '板块采集（增量）开始？')">执行</el-button>
            <el-button v-permission="'data-task:manage'" text size="small" @click="openOptions('board')">更多选项…</el-button>
          </div>
        </div>
      </el-card>

      <!-- 评分维护区 -->
      <el-card shadow="never" class="blk">
        <template #header><div class="blk-head"><span>评分维护</span>
          <span class="hint">数据质检入口在「数据质量」页。</span></div></template>
        <div class="act-grid">
          <div class="act">
            <div class="act-t">生产公共榜单
              <HelpTip title="什么时候需要？" :width="360">
                榜单页只读取已生产的公共快照；采集、补数、修复后相关评分会过期。
                手动执行会刷新评分缓存，并按最新交易日生产平台公共预设榜单。
              </HelpTip>
            </div>
            <div class="act-d">刷新评分缓存，并生成最新交易日公共预设榜单快照</div>
            <el-button v-permission="'data-task:manage'" plain size="small" @click="submit('recompute')">执行</el-button>
          </div>
        </div>
      </el-card>
      </div>

      <div class="ingest-bottom">
      <!-- 任务中心 -->
      <el-card shadow="never" class="blk ingest-panel">
        <template #header>
          <div class="blk-head">
            <span>任务中心</span>
            <div class="flt">
              <el-select v-model="taskFilter.task_type" placeholder="类型" clearable size="small" style="width: 130px"
                         @change="() => { taskPage = 1; loadTasks() }">
                <el-option v-for="o in TASK_TYPE_OPTIONS" :key="o.v" :label="o.l" :value="o.v" />
              </el-select>
              <el-select v-model="taskFilter.status" placeholder="状态" clearable size="small" style="width: 110px"
                         @change="() => { taskPage = 1; loadTasks() }">
                <el-option v-for="o in TASK_STATUS_OPTIONS" :key="o.v" :label="o.l" :value="o.v" />
              </el-select>
            </div>
          </div>
        </template>
        <div class="panel-table-wrap" data-testid="task-center-panel">
          <AppStateBlock
            v-if="taskLoading && !tasks.length"
            state="loading"
            title="正在加载任务中心…"
          />
          <AppStateBlock
            v-else-if="taskError && !tasks.length"
            state="error"
            title="任务中心加载失败"
            :description="taskError"
            retry
            @retry="loadTasks"
          />
          <template v-else>
          <AppStateBlock
            v-if="taskError"
            state="error"
            size="compact"
            title="任务中心刷新失败"
            :description="taskError"
            retry
            @retry="loadTasks"
          />
          <AppDataTable
            :data="tasks"
            :loading="taskLoading"
            size="small"
            :border="tableBorder('taskTable')"
            :default-sort="taskDefaultSort"
            table-class="clk-tbl"
            clickable
            :pagination="{ currentPage: taskPage, pageSize: taskSize, total: taskTotal, pageSizes: PAGE_SIZE_OPTIONS }"
            @row-click="(r: AsyncTask) => openLogs(r.id)"
            @sort-change="onTaskSort"
            @page-change="(p: number) => { taskPage = p; loadTasks() }"
            @size-change="(s: number) => { taskSize = s; taskPage = 1; loadTasks() }"
          >
            <AppTableColumn label="任务ID" show-overflow-tooltip>
              <template #default="{ row }"><span class="task-id">{{ row.id }}</span></template>
            </AppTableColumn>
            <AppTableColumn label="类型" prop="type" sortable="custom">
              <template #default="{ row }">
                {{ taskDisplayLabel(row.task_type, row.params) }}
              </template>
            </AppTableColumn>
            <AppTableColumn label="来源" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-if="row.trigger_source === 'scheduled'" type="warning" size="small" effect="plain">
                  定时{{ row.job_name ? `·${row.job_name}` : '' }}
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
            <AppTableColumn label="信息" prop="message" show-overflow-tooltip />
            <AppTableColumn label="截止时间" prop="time" sortable="custom">
              <template #default="{ row }">{{ (row.updated_at || '').slice(0, 19) }}</template>
            </AppTableColumn>
            <AppTableColumn label="总耗时">
              <template #default="{ row }">{{ taskDuration(row) }}</template>
            </AppTableColumn>
            <AppTableColumn label="操作">
              <template #default="{ row }">
                <AppRowActions :actions="taskRowActions(row)" :inline-limit="2" />
              </template>
            </AppTableColumn>
          </AppDataTable>
          </template>
        </div>
      </el-card>

      <!-- 采集更新日志（按表/批次留痕）-->
      <el-card shadow="never" class="blk ingest-panel">
        <template #header>
          <div class="blk-head">
            <span>采集日志</span>
            <div class="flt">
              <span class="hint">失败行可见原因；逐股明细见任务中心「日志」</span>
              <el-select v-model="logFilter.table_name" placeholder="目标表" clearable size="small" style="width: 140px"
                         @change="() => { logPage = 1; loadLogs() }">
                <el-option v-for="t in logTables" :key="t" :label="t" :value="t" />
              </el-select>
              <el-select v-model="logFilter.status" placeholder="结果" clearable size="small" style="width: 100px"
                         @change="() => { logPage = 1; loadLogs() }">
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
                <el-option label="部分" value="partial" />
              </el-select>
            </div>
          </div>
        </template>
        <div class="panel-table-wrap">
          <AppStateBlock
            v-if="logLoading && !updateLogList.length"
            state="loading"
            title="正在加载采集日志…"
          />
          <AppStateBlock
            v-else-if="logError && !updateLogList.length"
            state="error"
            title="采集日志加载失败"
            :description="logError"
            retry
            @retry="loadLogs"
          />
          <template v-else>
          <AppStateBlock
            v-if="logError"
            state="error"
            size="compact"
            title="采集日志刷新失败"
            :description="logError"
            retry
            @retry="loadLogs"
          />
          <AppDataTable
            :data="updateLogList"
            :loading="logLoading"
            size="small"
            :border="tableBorder('logTable')"
            :default-sort="logDefaultSort"
            :row-class-name="logRowClass"
            :pagination="{ currentPage: logPage, pageSize: logSize, total: logTotal, pageSizes: PAGE_SIZE_OPTIONS }"
            @sort-change="onLogSort"
            @page-change="(p: number) => { logPage = p; loadLogs() }"
            @size-change="(s: number) => { logSize = s; logPage = 1; loadLogs() }"
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
                  {{ row.status === 'success' ? '成功' : row.status === 'failed' ? '失败' : row.status === 'partial' ? '部分' : row.status }}
                </el-tag>
              </template>
            </AppTableColumn>
            <AppTableColumn label="行数" prop="row_count" align="right" />
            <AppTableColumn label="区间">
              <template #default="{ row }">{{ row.date_start ? `${row.date_start} ~ ${row.date_end || row.date_start}` : '—' }}</template>
            </AppTableColumn>
            <AppTableColumn label="详情 / 失败原因" show-overflow-tooltip>
              <template #default="{ row }">
                <span :class="{ 'fail-detail': row.status === 'failed', 'partial-detail': row.status === 'partial' }">{{ row.detail || (row.status === 'success' ? '—' : '') }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn label="时间" prop="time" sortable="custom">
              <template #default="{ row }">{{ (row.updated_at || '').slice(0, 19) }}</template>
            </AppTableColumn>
          </AppDataTable>
          </template>
        </div>
      </el-card>
      </div>
    </div>
    </template>

    <template #overlays>
    <!-- 更多选项对话框 -->
    <el-dialog
      v-model="optDlg"
      :title="`${TASK_LABEL[optType]} · 更多选项`"
      width="460px"
      data-testid="ingest-options-dialog"
    >
      <el-form label-width="92px">
        <el-form-item v-if="optType === 'ingest_date'" label="起始日期">
          <TradeDatePicker v-model="optForm.date_start" placeholder="必填，仅可选交易日" />
        </el-form-item>
        <el-form-item v-if="optType === 'ingest_date'" label="结束日期">
          <TradeDatePicker v-model="optForm.date_end" placeholder="留空=仅起始日" clearable />
        </el-form-item>
        <el-form-item v-if="optType === 'backfill'" label="回填年限">
          <el-input-number v-model="optForm.years" :min="1" :max="30" placeholder="留空=默认" />
        </el-form-item>
        <el-form-item v-if="optType === 'board'" label="采集模式">
          <el-radio-group v-model="optForm.mode" data-testid="ingest-board-mode">
            <el-radio value="update">增量</el-radio>
            <el-radio value="backfill">全量回填</el-radio>
          </el-radio-group>
          <span class="hint">增量：指数补最近交易日、资金流只采即时、成分股按周频跳过未到期板块；全量回填：指数补 2024 起、资金流全周期、成分股强制全量</span>
        </el-form-item>
        <el-form-item :label="optType === 'board' ? '指定板块' : '指定股票'">
          <el-select v-model="optForm.codes" multiple filterable remote clearable collapse-tags
                     :remote-method="remoteCode" :loading="codeOptLoading" :reserve-keyword="false"
                     :placeholder="optType === 'board' ? '输入板块代码或名称搜索' : '输入代码或名称搜索'" style="width: 100%">
            <el-option v-for="o in codeOptions" :key="o.code" :label="o.label" :value="o.code" />
          </el-select>
          <span class="hint">可多选；留空={{ optType === 'board' ? '全部板块' : '全市场' }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="optDlg = false">取消</el-button>
        <el-button v-permission="'data-task:manage'" type="primary" @click="submitOptions">执行</el-button>
      </template>
    </el-dialog>

    <!-- 实时日志抽屉 -->
    <PageDrawer v-model="logDrawer" :title="logTask ? `${taskDisplayLabel(logTask.task_type, logTask.params)} · 实时日志` : '实时日志'"
                size="wide" class="log-drawer" data-testid="task-log-drawer" @close="closeLogs">
      <div v-if="logTask" class="log-meta">
        <el-tag :type="taskStatusType(logTask)" size="small" effect="dark">{{ taskStatusLabel(logTask) }}</el-tag>
        <span class="lm-msg">{{ logTask.message }}</span>
        <span v-if="taskPhaseText(logTask)" class="lm-phase">{{ taskPhaseText(logTask) }}</span>
        <el-progress :percentage="Math.round((logTask.progress ?? 0) * 100)" :stroke-width="8" style="flex:1" />
        <el-checkbox v-model="autoScroll" size="small">自动滚动</el-checkbox>
      </div>
      <div ref="logBody" class="log-body">
        <div v-for="l in logs" :key="l.seq" class="log-line" :class="l.level">
          <span class="lt">{{ (l.ts || '').slice(11, 19) }}</span>
          <span class="lm">{{ l.message }}</span>
        </div>
        <div v-if="!logs.length" class="app-empty-inline">暂无日志…</div>
      </div>
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
        <PageSettingSection title="任务中心">
          <div class="setting-item">
            <div class="setting-label">默认任务筛选</div>
            <PageSegmented v-model="settings.taskStatus" aria-label="默认任务筛选" :options="[
              { label: '全部', value: 'all' },
              { label: '运行中', value: 'active' },
              { label: '失败项', value: 'failed' },
            ]" />
          </div>
        </PageSettingSection>
        <PageSettingSection title="日志与显示">
          <div class="setting-item">
            <div class="setting-label">采集日志筛选</div>
            <PageSegmented v-model="settings.logStatus" aria-label="采集日志筛选" :options="[
              { label: '全部', value: 'all' },
              { label: '仅失败', value: 'failed' },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">更多选项默认任务</div>
            <PageSegmented v-model="settings.defaultTaskType" aria-label="更多选项默认任务" :options="[
              { label: '指定日期', value: 'ingest_date' },
              { label: '增量更新', value: 'update' },
              { label: '历史补数', value: 'backfill' },
            ]" />
          </div>
          <PageToggleRow v-model="settings.autoScroll" label="日志默认自动滚动" />
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; }
.page-head h2 { margin: 0; font-size: var(--app-font-size-page-title-sm); }
/* 填满 LayoutHost 的条件成长区；内部「顶部固定卡 + 底部双栏成长表」，放不下时整区内滚 */
.ingest-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}
.ingest-top {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}
.ingest-bottom {
  flex: 1 1 auto;
  min-height: 520px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--app-space-4);
}
.ingest-panel {
  margin-bottom: 0;
  min-height: 0;
}
.ingest-panel :deep(.el-card__body) {
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
.setting-item { display: flex; flex-direction: column; gap: var(--app-space-2); }
.setting-label { font-size: var(--app-font-size-body); color: var(--page-settings-text-subtle); }
.page-sub { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: var(--app-font-size-table); }
.blk { margin-bottom: 16px; }
.blk-head { display: flex; justify-content: space-between; align-items: center; gap: var(--app-space-3); }
.hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.flt { display: flex; align-items: center; gap: var(--app-space-2); }
.act-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--app-space-3); }
.act { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 12px 14px; }
.act-t { font-weight: var(--app-font-weight-section); }
.act-d { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin: 4px 0 10px; }
.task-id { font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.log-meta { flex: 0 0 auto; display: flex; align-items: center; gap: var(--app-space-2); margin-bottom: 10px; }
.lm-msg { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lm-phase { font-size: var(--app-font-size-caption); color: var(--el-color-warning); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-body { flex: 1 1 auto; min-height: 0; overflow: auto; background: var(--el-fill-color-darker); border-radius: 6px; padding: 10px; font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); }
.log-line { display: flex; gap: var(--app-space-2); padding: 1px 0; }
.log-line.warn { color: var(--app-warning-text); }
.log-line.error { color: var(--app-danger-text); }
.lt { color: var(--el-text-color-secondary); flex-shrink: 0; }
:deep(.row-fail) { background: var(--el-color-danger-light-9); }
:deep(.row-partial) { background: var(--el-color-warning-light-9); }
.fail-detail { color: var(--app-danger-text); }
.partial-detail { color: var(--app-warning-text); }
@media (max-width: 1280px) {
  .ingest-bottom {
    grid-template-columns: 1fr;
    min-height: unset;
  }
}
</style>

<!-- PageDrawer 经 teleport 挂到 LayoutHost 内容区，scoped 作用域属性不会带到抽屉根，
     故用非 scoped 块（.log-drawer 类名唯一，不污染全局）让抽屉正文成为 flex 列：
     meta 固定 + 日志区填满并内部滚动，meta 行换行也不再错位/裁切 -->
<style>
.log-drawer .el-drawer__body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
</style>

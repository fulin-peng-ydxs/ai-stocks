<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import {
  getDataStatus, getUpdateLogs, listTasks, createTask, getTask, getTaskLogs, resumeTask, cancelTask, getStockQuality,
  TASK_LABEL, STATUS_LABEL, ISSUE_TYPE_LABEL,
  type DataStatus, type AsyncTask, type TaskType, type TaskStatus, type TaskLogLine, type UpdateLog,
} from '@/api/data'
import HelpTip from '@/components/HelpTip.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const route = useRoute()
const settingsOpen = ref(false)
const ingestDefaults = {
  taskStatus: 'active' as 'all' | 'active' | 'failed',
  taskSort: 'time' as 'time' | 'status',
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

// 抽屉「布局」段由 PageSettingsDrawer 按 config 自动渲染（本页无组件配置，仅布局段）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }
const loading = ref(false)
const status = ref<DataStatus | null>(null)

// ── 任务中心：服务端分页 / 排序 / 筛选（M2.9.5）──
const tasks = ref<AsyncTask[]>([])
const taskTotal = ref(0)
const taskPage = ref(1)
const taskSize = ref(DEFAULT_PAGE_SIZE)
const taskFilter = ref<{ status: string; task_type: string }>({ status: '', task_type: '' })
const taskSort = ref<{ sort: 'time' | 'type' | 'status'; order: 'asc' | 'desc' }>({ sort: 'time', order: 'desc' })

// ── 采集日志：服务端分页 / 排序 / 筛选（M2.9.5）──
const updateLogList = ref<UpdateLog[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logSize = ref(DEFAULT_PAGE_SIZE)
const logTables = ref<string[]>([])
const logFilter = ref<{ status: string; table_name: string }>({ status: '', table_name: '' })
const logSort = ref<{ sort: 'time' | 'table' | 'status'; order: 'asc' | 'desc' }>({ sort: 'time', order: 'desc' })
const TASK_TYPE_OPTIONS: { v: TaskType; l: string }[] = [
  'update', 'backfill', 'ingest_date', 'ingest_codes', 'rebuild_price_factors',
  'recompute', 'verify', 'checkup', 'fix', 'enrich_basic',
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
  return t.status === 'interrupted' && Boolean(t.capability?.can_resume)
}
function taskStatusLabel(t: AsyncTask): string {
  return isCancellingTask(t) ? '终止中' : (STATUS_LABEL[t.status as TaskStatus] ?? t.status)
}
function taskStatusType(t: AsyncTask): 'success' | 'danger' | 'info' | 'warning' {
  return isCancellingTask(t) ? 'warning' : (statusType[t.status as TaskStatus] ?? 'info')
}
const updateLogType: Record<string, 'success' | 'danger' | 'info'> = { success: 'success', failed: 'danger' }
function logRowClass({ row }: { row: { status: string } }): string {
  return row.status === 'failed' ? 'row-fail' : ''
}
const writeRunning = computed(() =>
  tasks.value.some((t) => ['pending', 'running'].includes(t.status)
    && ['update', 'backfill', 'ingest_date', 'ingest_codes', 'fix'].includes(t.task_type)))

// 总耗时：进行中=开始到现在(随 now 每秒刷新)；已结束/人工终止=开始到截止时间(updated_at)。
const now = ref(Date.now())
const nowTimer = window.setInterval(() => { now.value = Date.now() }, 1000)
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
const optForm = ref<{ codes: string[]; date_start: string; date_end: string; years: number | null }>(
  { codes: [], date_start: '', date_end: '', years: null })

// 指定股票：下拉多选，输入代码或名称远程搜索（DM-D17）
const codeOptions = ref<{ code: string; label: string }[]>([])
const codeOptLoading = ref(false)
async function remoteCode(q: string) {
  if (!q) { codeOptions.value = []; return }
  codeOptLoading.value = true
  try {
    const r = await getStockQuality({ keyword: q, size: 30 })
    codeOptions.value = r.list.map((x) => ({ code: x.code, label: `${x.code} ${x.name}` }))
  } finally {
    codeOptLoading.value = false
  }
}

function openOptions(type: TaskType) {
  optType.value = type
  optForm.value = { codes: [], date_start: '', date_end: '', years: null }
  codeOptions.value = []
  optDlg.value = true
}

// 从概览/质量页带 ?code=&start=&end= 跳来 → 预填「指定日期采集」对话框（重采该股缺口区间）
function openFromQuery() {
  const q = route.query
  const code = typeof q.code === 'string' ? q.code : ''
  if (!code) return
  const start = typeof q.start === 'string' ? q.start : ''
  const end = typeof q.end === 'string' ? q.end : start
  optType.value = 'ingest_date'
  optForm.value = { codes: [code], date_start: start, date_end: end, years: null }
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
async function loadTasks() {
  const before = activeCount()
  try {
    const r = await listTasks({
      page: taskPage.value, size: taskSize.value,
      status: taskFilter.value.status || undefined, task_type: taskFilter.value.task_type || undefined,
      sort: taskSort.value.sort, order: taskSort.value.order,
    })
    tasks.value = r.tasks
    taskTotal.value = r.total ?? r.tasks.length
  } catch { /**/ }
  const after = activeCount()
  if (before > 0 && after === 0) { await loadLogs(); try { status.value = await getDataStatus() } catch { /**/ } }
  if (taskTimer) { clearTimeout(taskTimer); taskTimer = undefined }
  if (after > 0) taskTimer = window.setTimeout(loadTasks, 2000)
}
const refreshTasks = loadTasks   // 兼容旧调用名
function onTaskSort({ prop, order }: { prop: string; order: string | null }) {
  if (!order) { taskSort.value = { sort: 'time', order: 'desc' } } else {
    taskSort.value = { sort: prop as 'time' | 'type' | 'status', order: order === 'ascending' ? 'asc' : 'desc' }
  }
  taskPage.value = 1; loadTasks()
}

async function loadLogs() {
  try {
    const r = await getUpdateLogs({
      page: logPage.value, size: logSize.value,
      status: logFilter.value.status || undefined, table_name: logFilter.value.table_name || undefined,
      sort: logSort.value.sort, order: logSort.value.order,
    })
    updateLogList.value = r.list
    logTotal.value = r.total
    if (r.tables?.length) logTables.value = r.tables
  } catch { /**/ }
}
function onLogSort({ prop, order }: { prop: string; order: string | null }) {
  if (!order) { logSort.value = { sort: 'time', order: 'desc' } } else {
    logSort.value = { sort: prop as 'time' | 'table' | 'status', order: order === 'ascending' ? 'asc' : 'desc' }
  }
  logPage.value = 1; loadLogs()
}

async function load() {
  loading.value = true
  try { status.value = await getDataStatus() } finally { loading.value = false }
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
  taskSort.value = settings.taskSort === 'status'
    ? { sort: 'status', order: 'asc' }
    : { sort: 'time', order: 'desc' }
  taskPage.value = 1
  loadTasks()
}
function applyLogPrefs() {
  logFilter.value.status = settings.logStatus === 'failed' ? 'failed' : ''
  logPage.value = 1
  loadLogs()
}
watch(() => settings.taskStatus, () => { applyTaskPrefs() })
watch(() => settings.taskSort, () => { applyTaskPrefs() })
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

function pollLogs(id: string) {
  if (logTimer) clearTimeout(logTimer)
  const tick = async () => {
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
    logTimer = window.setTimeout(tick, 1200)
  }
  tick()
}

function closeLogs() { logDrawer.value = false; if (logTimer) clearTimeout(logTimer) }
onUnmounted(() => { if (logTimer) clearTimeout(logTimer); if (taskTimer) clearTimeout(taskTimer); clearInterval(nowTimer) })
onMounted(async () => {
  optType.value = settings.defaultTaskType
  if (settings.taskStatus === 'active') taskFilter.value.status = 'running'
  else if (settings.taskStatus === 'failed') taskFilter.value.status = 'failed'
  if (settings.logStatus === 'failed') logFilter.value.status = 'failed'
  if (settings.taskSort === 'status') taskSort.value = { sort: 'status', order: 'asc' }
  await load()
  openFromQuery()
})
</script>

<template>
  <LayoutHost :layout="ingestEffective">
    <template #action>
    <div class="page-head">
      <h2>
        数据采集
        <HelpTip title="这页能做什么？" :width="420">
          手动触发数据采集 / 补数 / 刷新评分，后台异步执行：可离开页面，回来在「任务中心」点开看实时日志、
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
      <div class="ingest-top">
      <!-- 采集区 -->
      <el-card shadow="never" class="blk">
        <template #header>
          <div class="blk-head"><span>数据采集</span>
            <span class="hint">采集对象＝数据资产表中的：日线行情 / 市值指标 / 指数 / 交易日历。同类采集任务不可并发。</span></div>
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
        </div>
      </el-card>

      <!-- 评分维护区 -->
      <el-card shadow="never" class="blk">
        <template #header><div class="blk-head"><span>评分维护</span>
          <span class="hint">数据质检入口在「数据质量」页。</span></div></template>
        <div class="act-grid">
          <div class="act">
            <div class="act-t">刷新评分缓存
              <HelpTip title="什么时候需要？" :width="360">
                榜单/方案的评分会被缓存以秒级打开；采集、补数、修复后系统已自动让相关评分过期。
                仅当你怀疑评分未跟上数据时，手动点此把全部评分标记为「需重算」，下次打开自动重新计算。
              </HelpTip>
            </div>
            <div class="act-d">把所有已缓存评分标记为需重算（一般无需手动，数据变更已自动处理）</div>
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
        <div class="panel-table-wrap">
          <el-table :data="tasks" size="small" height="100%" @row-click="(r: AsyncTask) => openLogs(r.id)"
                    class="clk-tbl" @sort-change="onTaskSort">
            <el-table-column label="任务ID" width="220" show-overflow-tooltip>
              <template #default="{ row }"><span class="task-id">{{ row.id }}</span></template>
            </el-table-column>
            <el-table-column label="类型" prop="type" width="150" sortable="custom">
              <template #default="{ row }">
                {{ TASK_LABEL[row.task_type as TaskType] ?? row.task_type }}<!--
                -->{{ row.task_type === 'fix' && row.params?.issue_type ? `·${ISSUE_TYPE_LABEL[row.params.issue_type] ?? row.params.issue_type}` : '' }}
              </template>
            </el-table-column>
            <el-table-column label="来源" width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-if="row.trigger_source === 'scheduled'" type="warning" size="small" effect="plain">
                  定时{{ row.job_name ? `·${row.job_name}` : '' }}
                </el-tag>
                <el-tag v-else size="small" effect="plain" type="info">
                  {{ row.job_name ? `手动·${row.job_name}` : '手动' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" prop="status" width="90" sortable="custom">
              <template #default="{ row }">
                <el-tag :type="taskStatusType(row)" size="small" effect="dark">
                  {{ taskStatusLabel(row) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="140">
              <template #default="{ row }">
                <el-progress :percentage="Math.round((row.progress ?? 0) * 100)" :stroke-width="10"
                  :status="row.status === 'failed' || row.status === 'interrupted' ? 'exception' : row.status === 'done' ? 'success' : undefined" />
              </template>
            </el-table-column>
            <el-table-column label="信息" prop="message" show-overflow-tooltip />
            <el-table-column label="截止时间" prop="time" width="160" sortable="custom">
              <template #default="{ row }">{{ (row.updated_at || '').slice(0, 19) }}</template>
            </el-table-column>
            <el-table-column label="总耗时" width="100">
              <template #default="{ row }">{{ taskDuration(row) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="130">
              <template #default="{ row }">
                <el-tooltip v-if="isCancellingTask(row)" :content="taskPhaseText(row) || row.message" placement="top">
                  <el-button type="warning" size="small" link disabled>等待检查点</el-button>
                </el-tooltip>
                <el-button v-else-if="canCancelTask(row)" type="danger" size="small" link
                           @click.stop="cancel(row)">终止</el-button>
                <el-button v-if="canResumeTask(row)" type="warning" size="small" link
                           @click.stop="resume(row)">续跑</el-button>
                <el-button type="primary" size="small" link @click.stop="openLogs(row.id)">日志</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="pager">
          <el-pagination layout="total, sizes, prev, pager, next" :total="taskTotal" background
                         :current-page="taskPage" :page-size="taskSize" :page-sizes="PAGE_SIZE_OPTIONS"
                         @current-change="(p: number) => { taskPage = p; loadTasks() }"
                         @size-change="(s: number) => { taskSize = s; taskPage = 1; loadTasks() }" />
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
          <el-table :data="updateLogList" size="small" height="100%" :row-class-name="logRowClass" @sort-change="onLogSort">
            <el-table-column label="目标表" prop="table" width="130" sortable="custom">
              <template #default="{ row }">{{ row.table_name }}</template>
            </el-table-column>
            <el-table-column label="数据源" width="92">
              <template #default="{ row }">{{ row.source === 'akshare' ? 'AKShare' : row.source === 'baostock' ? 'BaoStock' : row.source }}</template>
            </el-table-column>
            <el-table-column label="结果" prop="status" width="76" sortable="custom">
              <template #default="{ row }">
                <el-tag :type="updateLogType[row.status] ?? 'info'" size="small" effect="plain">
                  {{ row.status === 'success' ? '成功' : row.status === 'failed' ? '失败' : row.status === 'partial' ? '部分' : row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="行数" prop="row_count" width="70" align="right" />
            <el-table-column label="区间" width="180">
              <template #default="{ row }">{{ row.date_start ? `${row.date_start} ~ ${row.date_end || row.date_start}` : '—' }}</template>
            </el-table-column>
            <el-table-column label="详情 / 失败原因" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span :class="{ 'fail-detail': row.status === 'failed' }">{{ row.detail || (row.status === 'success' ? '—' : '') }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" prop="time" width="160" sortable="custom">
              <template #default="{ row }">{{ (row.updated_at || '').slice(0, 19) }}</template>
            </el-table-column>
          </el-table>
        </div>
        <div class="pager">
          <el-pagination layout="total, sizes, prev, pager, next" :total="logTotal" background
                         :current-page="logPage" :page-size="logSize" :page-sizes="PAGE_SIZE_OPTIONS"
                         @current-change="(p: number) => { logPage = p; loadLogs() }"
                         @size-change="(s: number) => { logSize = s; logPage = 1; loadLogs() }" />
        </div>
      </el-card>
      </div>
    </div>
    </template>

    <template #overlays>
    <!-- 更多选项对话框 -->
    <el-dialog v-model="optDlg" :title="`${TASK_LABEL[optType]} · 更多选项`" width="460px">
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
        <el-form-item label="指定股票">
          <el-select v-model="optForm.codes" multiple filterable remote clearable collapse-tags
                     :remote-method="remoteCode" :loading="codeOptLoading" :reserve-keyword="false"
                     placeholder="输入代码或名称搜索，可多选（留空=全市场）" style="width: 100%">
            <el-option v-for="o in codeOptions" :key="o.code" :label="o.label" :value="o.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="optDlg = false">取消</el-button>
        <el-button v-permission="'data-task:manage'" type="primary" @click="submitOptions">执行</el-button>
      </template>
    </el-dialog>

    <!-- 实时日志抽屉 -->
    <el-drawer v-model="logDrawer" :title="logTask ? `${TASK_LABEL[logTask.task_type] ?? logTask.task_type} · 实时日志` : '实时日志'"
               size="46%" class="log-drawer" @close="closeLogs">
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
        <div v-if="!logs.length" class="log-empty">暂无日志…</div>
      </div>
    </el-drawer>

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
            <PageSegmented v-model="settings.taskStatus" :options="[
              { label: '全部', value: 'all' },
              { label: '运行中', value: 'active' },
              { label: '失败项', value: 'failed' },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">默认排序</div>
            <PageSegmented v-model="settings.taskSort" :options="[
              { label: '时间', value: 'time' },
              { label: '状态', value: 'status' },
            ]" />
          </div>
        </PageSettingSection>
        <PageSettingSection title="日志与显示">
          <div class="setting-item">
            <div class="setting-label">采集日志筛选</div>
            <PageSegmented v-model="settings.logStatus" :options="[
              { label: '全部', value: 'all' },
              { label: '仅失败', value: 'failed' },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">更多选项默认任务</div>
            <PageSegmented v-model="settings.defaultTaskType" :options="[
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
.page-head h2 { margin: 0; font-size: 20px; }
/* 填满 LayoutHost 的 .v-grow；内部「顶部固定卡 + 底部双栏成长表」，放不下时整区内滚 */
.ingest-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ingest-top {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ingest-bottom {
  flex: 1 1 auto;
  min-height: 520px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
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
.setting-item { display: flex; flex-direction: column; gap: 8px; }
.setting-label { font-size: 14px; color: var(--page-settings-text-subtle); }
.page-sub { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.blk { margin-bottom: 16px; }
.blk-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.flt { display: flex; align-items: center; gap: 8px; }
.pager { display: flex; justify-content: flex-end; margin-top: 10px; }
.act-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.act { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 12px 14px; }
.act-t { font-weight: 600; }
.act-d { font-size: 12px; color: var(--el-text-color-secondary); margin: 4px 0 10px; }
.clk-tbl :deep(tbody tr) { cursor: pointer; }
.task-id { font-family: var(--el-font-family-mono, monospace); font-size: 12px; color: var(--el-text-color-secondary); }
.log-meta { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.lm-msg { font-size: 12px; color: var(--el-text-color-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lm-phase { font-size: 12px; color: var(--el-color-warning); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-body { flex: 1 1 auto; min-height: 0; overflow: auto; background: var(--el-fill-color-darker); border-radius: 6px; padding: 10px; font-family: var(--el-font-family-mono, monospace); font-size: 12px; }
.log-line { display: flex; gap: 10px; padding: 1px 0; }
.log-line.warn { color: #e6a23c; }
.log-line.error { color: #f56c6c; }
.lt { color: var(--el-text-color-secondary); flex-shrink: 0; }
.log-empty { color: var(--el-text-color-secondary); text-align: center; padding: 20px; }
:deep(.row-fail) { background: var(--el-color-danger-light-9); }
.fail-detail { color: #f56c6c; }
@media (max-width: 1280px) {
  .ingest-bottom {
    grid-template-columns: 1fr;
    min-height: unset;
  }
}
</style>

<!-- el-drawer 经 teleport 挂到 body，scoped 作用域属性不会带到抽屉根，
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

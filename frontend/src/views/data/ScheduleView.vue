<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  listSchedules, createSchedule, updateSchedule, setScheduleEnabled, deleteSchedule, runSchedule,
  getSources, testSources, SOURCE_LABEL, TASK_LABEL, ISSUE_TYPE_LABEL, ISSUE_TYPES_ACTIVE,
  taskDisplayLabel, getSettingsView, saveSettings, resetSettings,
  type ScheduledJob, type ScheduledJobInput, type SourceStatus, type TaskType, type FreqType,
  type BoardIngestStage, type BoardTypeScope,
} from '@/api/data'
import AppRowActions from '@/components/AppRowActions.vue'
import type { AppRowAction } from '@/components/rowActions'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
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
  componentLayerValuesOf,
} = useRemoteLayoutConfig(scheduleLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

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
const WEEKDAYS = [
  { label: '一', value: 1 }, { label: '二', value: 2 }, { label: '三', value: 3 },
  { label: '四', value: 4 }, { label: '五', value: 5 }, { label: '六', value: 6 }, { label: '日', value: 7 },
]
// 需要额外参数的任务类型：指定日期采集要日期；历史补数可填年限。其余无需参数（全市场）。
function taskTypeOptions() {
  return taskTypes.value.map((v) => ({ value: v, label: TASK_LABEL[v] ?? v }))
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
  name: '', task_type: 'update' as TaskType,
  issue_type: 'null_close',
  board_mode: 'update' as 'update' | 'backfill',
  board_type: '' as BoardTypeScope,
  board_stages: ['dict', 'members', 'bar', 'fund'] as BoardIngestStage[],
  board_force_members: false,
  date_start: '', date_end: '', years: null as number | null, concurrency: null as number | null,
  freq_type: 'daily' as FreqType,
  time: '15:30', weekdays: [1, 2, 3, 4, 5] as number[], day: 1, cron: '',
  trading_day_only: true, enabled: true,
})
const dlgTitle = computed(() => (editingId.value ? '编辑定时任务' : '新建定时任务'))
// 采集类任务（逐股拉取）才有并发概念；评分维护/质检无需并发
const needsConcurrency = computed(() => ['update', 'backfill', 'ingest_date', 'ingest_codes'].includes(form.task_type))
watch(() => form.task_type, (type, prev) => {
  if (type === 'audit_cleanup') form.trading_day_only = false
  else if (prev === 'audit_cleanup' && !editingId.value) form.trading_day_only = true
})

function openCreate() {
  editingId.value = ''
  Object.assign(form, {
    name: '', task_type: 'update', issue_type: qualityIssueTypes.value[0] || 'null_close',
    board_mode: 'update', board_type: '', board_stages: ['dict', 'members', 'bar', 'fund'],
    board_force_members: false,
    date_start: '', date_end: '', years: null, concurrency: null,
    freq_type: 'daily', time: '15:30', weekdays: [1, 2, 3, 4, 5], day: 1, cron: '',
    trading_day_only: true, enabled: true,
  })
  dlg.value = true
}

function openEdit(j: ScheduledJob) {
  editingId.value = j.id
  Object.assign(form, {
    name: j.name, task_type: j.task_type,
    issue_type: j.params?.issue_type || qualityIssueTypes.value[0] || 'null_close',
    board_mode: j.params?.mode === 'backfill' ? 'backfill' : 'update',
    board_type: j.params?.board_type === 'concept' || j.params?.board_type === 'industry'
      ? j.params.board_type : '',
    board_stages: Array.isArray(j.params?.only) && j.params.only.length
      ? j.params.only.filter((x): x is BoardIngestStage => ['dict', 'members', 'bar', 'fund'].includes(x))
      : ['dict', 'members', 'bar', 'fund'],
    board_force_members: j.params?.force_members === true,
    date_start: j.params?.date_start || '', date_end: j.params?.date_end || '',
    years: j.params?.years ?? null, concurrency: j.params?.concurrency ?? null,
    freq_type: j.freq_type,
    time: j.freq_config?.time || '15:30',
    weekdays: j.freq_config?.weekdays?.length ? [...j.freq_config.weekdays] : [1, 2, 3, 4, 5],
    day: j.freq_config?.day ?? 1,
    cron: j.freq_config?.cron || '',
    trading_day_only: j.trading_day_only, enabled: j.enabled,
  })
  dlg.value = true
}

function buildPayload(): ScheduledJobInput | null {
  if (!form.name.trim()) { ElMessage.warning('请填写任务名称'); return null }
  const params: Record<string, unknown> = {}
  if (form.task_type === 'ingest_date') {
    if (!form.date_start) { ElMessage.warning('指定日期采集需填写起始日期'); return null }
    params.date_start = form.date_start
    params.date_end = form.date_end || form.date_start
  } else if (form.task_type === 'backfill' && form.years) {
    params.years = form.years
  } else if (form.task_type === 'fix') {
    if (!form.issue_type) { ElMessage.warning('质检问题恢复需选择问题类型'); return null }
    params.issue_type = form.issue_type
  } else if (form.task_type === 'board') {
    if (!form.board_stages.length) { ElMessage.warning('请至少选择一项板块采集内容'); return null }
    params.mode = form.board_mode
    params.only = form.board_stages
    if (form.board_type) params.board_type = form.board_type
    if (form.board_force_members && form.board_stages.includes('members')) params.force_members = true
  }
  if (needsConcurrency.value && form.concurrency) params.concurrency = form.concurrency
  const fc: Record<string, unknown> = {}
  if (form.freq_type === 'daily') fc.time = form.time
  else if (form.freq_type === 'weekly') {
    if (!form.weekdays.length) { ElMessage.warning('每周任务请至少选一个星期'); return null }
    fc.weekdays = [...form.weekdays].sort((a, b) => a - b); fc.time = form.time
  } else if (form.freq_type === 'monthly') { fc.day = form.day; fc.time = form.time }
  else if (form.freq_type === 'cron') {
    if (!form.cron.trim()) { ElMessage.warning('请填写 cron 表达式'); return null }
    fc.cron = form.cron.trim()
  }
  return {
    name: form.name.trim(), task_type: form.task_type, params,
    freq_type: form.freq_type, freq_config: fc,
    trading_day_only: form.trading_day_only, enabled: form.enabled,
  }
}

async function save() {
  const payload = buildPayload()
  if (!payload) return
  saving.value = true
  try {
    if (editingId.value) { await updateSchedule(editingId.value, payload); ElMessage.success('定时任务已更新') }
    else { await createSchedule(payload); ElMessage.success('定时任务已创建') }
    dlg.value = false
    await load()
  } catch { /* 拦截器弹错 */ } finally { saving.value = false }
}

async function toggleEnabled(j: ScheduledJob) {
  togglingId.value = j.id
  try {
    await setScheduleEnabled(j.id, !j.enabled)
    await load()
  } catch { /* 拦截器弹错 */ } finally { togglingId.value = '' }
}

async function remove(j: ScheduledJob) {
  try {
    await ElMessageBox.confirm(`确认删除定时任务「${j.name}」？删除后不再自动触发。`, '删除定时任务', { type: 'warning' })
  } catch { return }
  try { await deleteSchedule(j.id); ElMessage.success('已删除'); await load() } catch { /* */ }
}

async function runNow(j: ScheduledJob) {
  try {
    await ElMessageBox.confirm(
      `立即执行一次「${j.name}」（${taskDisplayLabel(j.task_type, j.params)}）？不等定时时间点直接触发；`
      + `任务会按自身规则执行；采集类任务在非交易日 / 当日数据未就绪时会自行跳过实际拉取。`,
      '立即执行', { type: 'warning' })
  } catch { return }
  try {
    await runSchedule(j.id)
    ElMessage.success('已触发，前往任务中心查看实时日志')
    router.push('/data/ingest')
  } catch { /* 409 等由拦截器弹出 */ }
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
    loadError.value = getErrorMessage(error, '定时任务加载失败')
  } finally { loading.value = false }
}

onMounted(async () => { await Promise.all([load(), loadSources(false)]) })
</script>

<template>
  <LayoutHost :layout="scheduleEffective">
    <template #action>
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        任务调度
        <HelpTip title="这页管什么？" :width="440">
          ① <b>定时任务</b>——自定义多条定时任务（数据采集 / 评分维护 / 数据质检 / 按问题类型恢复 / 审计清理），
          各自设置频率（每日/每周/每月/cron）、是否仅交易日执行，可启停、立即执行；触发记录在「数据采集」任务中心，
          标注「定时·任务名」。<br />
          ② <b>数据源健康</b>——AKShare / BaoStock / 同花顺板块源的连通性。
        </HelpTip>
      </h2>
      <p class="page-subtitle">自定义定时任务（采集/评分/质检/恢复/审计清理），支持每日/每周/每月/cron，仅交易日可选。</p>
      </div>
      <div class="page-head-actions">
        <el-button
          v-permission="'data-schedule:manage'"
          data-testid="schedule-create"
          type="primary"
          @click="openCreate"
        >新建定时任务</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <div class="schedule-body">
      <!-- ① 定时任务列表 -->
      <el-card shadow="never" class="blk jobs-card">
        <template #header>
          <div class="blk-head"><span>定时任务</span>
            <span class="hint">到点自动创建对应任务；仅交易日的任务在非交易日跳过。</span></div>
        </template>
        <AppStateBlock
          v-if="loading && !jobs.length"
          state="loading"
          title="正在加载定时任务…"
        />
        <AppStateBlock
          v-else-if="loadError"
          state="error"
          :title="jobs.length ? '定时任务刷新失败' : '定时任务加载失败'"
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
          <AppTableColumn v-if="jobColVisible('freq')" label="频率" prop="freq" show-overflow-tooltip sortable="custom">
            <template #default="{ row }"><span data-testid="schedule-frequency">{{ row.freq_text }}</span></template>
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
              <el-switch v-permission="'data-schedule:manage'" :model-value="row.enabled" :loading="togglingId === row.id" @change="toggleEnabled(row)" />
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('nextRun')" label="下次触发">
            <template #default="{ row }">{{ row.enabled ? fmtTime(row.next_run_time) : '—' }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="jobColVisible('lastRun')" label="最近触发">
            <template #default="{ row }">{{ fmtTime(row.last_run_at) }}</template>
          </AppTableColumn>
          <AppTableColumn label="操作" fixed="right">
            <template #default="{ row }">
              <AppRowActions :actions="scheduleRowActions(row)" :inline-limit="2" />
            </template>
          </AppTableColumn>
          <template #empty>暂无定时任务，点右上「新建定时任务」添加</template>
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
          <AppTableColumn label="操作" fixed="right">
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
          <el-select v-model="form.task_type" data-testid="schedule-task-type" style="width: 100%">
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
          test-id-prefix="schedule-board"
        />
        <template v-if="form.task_type === 'ingest_date'">
          <el-form-item label="起始日期">
            <TradeDatePicker v-model="form.date_start" placeholder="必填，仅可选交易日" />
          </el-form-item>
          <el-form-item label="结束日期">
            <TradeDatePicker v-model="form.date_end" placeholder="留空=仅起始日" clearable />
          </el-form-item>
        </template>
        <el-form-item v-if="form.task_type === 'backfill'" label="回填年限">
          <el-input-number v-model="form.years" :min="1" :max="30" placeholder="留空=默认" />
        </el-form-item>
        <el-form-item v-if="needsConcurrency" label="采集并发数">
          <el-input-number v-model="form.concurrency" :min="1" :max="16" placeholder="默认" />
          <span class="hint">留空＝沿用全局默认并发；填数则覆盖。调高提速，但总请求速率↑，注意免费源封禁风险</span>
        </el-form-item>

        <el-divider content-position="left" style="margin: 4px 0 14px">触发频率</el-divider>
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

        <el-divider content-position="left" style="margin: 4px 0 14px">选项</el-divider>
        <el-form-item label="仅交易日">
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
        >保存</el-button>
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
.src-status { display: inline-flex; align-items: center; gap: var(--app-space-control-gap); }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dot.up { background: var(--el-color-success); box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-success) 18%, transparent); }
.dot.down { background: var(--app-danger-text); box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-danger-text) 18%, transparent); }
.dot.unknown { background: var(--app-placeholder-text); }
.cookie-note { margin: 10px 0 0; font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); color: var(--el-text-color-secondary); }
.cookie-field-hint { display: block; margin-top: 4px; font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); color: var(--el-text-color-secondary); }
</style>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  listSchedules, createSchedule, updateSchedule, setScheduleEnabled, deleteSchedule, runSchedule,
  getSources, testSources, SOURCE_LABEL, TASK_LABEL,
  type ScheduledJob, type ScheduledJobInput, type SourceStatus, type TaskType, type FreqType,
} from '@/api/data'
import HelpTip from '@/components/HelpTip.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

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

// 抽屉「布局」段由 PageSettingsDrawer 按 config 自动渲染（本页无组件配置，仅布局段）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

const loading = ref(false)
const jobs = ref<ScheduledJob[]>([])
const taskTypes = ref<TaskType[]>([])
const togglingId = ref('')

const sources = ref<SourceStatus[]>([])
const pinging = ref(false)
const displaySources = computed(() => settings.sourceMode === 'primary' ? sources.value.filter((s) => s.role === 'primary') : sources.value)

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
  date_start: '', date_end: '', years: null as number | null, concurrency: null as number | null,
  freq_type: 'daily' as FreqType,
  time: '15:30', weekdays: [1, 2, 3, 4, 5] as number[], day: 1, cron: '',
  trading_day_only: true, enabled: true,
})
const dlgTitle = computed(() => (editingId.value ? '编辑定时任务' : '新建定时任务'))
// 采集类任务（逐股拉取）才有并发概念；评分维护/质检无需并发
const needsConcurrency = computed(() => ['update', 'backfill', 'ingest_date', 'ingest_codes'].includes(form.task_type))

function openCreate() {
  editingId.value = ''
  Object.assign(form, {
    name: '', task_type: 'update', date_start: '', date_end: '', years: null, concurrency: null,
    freq_type: 'daily', time: '15:30', weekdays: [1, 2, 3, 4, 5], day: 1, cron: '',
    trading_day_only: true, enabled: true,
  })
  dlg.value = true
}

function openEdit(j: ScheduledJob) {
  editingId.value = j.id
  Object.assign(form, {
    name: j.name, task_type: j.task_type,
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
      `立即执行一次「${j.name}」（${TASK_LABEL[j.task_type]}）？不等定时时间点直接触发；`
      + `采集类任务在非交易日 / 当日数据未就绪时会自行跳过实际拉取。`,
      '立即执行', { type: 'warning' })
  } catch { return }
  try {
    await runSchedule(j.id)
    ElMessage.success('已触发，前往任务中心查看实时日志')
    router.push('/data/ingest')
  } catch { /* 409 等由拦截器弹出 */ }
}

async function loadSources(ping = false) {
  pinging.value = ping
  try { sources.value = (ping ? await testSources() : await getSources(false)).sources } finally { pinging.value = false }
}

async function load() {
  loading.value = true
  try {
    const r = await listSchedules()
    jobs.value = r.jobs
    taskTypes.value = r.task_types
  } finally { loading.value = false }
}

onMounted(async () => { await Promise.all([load(), loadSources(false)]) })
</script>

<template>
  <LayoutHost :layout="scheduleEffective">
    <template #action>
    <div class="page-head">
      <h2>
        任务调度
        <HelpTip title="这页管什么？" :width="440">
          ① <b>定时任务</b>——自定义多条定时任务（增量更新 / 历史补数 / 指定日期采集 / 刷新评分 / 数据质检），
          各自设置频率（每日/每周/每月/cron）、是否仅交易日执行，可启停、立即执行；触发记录在「数据采集」任务中心，
          标注「定时·任务名」。<br />
          ② <b>数据源健康</b>——AKShare / BaoStock 的连通性。
        </HelpTip>
      </h2>
      <div class="page-head-actions">
        <el-button v-permission="'data-schedule:manage'" type="primary" @click="openCreate">新建定时任务</el-button>
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
        <el-table :data="jobs" size="small" class="jobs-tbl">
          <el-table-column label="名称" prop="name" min-width="140" show-overflow-tooltip />
          <el-table-column label="任务类型" width="120">
            <template #default="{ row }">{{ TASK_LABEL[row.task_type as TaskType] ?? row.task_type }}</template>
          </el-table-column>
          <el-table-column label="频率" prop="freq_text" min-width="150" show-overflow-tooltip />
          <el-table-column label="仅交易日" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.trading_day_only ? 'success' : 'info'" size="small" effect="plain">
                {{ row.trading_day_only ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="80" align="center">
            <template #default="{ row }">
              <el-switch v-permission="'data-schedule:manage'" :model-value="row.enabled" :loading="togglingId === row.id" @change="toggleEnabled(row)" />
            </template>
          </el-table-column>
          <el-table-column label="下次触发" width="160">
            <template #default="{ row }">{{ row.enabled ? fmtTime(row.next_run_time) : '—' }}</template>
          </el-table-column>
          <el-table-column label="最近触发" width="160">
            <template #default="{ row }">{{ fmtTime(row.last_run_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button v-permission="'data-schedule:manage'" type="primary" link size="small" @click="runNow(row)">立即执行</el-button>
              <el-button v-permission="'data-schedule:manage'" link size="small" @click="openEdit(row)">编辑</el-button>
              <el-button v-permission="'data-schedule:manage'" type="danger" link size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>暂无定时任务，点右上「新建定时任务」添加</template>
        </el-table>
      </el-card>

      <!-- ② 数据源健康 -->
      <el-card shadow="never" class="blk">
        <template #header>
          <div class="blk-head"><span>数据源健康</span>
            <el-button v-permission="'data-source:test'" size="small" type="primary" plain :loading="pinging" @click="loadSources(true)">测试连通</el-button></div>
        </template>
        <div v-for="s in displaySources" :key="s.source" class="src">
          <span class="dot" :class="s.up === true ? 'up' : s.up === false ? 'down' : 'unknown'" />
          <span class="src-name">{{ SOURCE_LABEL[s.source] ?? s.source }}</span>
          <el-tag size="small" effect="plain" :type="s.role === 'primary' ? 'primary' : 'info'">
            {{ s.role === 'primary' ? '主源' : '备用' }}
          </el-tag>
          <span class="src-state">{{ s.up === true ? '连通' : s.up === false ? '不可达' : '未测试' }}</span>
          <span class="src-meta">最近成功 {{ fmtTime(s.last_success_at) }} · 超时 {{ s.timeout_sec }}s</span>
        </div>
        <div v-if="!displaySources.length" class="app-empty-inline">点「测试连通」检查 AKShare / BaoStock 可达性</div>
      </el-card>
    </div>
    </template>

    <template #overlays>
    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dlg" :title="dlgTitle" width="520px">
      <el-form label-width="92px">
        <el-form-item label="任务名称">
          <el-input v-model="form.name" placeholder="如：盘后增量更新" maxlength="40" show-word-limit />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="form.task_type" style="width: 100%">
            <el-option v-for="o in taskTypeOptions()" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <!-- 按类型的动态参数 -->
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
          <PageSegmented v-model="form.freq_type" :options="FREQ_OPTIONS" />
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
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button v-permission="'data-schedule:manage'" type="primary" :loading="saving" @click="save">保存</el-button>
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
            <PageSegmented v-model="settings.timeMode" :options="[
              { label: '完整时间', value: 'full' },
              { label: '仅时分', value: 'hm' },
            ]" />
          </div>
        </PageSettingSection>
        <PageSettingSection title="数据源视图">
          <div class="setting-item">
            <div class="setting-label">显示范围</div>
            <PageSegmented v-model="settings.sourceMode" :options="[
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
.page-head h2 { margin: 0; font-size: 20px; }
.page-head-actions { display: flex; gap: 8px; align-items: center; }
/* 填满 LayoutHost 的 .v-grow；放不下时整区内滚（兜底阶梯第 3 级） */
.schedule-body { flex: 1 1 auto; overflow: auto; min-height: 0; display: flex; flex-direction: column; }
.jobs-card { margin-bottom: 16px; }
.jobs-card :deep(.el-card__body) { flex: 1 1 auto; min-height: 0; }
.jobs-tbl { width: 100%; }
.setting-item { display: flex; flex-direction: column; gap: 8px; }
.setting-label { font-size: 14px; color: var(--page-settings-text-subtle); }
.blk { margin-bottom: 16px; }
.blk:last-child { margin-bottom: 0; }
.blk-head { display: flex; justify-content: space-between; align-items: center; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); margin-left: 10px; }
.src { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.src:last-child { border-bottom: none; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dot.up { background: var(--el-color-success); box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-success) 18%, transparent); }
.dot.down { background: var(--app-danger-text); box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-danger-text) 18%, transparent); }
.dot.unknown { background: var(--app-placeholder-text); }
.src-name { font-weight: 600; min-width: 78px; }
.src-state { font-size: 13px; }
.src-meta { font-size: 12px; color: var(--el-text-color-secondary); margin-left: auto; }
</style>

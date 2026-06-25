<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { ElMessage } from 'element-plus'
import {
  getDataQuality, fixQualityIssue, ignoreQualityIssue, resetQualityIssue, recoverQualityBatch,
  markDelisted, createTask, getTask,
  ISSUE_TYPE_LABEL, SEVERITY_LABEL, ISSUE_STATUS_LABEL, ISSUE_LAYER, LAYER_LABEL, RECOVER_ACTION_LABEL,
  type DataQuality, type QualityIssue, type CheckupReport,
} from '@/api/data'
import { ElMessageBox } from 'element-plus'
import HelpTip from '@/components/HelpTip.vue'
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
  componentLayerValuesOf,
} = useRemoteLayoutConfig(qualityLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

// 抽屉写值由 ComponentAutoSettings 自动渲染；页面只保留排序/渲染要读的 getter。
const defaultSort = computed<'time' | 'severity'>(() => (componentValueOf('table', 'defaultSort') as 'time' | 'severity') ?? 'time')
const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
const loading = ref(false)
const data = ref<DataQuality | null>(null)
const page = ref(1)
const size = ref(DEFAULT_PAGE_SIZE)
// 类型/严重度/状态多选；默认勾选「未处理 + 修复中」（待办两态），code 为模糊文本
const filters = ref<{ issue_type: string[]; severity: string[]; status: string[]; code: string }>(
  { issue_type: [], severity: [], status: ['open', 'fixing'], code: '' })

const sevType: Record<string, 'danger' | 'warning' | 'info'> = { high: 'danger', mid: 'warning', low: 'info' }
const statType: Record<string, 'info' | 'warning' | 'success'> = {
  open: 'info', fixing: 'warning', resolved: 'success', ignored: 'info',
}
const displayList = computed(() => {
  let list = [...(data.value?.list ?? [])]
  if (settings.hideDoneRows) list = list.filter((row) => row.status !== 'resolved' && row.status !== 'ignored')
  if (defaultSort.value === 'severity') {
    const order = { high: 0, mid: 1, low: 2 }
    list.sort((a, b) => (order[a.severity as keyof typeof order] ?? 9) - (order[b.severity as keyof typeof order] ?? 9))
  }
  return list
})

function applyDefaultFilters() {
  filters.value.status = settings.defaultStatus === 'all'
    ? []
    : settings.defaultStatus === 'open'
      ? ['open']
      : ['open', 'fixing']
  filters.value.severity = settings.defaultSeverity === 'high' ? ['high'] : []
}

async function load() {
  loading.value = true
  try {
    data.value = await getDataQuality({
      issue_type: filters.value.issue_type.join(',') || undefined,
      severity: filters.value.severity.join(',') || undefined,
      status: filters.value.status.join(',') || undefined,
      code: filters.value.code.trim() || undefined,
      page: page.value, size: size.value,
    })
  } finally {
    loading.value = false
  }
}

// 筛选变更自动触发（列表交互标准）；多选数组用 deep 监听
watch(() => [filters.value.issue_type, filters.value.severity, filters.value.status],
  () => { page.value = 1; load() }, { deep: true })
watch(() => settings.defaultStatus, () => { applyDefaultFilters() })
watch(() => settings.defaultSeverity, () => { applyDefaultFilters() })

// 轮询任务到终态后回调（完成即自动刷新列表，闭环4）。返回任务结果供按真实结果提示。
async function waitTask(taskId: string): Promise<{ status: string; message: string; result?: Record<string, any> | null }> {
  for (;;) {
    const t = await getTask(taskId)
    if (['done', 'failed', 'interrupted'].includes(t.status)) return { status: t.status, message: t.message, result: t.result }
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

async function ignoreOne(row: QualityIssue) {
  try {
    await ignoreQualityIssue(row.id)
    ElMessage.success('已标记为正常/忽略，后续质检不再上报该问题')
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

async function runVerify() {
  try {
    const { task_id } = await createTask('verify')
    ElMessage.info('数据质检中…（也可在「数据采集 › 任务中心」看实时日志）')
    const t = await waitTask(task_id)
    ElMessage.success(t.message || '质检完成')
    await load()
  } catch { /* 并发/错误由拦截器提示 */ }
}

// 结构体检（checkup 任务）：本地 SQL 的结构/价格正确性/字段契约核查，结果以只读报告弹窗呈现。
// 与质检互补——能查出质检盲区（如在市股逐行 total_mv 缺失），但不写台账、无修复闭环。
const checkupRunning = ref(false)
const checkupOpen = ref(false)
const checkupReport = ref<CheckupReport | null>(null)
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
    const { count } = await recoverQualityBatch({
      issue_type: f.issue_type.length ? f.issue_type : undefined,
      severity: f.severity.length ? f.severity : undefined,
      code: f.code.trim() || undefined,
    })
    ElMessage.success(`已提交批量恢复 ${count} 条，前往任务中心查看进度（可终止）`)
    router.push('/data/ingest')   // 跳任务中心看进度/实时日志
  } catch { /* 400无匹配/409并发 由拦截器提示 */ } finally { batching.value = false }
}

onMounted(() => {
  applyDefaultFilters()
  // 支持从概览/总览带参下钻：?severity=high（按严重度）或 ?code=600000.SH（按个股）
  const sev = route.query.severity
  if (typeof sev === 'string' && ['high', 'mid', 'low'].includes(sev)) filters.value.severity = [sev]
  const code = route.query.code
  if (typeof code === 'string' && code) { filters.value.code = code; filters.value.status = [] }
  load()
})
</script>

<template>
  <LayoutHost :layout="qualityEffective">
    <template #action>
    <div class="lh-action">
    <div class="page-head">
      <h2>
        数据质量
        <HelpTip title="数据质量怎么来的、怎么处理？" :width="480">
          四层质量台账，每条问题按类型走对应恢复手段，<b>复检通过才标记「已解决」</b>（不会假装修好）。<br /><br />
          <b>四层口径：</b>L1 入库闸门 / L2 字段契约 / L3 正确性 / L4 覆盖鲜活。<br /><br />
          <b>问题来源：</b><br />
          ① 采集入库时自动记录（L1）：收盘价非法被丢弃、开高低回填；<br />
          ② 数据质检（本页「立即质检」=定时「数据质检」任务，同一方法）：市值缺失(L2)、异常涨跌/复权跳变(L3)、缺口/滞后(L4)；<br />
          ③ 恢复后复检通过 → 「已解决」。<br /><br />
          <b>恢复 / 标记正常：</b>缺口先按漏采重采，源端确无数据则确认为停牌（不再上报）；真实极端值（如新股首日大涨）可「标记正常」。
        </HelpTip>
      </h2>
      <div class="page-head-actions">
        <el-button type="warning" plain :loading="batching" :disabled="!canBatch"
                   :title="canBatch ? '' : '请先选择类型/严重度/代码再批量恢复'" @click="batchRecover">
          一键恢复
        </el-button>
        <el-button type="primary" plain @click="runVerify">立即质检</el-button>
        <el-button type="success" plain :loading="checkupRunning" @click="runCheckup">结构体检</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="filters.status" placeholder="状态" multiple clearable collapse-tags
                 collapse-tags-tooltip :max-collapse-tags="3" style="width: 240px">
        <el-option v-for="(l, k) in ISSUE_STATUS_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-select v-model="filters.severity" placeholder="严重度" multiple clearable collapse-tags
                 collapse-tags-tooltip :max-collapse-tags="3" style="width: 200px">
        <el-option v-for="(l, k) in SEVERITY_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-select v-model="filters.issue_type" placeholder="问题类型" multiple clearable collapse-tags
                 collapse-tags-tooltip :max-collapse-tags="3" style="width: 280px">
        <el-option v-for="(l, k) in ISSUE_TYPE_LABEL" :key="k" :label="l" :value="k" />
      </el-select>
      <el-input v-model="filters.code" placeholder="股票代码或名称" clearable style="width: 180px"
                @keyup.enter="() => { page = 1; load() }" @clear="() => { page = 1; load() }" />
      <div class="summary">
        <el-tag v-for="s in data?.summary ?? []" :key="s.issue_type" size="small" type="warning" effect="plain" class="sm-tag">
          {{ ISSUE_TYPE_LABEL[s.issue_type] ?? s.issue_type }}: {{ s.n }}
        </el-tag>
      </div>
    </div>
    </div>
    </template>

    <template #main>
    <el-card shadow="never">
      <el-table :data="displayList" size="small" height="100%" v-loading="loading"
                :row-class-name="rowClass">
        <el-table-column v-if="colVisible('severity')" label="严重度" width="90">
          <template #default="{ row }">
            <el-tag :type="sevType[row.severity] ?? 'info'" size="small" effect="dark">{{ SEVERITY_LABEL[row.severity] ?? row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="colVisible('code')" label="代码" prop="code" width="110" />
        <el-table-column v-if="colVisible('name')" label="名称" prop="name" width="100" show-overflow-tooltip />
        <el-table-column v-if="colVisible('date')" label="日期" width="110">
          <template #default="{ row }">{{ (row.trade_date || '—').slice(0, 10) }}</template>
        </el-table-column>
        <el-table-column v-if="colVisible('layer')" label="层" width="64">
          <template #default="{ row }">
            <el-tooltip :content="LAYER_LABEL[ISSUE_LAYER[row.issue_type]] ?? '—'" placement="top">
              <span class="layer-tag">{{ ISSUE_LAYER[row.issue_type] ?? '—' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column v-if="colVisible('type')" label="类型" width="130">
          <template #default="{ row }">{{ ISSUE_TYPE_LABEL[row.issue_type] ?? row.issue_type }}</template>
        </el-table-column>
        <el-table-column v-if="colVisible('detail')" label="详情" prop="detail" show-overflow-tooltip />
        <el-table-column v-if="colVisible('status')" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statType[row.status] ?? 'info'" size="small" effect="plain">{{ ISSUE_STATUS_LABEL[row.status] ?? row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="colVisible('detectedAt')" label="检出时间" width="160">
          <template #default="{ row }">{{ (row.detected_at || '').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'open' || row.status === 'fixing'">
              <el-button type="primary" size="small" link
                         :loading="busyId === row.id" :disabled="busyId !== null"
                         @click="fixOne(row)">
                {{ row.status === 'fixing' && busyId !== row.id ? '处理中…'
                   : (RECOVER_ACTION_LABEL[row.issue_type] ?? '恢复') }}
              </el-button>
              <!-- 修复中且非本页正在处理 → 可能是孤儿状态（任务失败/中断/卡死），允许手动复位解套 -->
              <el-button v-if="row.status === 'fixing' && busyId !== row.id" type="warning" size="small" link
                         @click="resetOne(row)">复位</el-button>
              <el-button v-if="GAP_TYPES.includes(row.issue_type)" type="warning" size="small" link
                         :disabled="busyId !== null" @click="openDelist(row)">标记退市</el-button>
              <el-button type="info" size="small" link :disabled="busyId !== null"
                         @click="ignoreOne(row)">标记正常</el-button>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination layout="total, sizes, prev, pager, next" :total="data?.total ?? 0" background
                       :current-page="page" :page-size="size" :page-sizes="PAGE_SIZE_OPTIONS"
                       @current-change="(p: number) => { page = p; load() }"
                       @size-change="(s: number) => { size = s; page = 1; load() }" />
      </div>
    </el-card>
    </template>

    <template #overlays>
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
          <el-date-picker v-model="delistDate" type="date" value-format="YYYY-MM-DD"
                          format="YYYY年MM月DD日" placeholder="该股最后有效交易日" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="delistDlg = false">取消</el-button>
        <el-button type="warning" :loading="delisting" @click="confirmDelist">确认标记退市</el-button>
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
        <PageSettingSection title="默认筛选">
          <div class="setting-item">
            <div class="setting-label">状态筛选</div>
            <PageSegmented v-model="settings.defaultStatus" :options="[
              { label: '待办两态', value: 'todo' },
              { label: '仅未处理', value: 'open' },
              { label: '全部', value: 'all' },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">严重度筛选</div>
            <PageSegmented v-model="settings.defaultSeverity" :options="[
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
          <el-tag :type="checkupReport.all_ok ? 'success' : 'danger'" effect="dark" size="large">
            {{ checkupReport.all_ok ? '全部通过' : `${checkupReport.fails.length} 项未通过` }}
          </el-tag>
          <span class="checkup-score">{{ checkupReport.passed }} / {{ checkupReport.total }} 项通过</span>
          <span class="checkup-note">结构合法性 + 价格正确性 + 字段契约（本地核查，与质检台账互补，不写台账）</span>
        </div>
        <div v-for="g in checkupReport.groups" :key="g.group" class="checkup-group">
          <div class="checkup-group-title">{{ g.group }}</div>
          <div v-for="c in g.checks" :key="c.name" class="checkup-row" :class="{ bad: !c.ok }">
            <el-tag :type="c.ok ? 'success' : 'danger'" size="small" effect="plain" class="checkup-flag">
              {{ c.ok ? 'PASS' : 'FAIL' }}
            </el-tag>
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
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.page-head h2 { margin: 0; font-size: 20px; }
.setting-item { display: flex; flex-direction: column; gap: 8px; }
.setting-label { font-size: 14px; color: var(--page-settings-text-subtle); }
.page-sub { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.qm { color: var(--el-color-primary); cursor: help; margin-left: 4px; }
.layer-tag { font-family: var(--el-font-family-mono, monospace); font-size: 12px; color: var(--el-text-color-secondary); }
.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.summary { margin-left: auto; }
.sm-tag { margin-left: 6px; }
.muted { color: var(--el-text-color-secondary); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
:deep(.row-done) { opacity: 0.55; }
.checkup-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.checkup-score { font-size: 15px; font-weight: 600; }
.checkup-note { color: var(--el-text-color-secondary); font-size: 12px; flex-basis: 100%; }
.checkup-group { margin-bottom: 14px; }
.checkup-group-title { font-weight: 600; font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
.checkup-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
.checkup-row.bad { color: var(--el-color-danger); }
.checkup-flag { width: 48px; text-align: center; flex-shrink: 0; }
.checkup-name { flex-shrink: 0; }
.checkup-detail { color: var(--el-text-color-secondary); font-size: 12px; margin-left: auto; }
.checkup-row.bad .checkup-detail { color: var(--el-color-danger); }
</style>

<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  copyScoreProfile,
  getIndicatorRegistry,
  type IndicatorDef,
  type ScoreProfileSummary,
  type ScoreRunRow,
} from '@/api/scoreProfile'
import { browseBoardProfiles, listBoardProfiles, runBoardProfile } from '@/api/board'
import AppDataTable from '@/components/AppDataTable.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import ScoreGradeTag from '@/components/ScoreGradeTag.vue'
import SubScoreChips from '@/components/SubScoreChips.vue'
import StockAnalysisNameCell from '@/components/StockAnalysisNameCell.vue'
import RelatedBoardCell from '@/components/RelatedBoardCell.vue'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import StockAnalysisDefaultFields from '@/components/StockAnalysisDefaultFields.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useMarketMasterWidthRuntime } from '@/composables/useMarketMasterWidthRuntime'
import { useTradeDates } from '@/composables/useTradeDates'
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import { useStockAnalysisSelection } from '@/composables/useStockAnalysisSelection'
import { useStockAnalysisSession } from '@/composables/useStockAnalysisSession'
import { useUserPreference } from '@/composables/useUserPreference'
import {
  composeComponentRuntimeValueOf,
  useStockChartComponentConfig,
} from '@/composables/useStockChartComponentConfig'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import { downloadCsv } from '@/utils/csv'
import { ElMessage } from 'element-plus'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import {
  relatedBoardFirstLoadContext,
  mergeRelatedBoardResults,
  useRelatedBoardFirstLoad,
} from '@/composables/useRelatedBoardFirstLoad'
import { useStockSet } from '@/stores/stockSet'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import type { AssetBrowseParams, ProfileSummary } from '@/components/asset-search/types'
import {
  PRICE_COMPARE_METRIC_ORDER,
  type PriceCompareMetric,
} from '@/utils/marketCompare'
import { getApiErrorCode, getErrorMessage } from '@/utils/error'

// 列表页布局（原型 A）：操作区=头部（标题+控件），主内容区=榜单表格（撑满·表体内滚）。
// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const boardLayout = getPageLayout('board')
const {
  effective: boardEffective,
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
  remoteHydrated,
  whenRemoteHydrated,
  saveRemoteUserConfig,
  remoteSaveError,
} = useRemoteLayoutConfig(boardLayout)

// 设置抽屉由 PageSettingsDrawer 按元数据渲染；workspace 宽度、表格与图表均归入本页组件设置。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }
const { setCurrentMasterWidth, componentRuntimeValueOf: masterRuntimeValueOf } = useMarketMasterWidthRuntime()
const chartPreferences = useStockChartComponentConfig({
  componentValueOf,
  setComponentKnob,
  hydrated: remoteHydrated,
})
const componentRuntimeValueOf = composeComponentRuntimeValueOf(
  masterRuntimeValueOf,
  chartPreferences.componentRuntimeValueOf,
)
useLegacyStockChartPreferenceMigration({
  pageKey: 'board', componentSourceOf, setComponentKnob, whenRemoteHydrated,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value,
})

const router = useRouter()
const route = useRoute()
const stockSet = useStockSet()
const loading = ref(true)
const error = ref('')
const runDate = ref<string>('')
// topN 单向：抽屉默认值 → 页面会话 ref；主区改动只进会话态，不写回默认（DESIGN「设置抽屉」单向默认机制）。
const topN = ref(50)
const rows = ref<ScoreRunRow[]>([])
const syncingRunDate = ref(false)
const settingsOpen = ref(false)
const { dataMax, ensureLoaded: ensureTradeDatesLoaded } = useTradeDates()

// topN、分项达标分模式属榜单业务态偏好，保留在 usePageSettings；
// 列显隐与默认排序迁入组件配置层（slots.table.config.*），消除与 usePageSettings 的双入口（plan.md §13.3）。
const boardDefaults = {
  topN: 50,
  subScoreMode: 'full' as 'full' | 'brief' | 'hidden',
  defaultChartMode: 'compare' as 'compare' | 'kline',
  showAnalysisPanel: true,
  compareRange: 60,
  benchmarkCode: '000905.SH',
  compareMetrics: [...PRICE_COMPARE_METRIC_ORDER] as PriceCompareMetric[],
  defaultCompareMetric: 'cum' as PriceCompareMetric,
  adjustMode: 'qfq' as '' | 'qfq' | 'hfq',
}
const { settings, isDirty, reset } = usePageSettings('board', boardDefaults)
topN.value = Number(settings.topN)
const { validDefault: klineDefaultRange } = useKlinePrefs()
const {
  analysisPanelVisible,
  chartMode,
  compareRange,
  compareMetric,
  benchmarkCode,
  adjustMode,
  visibleCompareMetrics,
  klineRange,
} = useStockAnalysisSession(
  settings,
  klineDefaultRange,
)

// 排序单向：配置层 defaultSort 只提供默认值，列头排序只进会话覆盖（sessionSort），不写回配置层。
type BoardSort = 'score' | 'rank' | 'code'
const BOARD_SORT_PROPS: Record<string, BoardSort> = { total_score: 'score', rank: 'rank', code: 'code' }
const configuredSort = computed<BoardSort>(() => {
  const raw = componentValueOf('table', 'defaultSort')
  return raw === 'rank' || raw === 'code' ? raw : 'score'
})
const sessionSort = ref<BoardSort | null>(null)
watch(configuredSort, () => { sessionSort.value = null }) // 抽屉改默认 → 清会话覆盖跟随
const sortBy = computed<BoardSort>(() => sessionSort.value ?? configuredSort.value)
const elementDefaultSort = computed(() => {
  if (sortBy.value === 'rank') return { prop: 'rank', order: 'ascending' }
  if (sortBy.value === 'code') return { prop: 'code', order: 'ascending' }
  return { prop: 'total_score', order: 'descending' }
})
const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
function onTableSortChange({ prop }: { prop: string; order: string | null }): void {
  sessionSort.value = BOARD_SORT_PROPS[prop] ?? 'score'
}


// 评分规则方案（R3/R5/R7）：下拉加载「我的」，搜索抽屉可浏览可见资产；
// 榜单属于“选择即查看”页面，加载公开方案后直接形成只读选项并自动刷新。
const auth = useAuthStore()
const profiles = ref<ScoreProfileSummary[]>([])
const externalProfile = ref<ScoreProfileSummary | null>(null)
const profileRef = ref('')
function profileKey(p: ScoreProfileSummary): string {
  return p.profile_ref || p.id
}

// 「默认加载方案」偏好：在资产抽屉里把某个可见评分方案设为默认后，
// 下次进入本页且自己没有评分方案时，自动装载该方案进下拉框并刷新榜单（前提：没有自己的方案）。
// 复用既有 user_preference 通道（scope=feature / pageKey=board），不新建表/端点/权限。
interface BoardDefaultProfile {
  profile_ref: string
  id: string
  name: string
  version: number
  is_preset: boolean
  source: string | null
  owner_label: string | null
  readonly: boolean
}
const boardDefaultProfileDefaults: BoardDefaultProfile = {
  profile_ref: '',
  id: '',
  name: '',
  version: 0,
  is_preset: false,
  source: null,
  owner_label: null,
  readonly: true,
}
const defaultPref = useUserPreference<BoardDefaultProfile>({
  scope: 'feature',
  pageKey: 'board',
  prefKey: 'default-score-profile',
  defaults: boardDefaultProfileDefaults,
  localStorageKey: 'ai-stocks-board-default-profile',
})
const defaultItemKey = computed(() => defaultPref.value.profile_ref || defaultPref.value.id || '')
const curProfile = computed(() => (
  profiles.value.find((p) => profileKey(p) === profileRef.value)
  ?? (externalProfile.value && profileKey(externalProfile.value) === profileRef.value
    ? externalProfile.value : null)
))
const cacheStatus = ref('')
const canViewBoardProfiles = computed(() =>
  hasPermission(auth.role, auth.permissions, 'board:view'),
)
const canRecomputeCurrentBoard = computed(() => Boolean(
  curProfile.value
  && hasPermission(auth.role, auth.permissions, 'board:compute')
  && (
    auth.isSystem
    || curProfile.value.source === 'mine'
  )
))
const boardSelectRef = ref<InstanceType<typeof AssetProfileSelect> | null>(null)
async function fetchMineBoardProfiles(): Promise<ScoreProfileSummary[]> {
  if (!canViewBoardProfiles.value) return []
  return listBoardProfiles('mine')
}
function browseBoard(params: AssetBrowseParams) {
  return browseBoardProfiles(params)
}
function copyAnyBoardProfile(item: ProfileSummary) {
  // 榜单方案=评分方案，复制走评分 copy 端点（后端生成唯一 id）
  return copyScoreProfile(item.profile_ref || item.id)
}
function onProfileSelect(key: string) {
  // 任何选择变化（包括清空）都先让旧请求失效，避免无选中时被迟到响应重新写回榜单。
  loadSequence += 1
  clearAnalysisSelection()
  profileRef.value = key
  if (externalProfile.value && profileKey(externalProfile.value) !== key) {
    externalProfile.value = null
  }
  if (key) void load()
  else {
    rows.value = []
    cacheStatus.value = ''
    loading.value = false
  }
}
// 外部只读项与 mine 列表分离，避免清除后影响默认方案和空状态判断。
function onProfileLoaded(item: ProfileSummary) {
  externalProfile.value = item as ScoreProfileSummary
}
const profilesReady = ref(false)
const tradeDatesReady = ref(false)
let initialLoadStarted = false
async function maybeLoadInitialBoard() {
  if (initialLoadStarted || !profilesReady.value || !tradeDatesReady.value) return
  // 自己无方案且可能已设默认但偏好尚未 hydrated 时，先等远端偏好合并，别急着落空态；
  // 待 hydrated watch 触发后再走（tryApplyDefault 装载默认，或确认无默认后落空态）。
  if (!profiles.value.length && !defaultPref.hydrated.value && canViewBoardProfiles.value) return
  initialLoadStarted = true
  if (profileRef.value) await load()
  else loading.value = false
}

// 组件为列表唯一事实源：经 ready 接收「我的」列表；与交易日初始化汇合后只发起一次首屏请求。
async function onProfilesReady(list: ProfileSummary[]) {
  const recoveredFromError = profilesReady.value && !!error.value
  profiles.value = list as ScoreProfileSummary[]
  if (profiles.value.length && !profileRef.value) {
    profileRef.value = profileKey(profiles.value[0])
  }
  profilesReady.value = true
  error.value = ''
  // 自己无方案时尝试装载默认（偏好已 hydrated 则立即生效；否则由下方 watch 兜底）
  tryApplyDefault()
  if (recoveredFromError && profileRef.value) await load()
  else await maybeLoadInitialBoard()
}
// 偏好 hydrated 可能晚于 mine 列表 ready：任一就绪都重试默认装载与首屏汇合
watch([profilesReady, defaultPref.hydrated], () => {
  tryApplyDefault()
  void maybeLoadInitialBoard()
})
function onProfilesLoadFailed(message: string) {
  // 刷新失败时保留已成功加载的摘要与榜单；首屏本来为空，仍会自然进入全页错误态。
  profilesReady.value = true
  error.value = message
  loading.value = false
}
// 复制成功（P2-2）：组件回写完整 summary，并入 profiles 使 curProfile（标题/导出/榜单参数）可解析
function onProfileCopied(item: ProfileSummary) {
  const summary = item as ScoreProfileSummary
  if (!profiles.value.some((p) => profileKey(p) === profileKey(summary))) {
    profiles.value = [summary, ...profiles.value]
  }
}

// 设为/取消默认加载方案：写入用户偏好（reactive 逐字段赋值触发 useUserPreference 双写持久化）。
function onSetDefault(item: ProfileSummary | null) {
  if (!item) {
    defaultPref.reset()
    ElMessage.info('已取消默认加载方案')
    return
  }
  defaultPref.value.profile_ref = item.profile_ref || ''
  defaultPref.value.id = item.id
  defaultPref.value.name = item.name
  defaultPref.value.version = item.version
  defaultPref.value.is_preset = item.is_preset
  defaultPref.value.source = item.source ?? null
  defaultPref.value.owner_label = item.owner_label ?? null
  defaultPref.value.readonly = true
  ElMessage.success(`已将「${item.name}」设为默认加载方案`)
}

// 首屏默认装载：仅当自己没有评分方案（mine 空）+ 已设默认 + 偏好已 hydrated 时，
// 经选择器 applyLoaded 复用 selectLoaded 链路装载并触发榜单刷新。每次进入只尝试一次。
let defaultApplied = false
let pendingDefaultKey = ''
function tryApplyDefault() {
  if (defaultApplied) return
  if (!canViewBoardProfiles.value) return
  if (!profilesReady.value) return
  if (profiles.value.length) return
  if (!defaultPref.hydrated.value) return
  const snap = defaultPref.value
  const key = snap.profile_ref || snap.id
  if (!key) return
  defaultApplied = true
  pendingDefaultKey = key
  const item: ProfileSummary = {
    id: snap.id,
    profile_ref: snap.profile_ref || undefined,
    name: snap.name,
    version: snap.version,
    is_preset: snap.is_preset,
    source: (snap.source as ProfileSummary['source']) ?? undefined,
    owner_label: snap.owner_label,
    readonly: true,
  }
  boardSelectRef.value?.applyLoaded(item)
}

// 指标注册表：用于把指标 key 映射成中文名（分项达标分徽章）
const registry = ref<IndicatorDef[]>([])
function nameOf(key: string): string {
  return registry.value.find((d) => d.key === key)?.name_cn || key
}
// 分项 key 顺序 = 本次结果第一行 sub_scores 的键序
const subKeys = computed(() => (rows.value[0] ? Object.keys(rows.value[0].sub_scores || {}) : []))
const displayRows = computed(() => {
  const list = [...rows.value]
  if (sortBy.value === 'rank') list.sort((a, b) => a.rank - b.rank)
  else if (sortBy.value === 'code') list.sort((a, b) => a.code.localeCompare(b.code))
  else list.sort((a, b) => b.total_score - a.total_score)
  return list
})
const analysisSourceItems = computed(() => displayRows.value)
const analysisRefreshRevision = ref(0)
const {
  activeCode: activeAnalysisCode,
  activeItem: activeAnalysisItem,
  items: analysisItems,
  isPinned: isAnalysisPinned,
  togglePinned: toggleAnalysisPinned,
  select: selectAnalysisItem,
  activate: activateAnalysisCode,
  remove: removeAnalysisCode,
  clear: clearAnalysisSelection,
} = useStockAnalysisSelection(analysisSourceItems, {
  onLimitReached: (limit) => ElMessage.warning(`最多对比${limit}只股票`),
})
const boardListMeta = computed(() => (
  analysisPanelVisible.value ? '点击行切换走势' : '点击行查看详情'
))

function handleBoardRowClick(item: ScoreRunRow): void {
  if (analysisPanelVisible.value) selectAnalysisItem(item)
  else gotoStock(item)
}

function boardAnalysisRowClass({ row }: { row: ScoreRunRow }): string {
  return row.code === activeAnalysisCode.value ? 'stock-analysis-row--active' : ''
}

function openActiveAnalysisDetail(): void {
  const row = rows.value.find((item) => item.code === activeAnalysisCode.value)
  if (row) gotoStock(row)
}

const displaySubKeys = computed(() => {
  if (settings.subScoreMode === 'hidden') return []
  if (settings.subScoreMode === 'brief') return subKeys.value.slice(0, 3)
  return subKeys.value
})
const tableEmptyText = computed(() =>
  profileRef.value ? '当前条件暂无榜单数据' : '暂无可用评分方案',
)

watch(runDate, () => {
  if (!profileRef.value || syncingRunDate.value) return
  clearAnalysisSelection()
  load()
})
// topN 单向：抽屉默认值 → 会话 ref；主区改动只进会话态，不写回默认。
watch(() => settings.topN, (value) => {
  topN.value = Number(value)
  clearAnalysisSelection()
  if (profileRef.value) load()
})

function onTopNChange(): void {
  clearAnalysisSelection()
  void load()
}

let loadSequence = 0
const relatedBoardFirstLoad = useRelatedBoardFirstLoad(() => loadBoard(false, true))
const recomputing = ref(false)
async function loadBoard(force: boolean, background = false): Promise<boolean> {
  if (!profileRef.value) return false
  const selected = curProfile.value
  if (!selected) {
    if (!background) {
      error.value = '评分方案信息尚未加载完成，请重新选择'
      loading.value = false
    }
    return false
  }
  const sequence = ++loadSequence
  if (!background) {
    loading.value = true
    error.value = ''
  }
  try {
    const res = await runBoardProfile({
      ...(selected.profile_ref ? { profile_ref: selected.profile_ref } : { profile_id: selected.id }),
      run_date: runDate.value || undefined,
      top: topN.value,
      ...(force ? { force: true } : {}),
    })
    if (sequence !== loadSequence) return false
    if (background) mergeRelatedBoardResults(rows.value, res.list)
    else rows.value = res.list
    relatedBoardFirstLoad.observe(
      res.list,
      relatedBoardFirstLoadContext(res.list, res.run_date),
    )
    cacheStatus.value = res.cache_status || ''
    syncingRunDate.value = true
    runDate.value = res.run_date
    await nextTick()
    syncingRunDate.value = false
    if (!background && !res.list.length) ElMessage.info('无结果（可能该日无数据）')
    if (sequence === loadSequence && pendingDefaultKey === profileRef.value) pendingDefaultKey = ''
    return true
  } catch (e) {
    if (sequence !== loadSequence) return false
    const loadingDefault = pendingDefaultKey !== '' && pendingDefaultKey === profileRef.value
    // 只有后端明确返回“方案不存在/不可见”的业务 404 才清除默认偏好。
    // 服务重启、断网、超时、5xx 或其他权限异常都保留偏好，让用户可以重试。
    if (loadingDefault && getApiErrorCode(e) === 404) {
      pendingDefaultKey = ''
      defaultPref.reset()
      profileRef.value = ''
      rows.value = []
      cacheStatus.value = ''
      loading.value = false
      ElMessage.warning('默认加载方案已不可见（可能已被取消公开或删除），已清除默认设置')
      return false
    }
    if (!background) error.value = getErrorMessage(e, force ? '榜单重算失败' : '榜单加载失败')
    return false
  } finally {
    if (!background && sequence === loadSequence) loading.value = false
  }
}

function load() {
  return loadBoard(false)
}

async function refreshBoard(): Promise<void> {
  const completed = await load()
  if (completed) analysisRefreshRevision.value += 1
}

async function recomputeCurrentBoard(): Promise<void> {
  if (!canRecomputeCurrentBoard.value || recomputing.value) return
  recomputing.value = true
  try {
    const completed = await loadBoard(true)
    if (completed) ElMessage.success('所选交易日榜单已重算')
  } finally {
    recomputing.value = false
  }
}

function gotoStock(row: ScoreRunRow) {
  const items = displayRows.value.map((item) => ({ code: item.code, name: item.name }))
  stockSet.setSet('list', items, '每日榜单', '', {
    total: items.length,
    loadedPages: [1],
    pageSize: Math.max(items.length, 1),
    returnPath: '/board',
  })
  router.push(`/stocks/${row.code}`)
}

function exportCsv() {
  if (!rows.value.length) return
  const headers = ['排名', '代码', '名称', '板块', '综合分', '评级', ...subKeys.value.map((k) => nameOf(k))]
  const data = rows.value.map((r) => [
    r.rank, r.code, r.name ?? '', r.board ?? '', r.total_score, r.grade ?? '',
    ...subKeys.value.map((k) => Math.round(r.sub_scores[k] ?? 0)),
  ])
  downloadCsv(`每日榜单_${curProfile.value?.name ?? ''}_${runDate.value || 'latest'}.csv`, headers, data)
}

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    // 日期与指标并行加载；先显示数据最新交易日，再与选择器 ready 汇合，避免首屏重复请求。
    const [registryResult] = await Promise.all([
      getIndicatorRegistry(true),
      ensureTradeDatesLoaded(),
    ])
    registry.value = registryResult.items
    syncingRunDate.value = true
    if (!runDate.value && dataMax.value) runDate.value = dataMax.value
    await nextTick()
    syncingRunDate.value = false
    tradeDatesReady.value = true
    await maybeLoadInitialBoard()
  } catch (e) {
    error.value = (e as Error).message
    loading.value = false
  }
})
</script>

<template>
  <LayoutHost :layout="boardEffective">
    <template #action>
    <div class="lh-action">
    <div class="page-head">
      <div>
        <h2 class="app-page-title page-title-row">
          每日榜单
          <HelpTip title="榜单是怎么排出来的？" :width="420">
            <HelpTipItem question="榜单如何排序">
              <ul>
                <li>选择一个评分规则方案，对全市场中除 ST 外的每只股票按规则打分，再按综合分降序取 Top N。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem question="可以使用哪些方案">
              <ul>
                <li>可使用自己的方案、租户公开方案、全体公开方案或系统内置方案；每条规则由技术指标、权重和布尔/分段/线性达标打分方式组成，权重自动归一到 100%。</li>
              </ul>
            </HelpTipItem>
            <HelpTipItem warning>
              <ul>
                <li>全市场排序不设硬门槛，行情差时前排也可能只是“矮个里的高个”，应关注分数高低而非只看排名。</li>
              </ul>
            </HelpTipItem>
          </HelpTip>
        </h2>
        <p class="page-subtitle">
          <template v-if="runDate">交易日 {{ runDate }} · 已排除 ST</template>
          <template v-if="curProfile"> · 规则「{{ curProfile.name }}」 v{{ curProfile.version }}</template>
          <template v-if="cacheStatus"> · {{ cacheStatus === 'cached' ? '已缓存' : '已更新' }}</template>
        </p>
      </div>
      <div class="page-head-actions">
        <div class="ops">
          <el-button
            :loading="loading && !recomputing"
            :disabled="recomputing"
            type="primary"
            @click="refreshBoard"
          >刷新</el-button>
          <el-button
            v-if="canRecomputeCurrentBoard"
            v-permission="'board:compute'"
            data-testid="board-recompute-current"
            :loading="recomputing"
            :disabled="loading && !recomputing"
            @click="recomputeCurrentBoard"
          >重算当日</el-button>
          <el-button :disabled="!rows.length" @click="exportCsv">导出 CSV</el-button>
        </div>
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>

    <!-- 筛选条件（独立一行居左，与全站列表页 filter-card 规范一致；操作按钮留页头） -->
    <el-card shadow="never" class="filter-card">
      <AppControlRow class="filter-row">
        <span class="lbl">评分规则</span>
        <AssetProfileSelect
          ref="boardSelectRef"
          :model-value="profileRef"
          asset-label="评分方案"
          :fetch-mine="fetchMineBoardProfiles"
          :browse="browseBoard"
          :copy-item="copyAnyBoardProfile"
          copy-permission="score-profile:save"
          view-permission="board:view"
          placeholder="请选择评分方案"
          select-loaded
          :default-item-key="defaultItemKey"
          test-id="board-profile-select"
          style="width: 300px"
          @update:model-value="onProfileSelect"
          @loaded="onProfileLoaded"
          @ready="onProfilesReady"
          @load-failed="onProfilesLoadFailed"
          @copied-item="onProfileCopied"
          @set-default="onSetDefault"
        />
        <TradeDatePicker v-model="runDate" placeholder="默认最新交易日" />
        <span class="lbl">Top</span>
        <el-select v-model="topN" style="width: 88px" @change="onTopNChange">
          <el-option :value="20" label="20" />
          <el-option :value="50" label="50" />
          <el-option :value="100" label="100" />
        </el-select>
      </AppControlRow>
    </el-card>

    </div>
    </template>

    <template #main>
    <AppStateBlock
      v-if="error"
      state="error"
      :title="rows.length ? '榜单刷新失败' : '榜单加载失败'"
      :description="error"
      retry
      @retry="load"
    />
    <MarketMasterDetailWorkspace
      v-else
      v-model:analysis-visible="analysisPanelVisible"
      eyebrow="评分榜单"
      :title="runDate || '最新交易日'"
      :meta="boardListMeta"
      list-aria-label="每日榜单结果"
      :default-master-width="Number(componentValueOf('workspace', 'masterWidth') ?? 1200)"
      @master-width-change="setCurrentMasterWidth"
      data-testid="board-market-workspace"
    >
      <template #list>
      <AppStateBlock
        v-if="loading && !rows.length"
        state="loading"
        title="正在加载榜单…"
      />
      <AppDataTable
        v-else
        kind="wide-table"
        :data="displayRows"
        :loading="loading"
        :empty-text="tableEmptyText"
        :border="tableBorder('table')"
        :default-sort="elementDefaultSort"
        :row-class-name="boardAnalysisRowClass"
        clickable
        @sort-change="onTableSortChange"
        @row-click="handleBoardRowClick"
      >
        <AppTableColumn label="#" prop="rank" sortable :sort-by="(r:any)=>r.rank">
          <template #default="{ row }">{{ row.rank }}</template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" sortable />
        <AppTableColumn v-if="colVisible('name')" label="名称" prop="name" role="entity" :leading-controls="1">
          <template #default="{ row }">
            <StockAnalysisNameCell
              :code="row.code"
              :name="row.name"
              :pinned="isAnalysisPinned(row.code)"
              @toggle="toggleAnalysisPinned(row)"
            />
          </template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('board')" label="板块" prop="board" />
        <AppTableColumn v-if="colVisible('relatedIndustry')" label="行业走势">
          <template #default="{ row }"><RelatedBoardCell :summary="row.related_boards" board-type="industry" :return-path="route.fullPath" /></template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('relatedConcept')" label="概念走势">
          <template #default="{ row }"><RelatedBoardCell :summary="row.related_boards" board-type="concept" :return-path="route.fullPath" /></template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('score')" label="综合分" prop="total_score" sortable :sort-by="(r:any)=>r.total_score">
          <template #default="{ row }">
            <strong class="score">{{ row.total_score }}</strong>
          </template>
        </AppTableColumn>
        <AppTableColumn v-if="colVisible('grade')" label="评级">
          <template #default="{ row }">
            <ScoreGradeTag v-if="row.grade" :grade="row.grade" />
            <span v-else class="muted">—</span>
          </template>
        </AppTableColumn>
        <AppTableColumn
          v-if="colVisible('subScores') && displaySubKeys.length"
          label="分项达标分"
        >
          <template #default="{ row }">
            <SubScoreChips
              :score-keys="displaySubKeys"
              :scores="row.sub_scores"
              :label-of="nameOf"
            />
          </template>
        </AppTableColumn>
      </AppDataTable>
      </template>
      <template #analysis>
        <StockAnalysisPanel
          v-model:mode="chartMode"
          v-model:compare-range="compareRange"
          v-model:compare-metric="compareMetric"
          v-model:benchmark-code="benchmarkCode"
          v-model:kline-range="klineRange"
          :active="activeAnalysisItem"
          :items="analysisItems"
          :compare-metrics="visibleCompareMetrics"
          :adjust-mode="adjustMode"
          :end-date="runDate"
          :slot2="chartPreferences.preferences.value.slot2"
          :slot3="chartPreferences.preferences.value.slot3"
          :height-ratios="chartPreferences.currentRatios.value"
          :refresh-revision="analysisRefreshRevision"
          @activate="activateAnalysisCode"
          @remove="removeAnalysisCode"
          @open-detail="openActiveAnalysisDetail"
          @ratio-draft="chartPreferences.handleRatioDraft"
          @ratio-commit="chartPreferences.handleRatioCommit"
        />
      </template>
    </MarketMasterDetailWorkspace>
    </template>

    <template #overlays>
    <PageSettingsDrawer
      v-model="settingsOpen"
      title="每日榜单"
      :dirty="isDirty || layoutDirty"
      page-key="board"
      :config="drawerConfig"
      :component-runtime-value-of="componentRuntimeValueOf"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="行情口径">
          <div class="setting-item">
            <div class="setting-label">复权模式</div>
            <PageSegmented v-model="settings.adjustMode" aria-label="复权模式" :options="[
              { label: '不复权', value: '' },
              { label: '前复权', value: 'qfq' },
              { label: '后复权', value: 'hfq' },
            ]" />
          </div>
        </PageSettingSection>
        <PageSettingSection title="默认结果">
          <div class="setting-item">
            <div class="setting-label">Top N</div>
            <PageSegmented v-model="settings.topN" aria-label="Top N" :options="[
              { label: '20', value: 20 },
              { label: '50', value: 50 },
              { label: '100', value: 100 },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">分项达标分</div>
            <PageSegmented v-model="settings.subScoreMode" aria-label="分项达标分" :options="[
              { label: '全显', value: 'full' },
              { label: '精简', value: 'brief' },
              { label: '隐藏', value: 'hidden' },
            ]" />
          </div>
          <StockAnalysisDefaultFields
            v-model:default-chart-mode="settings.defaultChartMode"
            v-model:compare-range="settings.compareRange"
            v-model:benchmark-code="settings.benchmarkCode"
            v-model:compare-metrics="settings.compareMetrics"
            v-model:default-compare-metric="settings.defaultCompareMetric"
            v-model:show-analysis-panel="settings.showAnalysisPanel"
          />
        </PageSettingSection>
        <KlineSettingSection />
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}
.page-title-row {
  display: flex;
  align-items: center;
}
.ops {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}
.ops .lbl {
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-table);
}
.score {
  color: var(--app-danger-text);
  font-size: var(--app-font-size-section-title);
}
.muted {
  color: var(--app-placeholder-text);
}
.clickable :deep(.el-table__row) {
  cursor: pointer;
}
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  font-size: var(--app-font-size-body);
  color: var(--page-settings-text-subtle);
}
</style>

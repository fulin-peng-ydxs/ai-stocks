<script setup lang="ts">
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PAGE_SIZE_OPTIONS, normalizePageSize } from '@/constants/pagination'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import { ArrowDown, Delete, Edit } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppDialog from '@/components/AppDialog.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import StockAnalysisNameCell from '@/components/StockAnalysisNameCell.vue'
import RelatedBoardCell from '@/components/RelatedBoardCell.vue'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
import StockAnalysisDefaultFields from '@/components/StockAnalysisDefaultFields.vue'
import StockGroupBatchActions from '@/components/StockGroupBatchActions.vue'
import StockGroupFavoriteButton from '@/components/StockGroupFavoriteButton.vue'
import {
  getStockMembershipOptions,
  listStocks,
  type StockBasic,
  type StockListParams,
  type StockMembershipOption,
} from '@/api/stocks'
import {
  deleteGroup,
  getGroup,
  listGroups,
  updateGroup,
  type GroupDetail,
  type GroupMember,
  type GroupSummary,
} from '@/api/stockGroup'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useMarketMasterRatioRuntime } from '@/composables/useMarketMasterRatioRuntime'
import { useStockSet, type StockListState } from '@/stores/stockSet'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import { useTradeDates } from '@/composables/useTradeDates'
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import { useStockAnalysisSelection } from '@/composables/useStockAnalysisSelection'
import { useStockBatchSelection, type StockBatchItem } from '@/composables/useStockBatchSelection'
import { useStockAnalysisSession } from '@/composables/useStockAnalysisSession'
import {
  composeComponentRuntimeValueOf,
  useStockChartComponentConfig,
} from '@/composables/useStockChartComponentConfig'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageEntry, getPageLayout, type SlotConfigMeta } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useFormChangeTracker } from '@/composables/useFormChangeTracker'
import {
  relatedBoardFirstLoadContext,
  mergeRelatedBoardResults,
  useRelatedBoardFirstLoad,
} from '@/composables/useRelatedBoardFirstLoad'
import { getErrorMessage } from '@/utils/error'
import { formatMoney } from '@/utils/money'
import {
  PRICE_COMPARE_METRIC_ORDER,
  type PriceCompareMetric,
} from '@/utils/marketCompare'
import {
  DEFAULT_STOCK_GROUP_COLOR,
  STOCK_GROUP_COLOR_PRESETS,
  isDefaultStockGroupMember,
  stockGroupTagStyle,
} from '@/utils/stockGroupPresentation'

const router = useRouter()
const route = useRoute()
const stockSet = useStockSet()
const { dataMax, ensureLoaded } = useTradeDates()
const settingsOpen = ref(false)
// 默认视图/排除 ST 属业务态偏好，保留 usePageSettings；
// 普通列表的默认排序、每页条数、列显隐迁入组件配置层 table slot（plan.md §13.3）。
// 分组视图为另一套列集，P7 已建模为独立可寻址 groupTable slot 并迁入组件配置层（见下 groupColVisible）。
const stocksDefaults = {
  defaultView: 'group' as 'list' | 'group',
  excludeSt: true,
  defaultChartMode: 'compare' as 'compare' | 'kline',
  showAnalysisPanel: true,
  compareRange: 60,
  benchmarkCode: '000905.SH',
  compareMetrics: [...PRICE_COMPARE_METRIC_ORDER] as PriceCompareMetric[],
  defaultCompareMetric: 'cum' as PriceCompareMetric,
  adjustMode: 'qfq' as '' | 'qfq' | 'hfq',
}
const { settings, isDirty, reset, whenHydrated } = usePageSettings('stocks', stocksDefaults)
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

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const stocksLayout = getPageLayout('stocks')
const {
  effective: stocksEffective,
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
  componentAllowedLayers,
  whenRemoteHydrated,
  remoteHydrated,
  saveRemoteUserConfig,
  remoteSaveError,
} = useRemoteLayoutConfig(stocksLayout)

// 设置抽屉由 PageSettingsDrawer 按元数据渲染；workspace 宽度、表格与图表均归入本页组件设置。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers, save: saveRemoteUserConfig }
const {
  setCurrentMasterRatioSample,
  componentRuntimeValueOf: masterRuntimeValueOf,
} = useMarketMasterRatioRuntime()
const marketWorkspaceRef = ref<{ openCompactAnalysis: () => boolean } | null>(null)
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
  pageKey: 'stocks', componentSourceOf, setComponentKnob, whenRemoteHydrated,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value,
})

// 普通列表表格的组件配置（slot 'table'）：抽屉写值由 ComponentAutoSettings 自动渲染；
// 这里只保留页面渲染/查询要读的派生值（默认排序、每页条数、列显隐 getter），写值统一经组件配置层。
const DEFAULT_TABLE_SORT = 'pct_chg:asc'
const defaultSortRaw = computed<string>(() => (componentValueOf('table', 'defaultSort') as string) || DEFAULT_TABLE_SORT)
const defaultSortBy = computed<string>(() => defaultSortRaw.value.split(':')[0] || 'pct_chg')
const defaultSortOrder = computed<'asc' | 'desc'>(() => (defaultSortRaw.value.split(':')[1] as 'asc' | 'desc') || 'asc')
const tableElementDefaultSort = computed(() => ({
  prop: defaultSortBy.value,
  order: defaultSortOrder.value === 'desc' ? 'descending' : 'ascending',
}))
const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}

// 分组视图表的排序/列显隐（slot 'groupTable'）：另一套列集，单一事实源走组件配置层，页面只读 getter。
const DEFAULT_GROUP_SORT = 'add_date:asc'
const groupDefaultSortRaw = computed<string>(() => (componentValueOf('groupTable', 'defaultSort') as string) || DEFAULT_GROUP_SORT)
const groupDefaultSortBy = computed<string>(() => groupDefaultSortRaw.value.split(':')[0] || 'add_date')
const groupDefaultSortOrder = computed<'asc' | 'desc'>(() => (groupDefaultSortRaw.value.split(':')[1] as 'asc' | 'desc') || 'asc')
const groupElementDefaultSort = computed(() => ({
  prop: groupDefaultSortBy.value,
  order: groupDefaultSortOrder.value === 'desc' ? 'descending' : 'ascending',
}))
const groupHidden = computed<string[]>(() => (componentValueOf('groupTable', 'hiddenColumns') as string[]) ?? [])
const {
  defaultPageSize: groupSizeCfg,
  pageSize: groupSize,
  changePageSize: changeGroupPageSize,
} = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('groupTable', 'pageSize'),
  shouldSync: () => inGroupMode.value && !restoringListState,
  resetPage: () => {
    groupPage.value = 1
  },
  reload: groupSearch,
})
function groupColVisible(key: string): boolean {
  return !groupHidden.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

// ── 查询条件（普通查询）──
const loading = ref(false)
const loadError = ref('')
const q = ref('')
const board = ref('')
const membershipBoardCode = ref('')
const membershipOptionRows = ref<StockMembershipOption[]>([])
const membershipOptionsLoading = ref(false)
const membershipOptionsError = ref('')
const membershipOptionsRequest = createLatestRequestGuard()
const membershipOptions = computed(() => {
  const duplicateNames = new Map<string, number>()
  for (const item of membershipOptionRows.value) {
    const key = `${item.board_type}:${item.name}`
    duplicateNames.set(key, (duplicateNames.get(key) ?? 0) + 1)
  }
  return membershipOptionRows.value.map((item) => {
    const typeLabel = item.board_type === 'industry' ? '行业' : '概念'
    const duplicate = (duplicateNames.get(`${item.board_type}:${item.name}`) ?? 0) > 1
    return {
      value: item.board_code,
      label: `${typeLabel}｜${item.name}${duplicate ? `（${item.board_code}）` : ''}`,
    }
  })
})
const excludeSt = useDefaultedSessionValue(computed(() => Boolean(settings.excludeSt)), {
  shouldSync: () => !restoringListState && board.value !== 'ST' && board.value !== '退市',
  onSynced: () => { void searchCurrentView() },
})
const tradeDate = ref('')          // 交易日期（默认最新，展示当日涨跌幅）
const sortBy = useDefaultedSessionValue(defaultSortBy, {
  shouldSync: () => !restoringListState && !inGroupMode.value,
  onSynced: () => { void search() },
})
const sortOrder = useDefaultedSessionValue(defaultSortOrder, {
  shouldSync: () => !restoringListState && !inGroupMode.value,
  onSynced: () => { void search() },
})
const page = ref(1)
const {
  defaultPageSize: defaultSize,
  pageSize: size,
  changePageSize,
} = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('table', 'pageSize'),
  shouldSync: () => !inGroupMode.value && !restoringListState,
  resetPage: () => {
    page.value = 1
  },
  reload: load,
})
const total = ref(0)
const rows = ref<StockBasic[]>([])
const relatedBoardFirstLoad = useRelatedBoardFirstLoad(async () => {
  if (inGroupMode.value) await loadGroupDetail(true)
  else await load(true)
})
const analysisRefreshRevision = ref(0)

// ST / 退市板块下「排除 ST」无意义（隐藏），其余板块默认排除 ST
watch(board, (b) => {
  excludeSt.value = b !== 'ST' && b !== '退市'
})
// 选交易日自动触发查询（初始化/恢复时设值不触发，避免重复加载）
watch(tradeDate, () => {
  if (restoringListState) return
  clearAnalysisSelection()
  searchCurrentView()
})

const stockListRequest = createLatestRequestGuard()
async function loadMembershipOptions(): Promise<void> {
  const requestId = membershipOptionsRequest.begin()
  membershipOptionsLoading.value = true
  membershipOptionsError.value = ''
  try {
    const data = await getStockMembershipOptions()
    if (!membershipOptionsRequest.isCurrent(requestId)) return
    membershipOptionRows.value = data.list
  } catch (error) {
    if (!membershipOptionsRequest.isCurrent(requestId)) return
    membershipOptionsError.value = getErrorMessage(error, '行业与概念选项加载失败')
  } finally {
    if (membershipOptionsRequest.isCurrent(requestId)) membershipOptionsLoading.value = false
  }
}

async function load(background = false) {
  const requestId = stockListRequest.begin()
  if (!background) {
    loading.value = true
    loadError.value = ''
  }
  try {
    const data = await listStocks({
      q: q.value || undefined,
      board: board.value || undefined,
      membership_board_code: membershipBoardCode.value || undefined,
      exclude_st: excludeSt.value,
      trade_date: tradeDate.value || undefined,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      page: page.value,
      size: size.value,
    })
    if (!stockListRequest.isCurrent(requestId)) return
    if (background) mergeRelatedBoardResults(rows.value, data.list)
    else rows.value = data.list
    relatedBoardFirstLoad.observe(
      data.list,
      relatedBoardFirstLoadContext(data.list, data.trade_date),
    )
    total.value = data.total
  } catch (error) {
    if (!stockListRequest.isCurrent(requestId)) return
    if (!background) loadError.value = getErrorMessage(error, '个股列表加载失败')
  } finally {
    if (!background && stockListRequest.isCurrent(requestId)) loading.value = false
  }
}
function search() {
  page.value = 1
  load()
}
// 服务端排序（跨全量，而非仅当前页）。单向：只改会话 ref，不写回配置层默认排序。
function onSortChange({ prop, order }: { prop: string; order: string | null }) {
  if (!order) {            // 取消排序 → 回默认涨跌幅正序
    sortBy.value = 'pct_chg'
    sortOrder.value = 'asc'
  } else {
    sortBy.value = prop
    sortOrder.value = order === 'descending' ? 'desc' : 'asc'
  }
  page.value = 1
  load()
}

// ── 分组查看 ──
const groups = ref<GroupSummary[]>([])
const activeGid = ref('')
const groupDetail = ref<GroupDetail | null>(null)
const groupLoading = ref(false)
const groupError = ref('')
const groupListError = ref('')
const inGroupMode = computed(() => !!activeGid.value)
const groupPage = ref(1)
const groupSortBy = useDefaultedSessionValue(groupDefaultSortBy, {
  shouldSync: () => !restoringListState && inGroupMode.value,
  onSynced: () => { void groupSearch() },
})
const groupSortOrder = useDefaultedSessionValue(groupDefaultSortOrder, {
  shouldSync: () => !restoringListState && inGroupMode.value,
  onSynced: () => { void groupSearch() },
})
const groupTotal = computed(() => groupDetail.value?.members.total ?? 0)
const lastActiveGid = ref('')
let groupLoadRevision = 0
// 首屏在远端组件默认值水合完成前保持恢复态，避免 watcher 抢跑并覆盖返回列表态。
let restoringListState = true

const auth = useAuthStore()
const canViewGroups = computed(() => hasPermission(auth.role, auth.permissions, 'stock-group:view'))
const canUpdateGroups = computed(() => hasPermission(
  auth.role,
  auth.permissions,
  'stock-group:member-update',
))
const settingsComponentSlotIds = computed(() => (
  canViewGroups.value ? undefined : ['table', 'chart']
))
const settingsComponentMetaOverrides = computed<Record<string, SlotConfigMeta> | undefined>(() => {
  if (canViewGroups.value) return undefined
  const tableColumns = getPageEntry('stocks')?.componentMeta?.table?.columns ?? []
  return {
    table: {
      columns: tableColumns.filter((column) => column.key !== 'groups'),
    },
  }
})
const visibleDefaultView = computed<'list' | 'group'>({
  get: () => (canViewGroups.value ? settings.defaultView : 'list'),
  set: (value) => {
    // 无分组权限时整个默认视图控件是只读安全投影，任何点击都不能覆盖隐藏的原偏好。
    if (!canViewGroups.value) return
    settings.defaultView = value
  },
})
const defaultViewOptions = computed<{ label: string; value: 'list' | 'group' }[]>(() => (
  canViewGroups.value
    ? [
        { label: '全市场', value: 'list' },
        { label: '分组', value: 'group' },
      ]
    : [{ label: '全市场', value: 'list' }]
))
async function reloadGroups() {
  // 次级加载按自身 view 码优雅降级：无 stock-group:view 的部分授权角色（如只授 stocks:view）
  // 不拉分组列表、也不因此 403 卡住个股行情主体。默认业务角色含该码不受影响。
  groupListError.value = ''
  if (!canViewGroups.value) {
    groups.value = []
    groupDetail.value = null
    if (activeGid.value) activeGid.value = ''
    return
  }
  try {
    groups.value = await listGroups()
  } catch (error) {
    groupListError.value = getErrorMessage(error, '分组列表加载失败')
    groups.value = []
    groupDetail.value = null
    if (activeGid.value) activeGid.value = ''
  }
}
const defaultGroup = computed(() => groups.value.find((g) => g.is_default))
function isDefaultFavorite(row: StockBasic): boolean {
  return isDefaultStockGroupMember(row.groups)
}
function updateDefaultFavorite(row: StockBasic, active: boolean): void {
  const group = defaultGroup.value
  if (!group) return
  const otherGroups = (row.groups ?? []).filter((item) => item.id !== group.id)
  row.groups = active
    ? [{ id: group.id, name: group.name, color: group.color, is_default: true }, ...otherGroups]
    : otherGroups
  group.member_count = Math.max(0, group.member_count + (active ? 1 : -1))
}
watch(activeGid, async (gid) => {
  cart.value = []   // 切换上下文清空选择
  if (!restoringListState) groupPage.value = 1
  if (!gid) {
    groupLoadRevision += 1
    groupDetail.value = null
    await load()
    return
  }
  lastActiveGid.value = gid
  if (!canViewGroups.value) {
    activeGid.value = ''
    return
  }
  await loadGroupDetail()
})
useDefaultedSessionValue(computed(() => settings.defaultView), {
  shouldSync: () => !restoringListState,
  onSynced: async (value) => {
    if (value === 'group') {
      changeView('group')
    } else if (activeGid.value) {
      changeView('list')
    } else {
      await load()
    }
  },
})
const currentView = computed<'list' | 'group'>(() => (inGroupMode.value ? 'group' : 'list'))
const viewOptions = [
  { label: '全市场', value: 'list' },
  { label: '分组', value: 'group' },
] satisfies { label: string; value: 'list' | 'group' }[]

function changeView(value: 'list' | 'group') {
  if (value === 'list') {
    if (activeGid.value) lastActiveGid.value = activeGid.value
    activeGid.value = ''
    return
  }
  if (!canViewGroups.value) return
  const remembered = groups.value.find((group) => group.id === lastActiveGid.value)
  const target = remembered || defaultGroup.value || groups.value[0]
  if (target) activeGid.value = target.id
}

function onViewChange(value: string | number | boolean) {
  if (value === 'list' || value === 'group') changeView(value)
}

function switchGroup(gid: string) {
  if (!canViewGroups.value || !gid) return
  activeGid.value = gid
}

function searchCurrentView() {
  clearAnalysisSelection()
  if (inGroupMode.value) groupSearch()
  else search()
}
const hasQueryFilters = computed(() => (
  q.value.trim() !== ''
  || board.value !== ''
  || membershipBoardCode.value !== ''
  || tradeDate.value !== (dataMax.value || '')
))

async function resetQueryFilters(): Promise<void> {
  if (!hasQueryFilters.value) return
  restoringListState = true
  q.value = ''
  board.value = ''
  membershipBoardCode.value = ''
  excludeSt.value = Boolean(settings.excludeSt)
  tradeDate.value = dataMax.value || ''
  page.value = 1
  groupPage.value = 1
  await nextTick()
  restoringListState = false
  clearAnalysisSelection()
  if (inGroupMode.value) await loadGroupDetail()
  else await load()
}

async function refreshStocks(): Promise<void> {
  await Promise.all([
    inGroupMode.value ? loadGroupDetail() : load(),
    loadMembershipOptions(),
  ])
  analysisRefreshRevision.value += 1
}
async function loadGroupDetail(background = false) {
  if (!activeGid.value) return
  if (!canViewGroups.value) {
    groupDetail.value = null
    activeGid.value = ''
    return
  }
  const gid = activeGid.value
  const revision = ++groupLoadRevision
  if (!background) {
    groupLoading.value = true
    groupError.value = ''
  }
  try {
    const detail = await getGroup(gid, {
      page: groupPage.value,
      size: groupSize.value,
      q: q.value || undefined,
      board: board.value || undefined,
      membership_board_code: membershipBoardCode.value || undefined,
      exclude_st: excludeSt.value,
      exclude_delisted: board.value !== '退市',
      trade_date: tradeDate.value || undefined,
      sort_by: groupSortBy.value,
      sort_order: groupSortOrder.value,
    })
    if (revision !== groupLoadRevision || gid !== activeGid.value) return
    if (background && groupDetail.value) {
      mergeRelatedBoardResults(groupDetail.value.members.list, detail.members.list)
    } else {
      groupDetail.value = detail
    }
    relatedBoardFirstLoad.observe(
      detail.members.list,
      relatedBoardFirstLoadContext(detail.members.list, (row) => row.last_date),
    )
  } catch (error) {
    if (revision !== groupLoadRevision || gid !== activeGid.value) return
    if (!background) groupError.value = getErrorMessage(error, '分组明细加载失败')
  } finally {
    if (!background && revision === groupLoadRevision) groupLoading.value = false
  }
}
const groupRows = computed<GroupMember[]>(() => groupDetail.value?.members.list ?? [])
function groupSearch() {
  groupPage.value = 1
  loadGroupDetail()
}
function onGroupSortChange({ prop, order }: { prop: string; order: string | null }) {
  if (!order) {
    groupSortBy.value = 'add_date'
    groupSortOrder.value = 'asc'
  } else {
    groupSortBy.value = prop
    groupSortOrder.value = order === 'descending' ? 'desc' : 'asc'
  }
  groupPage.value = 1
  loadGroupDetail()
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(2) + '%'
}
function fmtPrice(v: number | null | undefined): string {
  return formatMoney(v, { digits: 2 })
}
function fmtPctRatio(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return (v > 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
}
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'muted'
  return v > 0 ? 'up' : v < 0 ? 'down' : ''
}
// ── 持久化选择「购物车」：跨分页 / 跨搜索累积 ──
const cart = ref<StockBatchItem[]>([])
type StockAnalysisRow = { code: string; name: string | null; last_date?: string | null }
const curRows = computed<StockAnalysisRow[]>(() =>
  inGroupMode.value ? groupRows.value : rows.value,
)
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
} = useStockAnalysisSelection(curRows, {
  onLimitReached: (limit) => ElMessage.warning(`最多对比${limit}只股票`),
})
const analysisEndDate = computed(() => (
  inGroupMode.value ? activeAnalysisItem.value?.last_date || tradeDate.value : tradeDate.value
))
const analysisListTitle = computed(() => (
  inGroupMode.value ? groupDetail.value?.name || '分组股票' : tradeDate.value || '最新交易日'
))
const analysisListMeta = computed(() => (
  analysisPanelVisible.value ? '点击行切换走势' : '点击行查看详情'
))

function handleStockRowClick(item: StockAnalysisRow): void {
  if (marketWorkspaceRef.value?.openCompactAnalysis()) {
    selectAnalysisItem(item)
    return
  }
  if (analysisPanelVisible.value) selectAnalysisItem(item)
  else enterDetail(item.code)
}

function stockAnalysisRowClass({ row }: { row: { code: string } }): string {
  return row.code === activeAnalysisCode.value ? 'stock-analysis-row--active' : ''
}

function openActiveAnalysisDetail(): void {
  if (activeAnalysisCode.value) enterDetail(activeAnalysisCode.value)
}

const {
  isSelected: inCart,
  toggle,
  allCurrentSelected: allCurChecked,
  someCurrentSelected: someCurChecked,
  toggleAllCurrent: toggleAllCur,
} = useStockBatchSelection(curRows, cart)

// ── 进入详情：设置“当前集合” ──
function activeItems(): { code: string; name?: string | null }[] {
  if (inGroupMode.value) return groupRows.value.map((m) => ({ code: m.code, name: m.name }))
  return rows.value.map((r) => ({ code: r.code, name: r.name }))
}
function querySnapshot(): StockListParams {
  return {
    q: q.value || undefined,
    board: board.value || undefined,
    membership_board_code: membershipBoardCode.value || undefined,
    exclude_st: excludeSt.value,
    trade_date: tradeDate.value || undefined,
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
    size: Math.min(size.value, 100),
  }
}
function groupQuerySnapshot() {
  return {
    page: groupPage.value,
    size: Math.min(groupSize.value, 100),
    q: q.value || undefined,
    board: board.value || undefined,
    membership_board_code: membershipBoardCode.value || undefined,
    exclude_st: excludeSt.value,
    exclude_delisted: board.value !== '退市',
    trade_date: tradeDate.value || undefined,
    sort_by: groupSortBy.value,
    sort_order: groupSortOrder.value,
  }
}
function currentListState(): StockListState {
  return {
    mode: inGroupMode.value ? 'group' : 'list',
    q: q.value,
    board: board.value,
    membershipBoardCode: membershipBoardCode.value,
    excludeSt: excludeSt.value,
    tradeDate: tradeDate.value,
    sortBy: sortBy.value,
    sortOrder: sortOrder.value,
    page: page.value,
    size: size.value,
    activeGid: activeGid.value,
    groupPage: groupPage.value,
    groupSize: groupSize.value,
    groupQ: q.value,
    groupSortBy: groupSortBy.value,
    groupSortOrder: groupSortOrder.value,
  }
}
function enterDetail(code: string) {
  const label = inGroupMode.value ? (groupDetail.value?.name ?? '分组') : '查询结果'
  stockSet.setListState(currentListState())
  stockSet.setSet(
    inGroupMode.value ? 'group' : 'list',
    activeItems(),
    label,
    activeGid.value,
    inGroupMode.value
      ? {
          query: { kind: 'group', groupId: activeGid.value, params: groupQuerySnapshot() },
          total: groupTotal.value,
          loadedPages: [groupPage.value],
          pageSize: Math.min(groupSize.value, 100),
        }
      : {
          query: { kind: 'stocks', params: querySnapshot() },
          total: total.value,
          loadedPages: [page.value],
          pageSize: Math.min(size.value, 100),
        },
  )
  router.push(`/stocks/${code}`)
}
function viewCartOneByOne() {
  if (!cart.value.length) return
  stockSet.setSet('list', cart.value.map((c) => ({ code: c.code, name: c.name })), '勾选集')
  router.push(`/stocks/${cart.value[0].code}`)
}

async function onBatchGroupsChanged(
  groupId: string,
  action: 'create' | 'add' | 'remove',
): Promise<void> {
  await reloadGroups()
  if (inGroupMode.value && activeGid.value === groupId) await loadGroupDetail()
  else if (!inGroupMode.value && action === 'create') activeGid.value = groupId
}

// ── 编辑 / 删除分组 ──
const editVisible = ref(false)
const editForm = ref<{ name: string; group_date: string; description: string; color: string }>({
  name: '', group_date: '', description: '', color: DEFAULT_STOCK_GROUP_COLOR,
})
const groupSubmitPayload = () => ({
  name: editForm.value.name.trim(),
  group_date: editForm.value.group_date || undefined,
  description: editForm.value.description,
  color: editForm.value.color,
})
const { hasChanges: groupFormChanged, captureBaseline: captureGroupBaseline } = useFormChangeTracker(groupSubmitPayload)
function openEdit() {
  if (!groupDetail.value) return
  editForm.value = {
    name: groupDetail.value.name,
    group_date: groupDetail.value.group_date || '',
    description: groupDetail.value.description || '',
    color: groupDetail.value.color || DEFAULT_STOCK_GROUP_COLOR,
  }
  captureGroupBaseline()
  editVisible.value = true
}
async function doEdit() {
  if (!groupFormChanged.value) return
  if (!editForm.value.name.trim()) {
    ElMessage.warning('请填写分组名')
    return
  }
  await updateGroup(activeGid.value, groupSubmitPayload())
  ElMessage.success('已更新')
  editVisible.value = false
  await Promise.all([reloadGroups(), loadGroupDetail()])
}
async function doDeleteGroup() {
  if (!groupDetail.value) return
  if (groupDetail.value.is_default) return ElMessage.warning('默认自选分组不能删除')
  await ElMessageBox.confirm(`确认删除分组「${groupDetail.value.name}」？成员关系一并清除。`, '删除分组', { type: 'warning' })
  await deleteGroup(activeGid.value)
  ElMessage.success('已删除')
  await reloadGroups()
  lastActiveGid.value = ''
  const fallback = defaultGroup.value || groups.value[0]
  activeGid.value = fallback?.id || ''
}

onMounted(async () => {
  await Promise.all([
    whenHydrated(),
    whenRemoteHydrated(),
    auth.ensureLoaded().catch(() => undefined),
  ])
  await Promise.all([reloadGroups(), loadMembershipOptions()])
  const restore = route.query.restore === '1' ? stockSet.consumeListState() : null
  if (restore) {
    // 返回现场已由 store 原子消费，避免后续刷新重复覆盖当前页状态。
    restoringListState = true
    q.value = restore.mode === 'group' ? (restore.groupQ || restore.q) : restore.q
    board.value = restore.board
    membershipBoardCode.value = restore.membershipBoardCode || ''
    excludeSt.value = restore.excludeSt
    tradeDate.value = restore.tradeDate
    sortBy.value = restore.sortBy
    sortOrder.value = restore.sortOrder
    page.value = restore.page
    // size/groupSize 是组件配置层默认值派生的会话 ref，恢复上次浏览态时直接赋值会话值即可。
    size.value = normalizePageSize(restore.size)
    groupSize.value = normalizePageSize(restore.groupSize)
    groupPage.value = restore.groupPage
    groupSortBy.value = restore.groupSortBy
    groupSortOrder.value = restore.groupSortOrder
    activeGid.value = restore.mode === 'group' && canViewGroups.value ? restore.activeGid : ''
    restoringListState = false
    if (activeGid.value) await loadGroupDetail()
    else await load()
    router.replace('/stocks')
    return
  }
  const dg = defaultGroup.value
  excludeSt.value = Boolean(settings.excludeSt)
  sortBy.value = defaultSortBy.value
  sortOrder.value = defaultSortOrder.value
  size.value = defaultSize.value
  groupSize.value = groupSizeCfg.value
  groupSortBy.value = groupDefaultSortBy.value
  groupSortOrder.value = groupDefaultSortOrder.value
  // 交易日默认直接选中最新交易日（而非留空靠占位提示）
  await ensureLoaded()
  restoringListState = true
  tradeDate.value = dataMax.value || ''
  restoringListState = false
  if (canViewGroups.value && settings.defaultView === 'group' && dg) {
    activeGid.value = dg.id
  } else {
    await load()
  }
})
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="stocksEffective">
    <template #action>
    <div class="lh-action">
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        {{ menuPageTitle }}
        <HelpTip title="个股查询说明" :width="440">
          <HelpTipItem question="如何查询个股">
            <ul>
              <li>按代码、名称、上市板块或同花顺行业概念归属筛选，并支持分组查看与集合内翻页。</li>
            </ul>
          </HelpTipItem>
        </HelpTip>
      </h2>
      <p class="page-subtitle">按代码、名称、上市板块或行业概念归属筛选，可跨分页勾选与分组管理。</p>
      </div>
      <div class="page-head-actions">
        <AppStatusNotice
          v-if="groupListError"
          tone="warning"
          size="inline"
          title="分组列表加载失败"
          :description="groupListError"
          action-text="重新加载"
          @action="reloadGroups"
        />
        <AppStatusNotice
          v-if="membershipOptionsError"
          tone="warning"
          size="inline"
          title="行业与概念选项加载失败"
          :description="membershipOptionsError"
          action-text="重新加载"
          @action="loadMembershipOptions"
        />
        <el-button data-testid="stocks-refresh" :loading="loading || groupLoading || membershipOptionsLoading" @click="refreshStocks">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>

    <!-- 搜索 / 筛选（置顶）-->
    <el-card shadow="never" class="filter-card">
      <AppControlRow class="filter-row">
        <PageSegmented
          v-if="canViewGroups"
          :model-value="currentView"
          :options="viewOptions"
          aria-label="个股范围"
          test-id="stocks-list-scope"
          size="small"
          tone="primary"
          @update:model-value="onViewChange"
        />
        <TradeDatePicker v-model="tradeDate" placeholder="交易日期" clearable class="app-control-width-medium" />
        <el-select v-model="board" placeholder="全部板块" class="app-control-width-short" clearable @change="searchCurrentView">
          <el-option label="主板" value="主板" />
          <el-option label="创业板" value="创业板" />
          <el-option label="科创板" value="科创板" />
          <el-option label="ST 板块" value="ST" />
          <el-option label="退市板块" value="退市" />
        </el-select>
        <AppFilterSelect
          v-model="membershipBoardCode"
          :options="membershipOptions"
          :multiple="false"
          :disabled="membershipOptionsLoading || !!membershipOptionsError"
          placeholder="所属行业 / 概念"
          aria-label="所属行业或概念"
          class="app-control-width-long"
          @change="searchCurrentView"
        />
        <AppSearchInput v-model="q" placeholder="代码 / 名称" class="app-control-width-long" @search="searchCurrentView" />
        <el-button data-testid="stocks-reset-filters" :disabled="!hasQueryFilters" @click="resetQueryFilters">重置筛选</el-button>
      </AppControlRow>
    </el-card>

    <!-- 分组横幅 -->
    <el-card v-if="inGroupMode && groupDetail" shadow="never" class="group-banner">
      <div class="gb-row">
        <div class="gb-main">
          <el-dropdown trigger="click" @command="switchGroup">
            <el-button link type="primary" class="gb-name" data-testid="stocks-group-switcher">
              <span class="color-dot" :style="{ backgroundColor: groupDetail.color }" />
              {{ groupDetail.name }}
              <el-icon><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="g in groups"
                  :key="g.id"
                  :command="g.id"
                  :disabled="g.id === activeGid"
                >
                  <span class="group-option">
                    <span class="color-dot" :style="{ backgroundColor: g.color }" />
                    <span>{{ g.name }}（{{ g.member_count }}）</span>
                  </span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-tag size="small" effect="plain">建组 {{ groupDetail.group_date || '—' }}</el-tag>
          <el-tag v-if="groupDetail.is_default" size="small" type="danger" effect="plain">默认</el-tag>
          <el-tag size="small" effect="plain">{{ groupDetail.count }} 只</el-tag>
          <span class="gb-ret">整组涨幅
            <b :class="pctClass(groupDetail.avg_ret)">{{ fmtPctRatio(groupDetail.avg_ret) }}</b>
            <span class="gb-hint">（各股自加入日起·等权平均）</span>
          </span>
          <span v-if="groupDetail.description" class="gb-desc" :title="groupDetail.description">{{ groupDetail.description }}</span>
        </div>
        <div class="gb-ops">
          <AppIconButton
            v-permission="'stock-group:update'"
            label="编辑分组"
            size="sm"
            tone="primary"
            @click="openEdit"
          ><Edit /></AppIconButton>
          <AppIconButton
            v-permission="'stock-group:delete'"
            :label="groupDetail.is_default ? '默认自选分组不能删除' : '删除分组'"
            size="sm"
            tone="danger"
            :disabled="groupDetail.is_default"
            @click="doDeleteGroup"
          ><Delete /></AppIconButton>
        </div>
      </div>
    </el-card>
    </div>
    </template>

    <template #main>
    <MarketMasterDetailWorkspace
      ref="marketWorkspaceRef"
      v-model:analysis-visible="analysisPanelVisible"
      eyebrow="股票列表"
      :title="analysisListTitle"
      :meta="analysisListMeta"
      list-aria-label="个股行情列表"
      :default-master-ratio="Number(componentValueOf('workspace', 'masterRatio') ?? 45)"
      :master-ratio-profiles="componentValueOf('workspace', 'masterRatioProfiles')"
      analysis-drawer-title="股票走势分析"
      @master-ratio-sample-change="setCurrentMasterRatioSample"
      data-testid="stocks-market-workspace"
    >
      <template #list>
      <!-- 分组视图 -->
      <template v-if="inGroupMode">
        <AppStateBlock
          v-if="groupError"
          state="error"
          :title="groupDetail ? '分组明细刷新失败' : '分组明细加载失败'"
          :description="groupError"
          retry
          @retry="loadGroupDetail"
        />
        <AppDataTable v-else kind="wide-table" :data="groupRows" :loading="groupLoading" row-key="code"
          :border="tableBorder('groupTable')"
          :default-sort="groupElementDefaultSort"
          clickable
          :pagination="{ currentPage: groupPage, pageSize: groupSize, total: groupTotal, pageSizes: PAGE_SIZE_OPTIONS }"
          :row-class-name="stockAnalysisRowClass"
          @row-click="handleStockRowClick"
          @sort-change="onGroupSortChange"
          @page-change="(p:number)=>{ groupPage=p; loadGroupDetail() }"
          @size-change="changeGroupPageSize">
          <AppTableColumn role="structural">
            <template #header>
              <el-checkbox :model-value="allCurChecked" :indeterminate="someCurChecked" @change="toggleAllCur" />
            </template>
            <template #default="{ row }">
              <span @click.stop><el-checkbox :model-value="inCart(row.code)" @change="() => toggle(row)" /></span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('code')" label="代码" prop="code" sortable="custom" />
          <AppTableColumn v-if="groupColVisible('name')" label="名称" prop="name" role="entity" :leading-controls="1" sortable="custom">
            <template #default="{ row }">
              <StockAnalysisNameCell
                :code="row.code"
                :name="row.name"
                :pinned="isAnalysisPinned(row.code)"
                @toggle="toggleAnalysisPinned(row)"
              />
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('relatedIndustry')" label="行业走势">
            <template #default="{ row }"><RelatedBoardCell :summary="row.related_boards" board-type="industry" :return-path="route.fullPath" /></template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('relatedConcept')" label="概念走势">
            <template #default="{ row }"><RelatedBoardCell :summary="row.related_boards" board-type="concept" :return-path="route.fullPath" /></template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('price')" label="股价" prop="price" sortable="custom">
            <template #default="{ row }"><b :class="pctClass(row.pct_chg)">{{ fmtPrice(row.price) }}</b></template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('pct')" label="涨跌幅" prop="pct_chg" sortable="custom">
            <template #default="{ row }"><b :class="pctClass(row.pct_chg)">{{ fmtPct(row.pct_chg) }}</b></template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('ret')" label="截止涨幅" prop="ret" sortable="custom">
            <template #default="{ row }"><b :class="pctClass(row.ret)">{{ fmtPctRatio(row.ret) }}</b></template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('lastDate')" label="截至当前" prop="last_date" sortable="custom">
            <template #default="{ row }">{{ row.last_date || '—' }}</template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('addDate')" label="加入日期" prop="add_date" sortable="custom">
            <template #default="{ row }">{{ row.add_date || '—' }}</template>
          </AppTableColumn>
        </AppDataTable>
      </template>

      <!-- 普通查询 -->
      <template v-else>
        <AppStateBlock
          v-if="loadError"
          state="error"
          :title="rows.length ? '个股列表刷新失败' : '个股列表加载失败'"
          :description="loadError"
          retry
          @retry="load"
        />
        <AppDataTable v-else kind="wide-table" :data="rows" :loading="loading" row-key="code"
          :border="tableBorder('table')"
          clickable
          :pagination="{ currentPage: page, pageSize: size, total, pageSizes: PAGE_SIZE_OPTIONS }"
          :row-class-name="stockAnalysisRowClass"
          @row-click="handleStockRowClick"
          :default-sort="tableElementDefaultSort"
          @sort-change="onSortChange"
          @page-change="(p:number)=>{ page=p; load() }"
          @size-change="changePageSize">
          <AppTableColumn role="structural">
            <template #header>
              <el-checkbox :model-value="allCurChecked" :indeterminate="someCurChecked" @change="toggleAllCur" />
            </template>
            <template #default="{ row }">
              <span @click.stop><el-checkbox :model-value="inCart(row.code)" @change="() => toggle(row)" /></span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" sortable="custom" />
          <AppTableColumn
            v-if="colVisible('name')"
            label="名称"
            prop="name"
            role="entity"
            :leading-controls="canUpdateGroups && defaultGroup ? 2 : 1"
            sortable="custom"
          >
            <template #default="{ row }">
              <StockAnalysisNameCell
                :code="row.code"
                :name="row.name"
                :pinned="isAnalysisPinned(row.code)"
                @toggle="toggleAnalysisPinned(row)"
              >
                <template #leading>
                  <StockGroupFavoriteButton
                    v-if="canUpdateGroups && defaultGroup && row?.code"
                    :group-id="defaultGroup.id"
                    :code="row.code"
                    :name="row.name"
                    :active="isDefaultFavorite(row)"
                    :default-date="tradeDate || dataMax || ''"
                    :data-testid="`stocks-favorite-${row.code}`"
                    @changed="updateDefaultFavorite(row, $event)"
                  />
                </template>
                <el-tag v-if="row.is_st" type="danger" size="small" effect="plain">ST</el-tag>
              </StockAnalysisNameCell>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('price')" label="股价" prop="close" sortable="custom">
            <template #default="{ row }"><b :class="pctClass(row.pct_chg)">{{ fmtPrice(row.close) }}</b></template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('pct')" label="涨跌幅" prop="pct_chg" sortable="custom">
            <template #default="{ row }"><b :class="pctClass(row.pct_chg)">{{ fmtPct(row.pct_chg) }}</b></template>
          </AppTableColumn>
          <AppTableColumn v-if="canViewGroups && colVisible('groups')" label="所属分组">
            <template #default="{ row }">
              <span v-if="row.groups?.length" class="app-inline-info">
                <el-tag
                  v-for="g in row.groups"
                  :key="g.id"
                  size="small"
                  effect="plain"
                  class="box-tag"
                  :style="stockGroupTagStyle(g.color)"
                  role="button"
                  tabindex="0"
                  :aria-label="`查看分组：${g.name}`"
                  :title="`查看分组：${g.name}`"
                  @click.stop="switchGroup(g.id)"
                  @keydown.enter.stop.prevent="switchGroup(g.id)"
                  @keydown.space.stop.prevent="switchGroup(g.id)"
                >
                  {{ g.name }}
                </el-tag>
              </span>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('industry')" label="行业" prop="industry" sortable="custom">
            <template #default="{ row }">
              <el-tag v-if="row.industry" size="small" effect="plain" class="box-tag industry-tag">{{ row.industry }}</el-tag>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('board')" label="板块" prop="board" />
          <AppTableColumn v-if="colVisible('relatedIndustry')" label="行业走势">
            <template #default="{ row }"><RelatedBoardCell :summary="row.related_boards" board-type="industry" :return-path="route.fullPath" /></template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('relatedConcept')" label="概念走势">
            <template #default="{ row }"><RelatedBoardCell :summary="row.related_boards" board-type="concept" :return-path="route.fullPath" /></template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('status')" label="状态">
            <template #default="{ row }">
              <el-tag v-if="row.delist_date" type="info" effect="plain" size="small">退市</el-tag>
              <el-tag v-else :type="row.is_st ? 'danger' : 'success'" effect="plain" size="small">
                {{ row.is_st ? 'ST' : '正常' }}
              </el-tag>
            </template>
          </AppTableColumn>
        </AppDataTable>
      </template>
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
          :end-date="analysisEndDate"
          :slot2="chartPreferences.preferences.value.slot2"
          :slot3="chartPreferences.preferences.value.slot3"
          :height-ratios="chartPreferences.currentRatios.value"
          :refresh-revision="analysisRefreshRevision"
          @activate="activateAnalysisCode"
          @remove="removeAnalysisCode"
          @open-detail="openActiveAnalysisDetail"
          @ratio-draft="chartPreferences.handleRatioDraft"
          @ratio-commit="chartPreferences.handleRatioCommit"
          @workspace-resize="chartPreferences.handleWorkspaceResize"
        />
      </template>
    </MarketMasterDetailWorkspace>
    </template>

    <template #footer>
    <StockGroupBatchActions
      v-model="cart"
      :groups="groups"
      :default-date="dataMax || ''"
      :mode="inGroupMode ? 'remove' : 'assign'"
      :active-group-id="activeGid"
      @view="viewCartOneByOne"
      @changed="onBatchGroupsChanged"
    />
    </template>

    <template #overlays>
    <!-- 编辑分组 -->
    <AppDialog v-model="editVisible" title="编辑分组" size="medium">
      <el-form label-width="80px">
        <el-form-item label="分组名" required><el-input v-model="editForm.name" maxlength="30" show-word-limit /></el-form-item>
        <el-form-item label="建组日期"><TradeDatePicker v-model="editForm.group_date" clearable style="width: 200px" /></el-form-item>
        <el-form-item label="分组说明"><el-input v-model="editForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="颜色">
          <el-color-picker
            v-model="editForm.color"
            :disabled="groupDetail?.is_default"
            :predefine="STOCK_GROUP_COLOR_PRESETS"
          />
          <span class="f-hint">{{ groupDetail?.is_default ? '默认自选固定为红色' : '用于列表标签和分组状态识别' }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button v-permission="'stock-group:update'" type="primary" :disabled="!groupFormChanged" @click="doEdit">保存</el-button>
      </template>
    </AppDialog>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="个股查询"
      :dirty="isDirty || layoutDirty"
      page-key="stocks"
      :config="drawerConfig"
      :business-visible="true"
      :component-slot-ids="settingsComponentSlotIds"
      :component-runtime-value-of="componentRuntimeValueOf"
      :component-meta-overrides="settingsComponentMetaOverrides"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="行情口径">
          <PageSettingItem label="复权模式">
            <PageSegmented v-model="settings.adjustMode" aria-label="复权模式" :options="[
              { label: '不复权', value: '' },
              { label: '前复权', value: 'qfq' },
              { label: '后复权', value: 'hfq' },
            ]" />
          </PageSettingItem>
        </PageSettingSection>
        <PageSettingSection title="默认查询">
          <PageSettingItem label="默认视图">
            <PageSegmented
              v-model="visibleDefaultView"
              :options="defaultViewOptions"
              aria-label="默认视图"
              test-id="stocks-default-view"
            />
          </PageSettingItem>
          <PageToggleRow v-model="settings.excludeSt" label="默认排除 ST" />
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
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.group-option,
.gb-name {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
}
.color-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.group-banner {
  margin-bottom: 0;
}
.group-banner :deep(.el-card__body) {
  padding: var(--app-space-2) var(--app-space-3);
}
.gb-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.gb-main {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}
.gb-name {
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-section);
  padding: 0;
}
.box-tag {
  border-radius: 4px;
  font-weight: var(--app-font-weight-section);
}
.box-tag[role='button'] {
  cursor: pointer;
}
.box-tag[role='button']:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
.industry-tag {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.gb-ret {
  font-size: var(--app-font-size-table);
  color: var(--el-text-color-regular);
}
.gb-ret b {
  font-size: var(--app-font-size-data);
  margin: 0 2px;
}
.gb-hint,
.f-hint {
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
}
.gb-ops {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.gb-desc {
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

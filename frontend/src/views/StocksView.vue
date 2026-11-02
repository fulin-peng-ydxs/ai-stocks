<script setup lang="ts">
import { formatNumber } from '@/utils/numberFormat'
import { formatMarketPercent, formatReturn, marketValueClass } from '@/utils/marketValue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppForm from '@/components/AppForm.vue'
import AppFormHelp from '@/components/AppFormHelp.vue'
import {
  APP_BOTTOM_FLOATING_PLACEMENT,
  APP_BOTTOM_FLOATING_POPPER_OPTIONS,
} from '@/utils/floatingPlacement'
import { vKeyboardActivate } from '@/directives/keyboardActivate'
import AppAdvancedSearch from '@/components/AppAdvancedSearch.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PAGE_SIZE_OPTIONS, normalizePageSize } from '@/constants/pagination'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import { isSameSelectedFilter, normalizeAllSelectedFilter } from '@/utils/multiSelectFilter'
import { ArrowDown, Delete, Edit } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppActionHint from '@/components/AppActionHint.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppDialog from '@/components/AppDialog.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import StockAnalysisNameCell from '@/components/StockAnalysisNameCell.vue'
import StockStatusTag from '@/components/StockStatusTag.vue'
import RelatedBoardCell from '@/components/RelatedBoardCell.vue'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
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
let restoringListState = true
const STOCK_LISTED_BOARD_OPTIONS = [
  { value: '主板', label: '主板' },
  { value: '创业板', label: '创业板' },
  { value: '科创板', label: '科创板' },
]
const STOCK_LISTED_BOARD_VALUES = STOCK_LISTED_BOARD_OPTIONS.map((item) => item.value)
const STOCK_STATUS_OPTIONS = [
  { value: '正常上市', label: '正常上市' },
  { value: 'ST', label: 'ST' },
  { value: '退市', label: '退市' },
]
const STOCK_STATUS_VALUES = STOCK_STATUS_OPTIONS.map((item) => item.value)
// 默认视图与默认筛选属业务态偏好，保留 usePageSettings；
// 普通列表的默认排序、每页条数、列显隐迁入组件配置层 table slot（plan.md §13.3）。
// 分组视图为另一套列集，P7 已建模为独立可寻址 groupTable slot 并迁入组件配置层（见下 groupColVisible）。
const stocksDefaults = {
  defaultView: 'group' as 'list' | 'group',
  defaultListedBoards: [...STOCK_LISTED_BOARD_VALUES],
  defaultStatuses: ['正常上市'],
  adjustMode: 'qfq' as '' | 'qfq' | 'hfq',
}
const {
  settings, isDirty, reset, save: savePageSettings, whenHydrated, legacySnapshot,
} = usePageSettings('stocks', stocksDefaults, { deferUnknownFieldCleanup: true })
const defaultListedBoards = computed<string[]>({
  get: () => normalizeAllSelectedFilter(settings.defaultListedBoards, STOCK_LISTED_BOARD_VALUES),
  set: value => { settings.defaultListedBoards = normalizeAllSelectedFilter(value, STOCK_LISTED_BOARD_VALUES) },
})
const defaultStatuses = computed<string[]>({
  get: () => normalizeAllSelectedFilter(settings.defaultStatuses, STOCK_STATUS_VALUES),
  set: value => { settings.defaultStatuses = normalizeAllSelectedFilter(value, STOCK_STATUS_VALUES) },
})
const { validDefault: klineDefaultRange } = useKlinePrefs()

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
  computed(() => ({ ...chartPreferences.stockAnalysis.value, adjustMode: settings.adjustMode })),
  klineDefaultRange,
)
const componentRuntimeValueOf = composeComponentRuntimeValueOf(
  masterRuntimeValueOf,
  chartPreferences.componentRuntimeValueOf,
)
useLegacyStockChartPreferenceMigration({
  pageKey: 'stocks', analysisType: 'stock', componentSourceOf, setComponentKnob, whenRemoteHydrated,
  whenPageSettingsHydrated: whenHydrated, legacySnapshot,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value, savePageSettings,
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
const selectedListedBoards = ref<string[]>([...STOCK_LISTED_BOARD_VALUES])
const selectedStatuses = ref<string[]>(['正常上市'])
const listedBoardsDirty = ref(false)
const statusesDirty = ref(false)
const stOnlyContext = computed(() => (
  selectedStatuses.value.length === 1 && selectedStatuses.value[0] === 'ST'
))
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
const initializing = ref(true)
const relatedBoardFirstLoad = useRelatedBoardFirstLoad(async () => {
  if (inGroupMode.value) await loadGroupDetail(true)
  else await load({ silent: true, relatedBoardsOnly: true })
})
const analysisRefreshRevision = ref(0)

// 选交易日自动触发查询（初始化/恢复时设值不触发，避免重复加载）
watch(tradeDate, () => {
  if (restoringListState) return
  searchCurrentView()
})

const stockListRequest = createLatestRequestGuard()
type StockListLoadOptions = {
  silent?: boolean
  relatedBoardsOnly?: boolean
}

function stockListParams(): StockListParams {
  return {
    q: q.value || undefined,
    boards: selectedListedBoards.value.join(','),
    statuses: selectedStatuses.value.join(','),
    membership_board_code: membershipBoardCode.value || undefined,
    trade_date: tradeDate.value || undefined,
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
    page: page.value,
    size: size.value,
  }
}

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

async function load(options: StockListLoadOptions = {}) {
  const requestId = stockListRequest.begin()
  const params = stockListParams()
  const silent = options.silent === true
  if (!silent) {
    loading.value = true
    loadError.value = ''
  } else {
    // 静默请求成为最新请求时，不能遗留被它取代的前台 loading 状态。
    loading.value = false
  }
  try {
    const data = await listStocks(params)
    if (!stockListRequest.isCurrent(requestId)) return
    if (options.relatedBoardsOnly) mergeRelatedBoardResults(rows.value, data.list)
    else rows.value = data.list
    relatedBoardFirstLoad.observe(
      data.list,
      relatedBoardFirstLoadContext(data.list, data.trade_date),
    )
    total.value = data.total
  } catch (error) {
    if (!stockListRequest.isCurrent(requestId)) return
    if (!silent) loadError.value = getErrorMessage(error, '个股列表加载失败')
  } finally {
    if (!silent && stockListRequest.isCurrent(requestId)) loading.value = false
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
const viewSwitching = ref(false)
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
const auth = useAuthStore()
const canViewGroups = computed(() => hasPermission(auth.role, auth.permissions, 'stock-group:view'))
const canUpdateGroups = computed(() => hasPermission(
  auth.role,
  auth.permissions,
  'stock-group:member-update',
))
const settingsComponentSlotIds = computed(() => (
  canViewGroups.value ? undefined : ['filter', 'table', 'chart']
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
  try {
    if (!gid) {
      groupLoadRevision += 1
      groupDetail.value = null
      // 用户显式切换范围时统一展示前台加载态；静默更新只用于关联板块等后台补数。
      await load()
      return
    }
    lastActiveGid.value = gid
    if (!canViewGroups.value) {
      activeGid.value = ''
      return
    }
    await loadGroupDetail()
  } finally {
    // 只允许当前上下文的请求结束完整切换态，避免快速往返时旧请求提前恢复旧图。
    if (activeGid.value === gid) viewSwitching.value = false
  }
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
    if (!activeGid.value) return
    viewSwitching.value = true
    clearAnalysisSelection()
    // 主上下文切换不复用上次全市场列表，避免旧股票被重新自动选中并触发遮罩刷新。
    rows.value = []
    if (activeGid.value) lastActiveGid.value = activeGid.value
    activeGid.value = ''
    return
  }
  if (!canViewGroups.value) return
  if (activeGid.value) return
  const remembered = groups.value.find((group) => group.id === lastActiveGid.value)
  const target = remembered || defaultGroup.value || groups.value[0]
  if (target) {
    viewSwitching.value = true
    clearAnalysisSelection()
    groupDetail.value = null
    activeGid.value = target.id
  }
}

function onViewChange(value: string | number | boolean) {
  if (value === 'list' || value === 'group') changeView(value)
}

function switchGroup(gid: string) {
  if (!canViewGroups.value || !gid || gid === activeGid.value) return
  viewSwitching.value = true
  clearAnalysisSelection()
  groupDetail.value = null
  activeGid.value = gid
}

function searchCurrentView() {
  if (inGroupMode.value) groupSearch()
  else search()
}
function onListedBoardsChange(value: string[] | string): void {
  listedBoardsDirty.value = true
  selectedListedBoards.value = normalizeAllSelectedFilter(value, STOCK_LISTED_BOARD_VALUES)
  searchCurrentView()
}
function onStatusesChange(value: string[] | string): void {
  statusesDirty.value = true
  selectedStatuses.value = normalizeAllSelectedFilter(value, STOCK_STATUS_VALUES)
  searchCurrentView()
}
watch([defaultListedBoards, defaultStatuses], ([boards, statuses]) => {
  if (restoringListState) return
  let changed = false
  if (!listedBoardsDirty.value) {
    selectedListedBoards.value = [...boards]
    changed = true
  }
  if (!statusesDirty.value) {
    selectedStatuses.value = [...statuses]
    changed = true
  }
  if (changed) void searchCurrentView()
})
const hasQueryFilters = computed(() => (
  q.value.trim() !== ''
  || !isSameSelectedFilter(selectedListedBoards.value, defaultListedBoards.value)
  || !isSameSelectedFilter(selectedStatuses.value, defaultStatuses.value)
  || membershipBoardCode.value !== ''
  || tradeDate.value !== (dataMax.value || '')
))

async function resetQueryFilters(): Promise<void> {
  if (!hasQueryFilters.value) return
  restoringListState = true
  q.value = ''
  selectedListedBoards.value = [...defaultListedBoards.value]
  selectedStatuses.value = [...defaultStatuses.value]
  listedBoardsDirty.value = false
  statusesDirty.value = false
  membershipBoardCode.value = ''
  tradeDate.value = dataMax.value || ''
  page.value = 1
  groupPage.value = 1
  await nextTick()
  restoringListState = false
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
      boards: selectedListedBoards.value.join(','),
      statuses: selectedStatuses.value.join(','),
      membership_board_code: membershipBoardCode.value || undefined,
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
  return formatMarketPercent(v)
}
function fmtPrice(v: number | null | undefined): string {
  return formatMoney(v, { digits: 2 })
}
function fmtPctRatio(v: number | null | undefined): string {
  return formatReturn(v)
}
function pctClass(v: number | null | undefined): string {
  return marketValueClass(v)
}
// ── 持久化选择「购物车」：跨分页 / 跨搜索累积 ──
const cart = ref<StockBatchItem[]>([])
type StockAnalysisRow = { code: string; name: string | null; last_date?: string | null }
const curRows = computed<StockAnalysisRow[]>(() =>
  inGroupMode.value ? groupRows.value : rows.value,
)
// 全市场、分组及具体分组之间属于不同主上下文；切换完成前分析区必须为空，不能复用旧图。
const analysisSourceRows = computed<StockAnalysisRow[]>(() => (
  viewSwitching.value ? [] : curRows.value
))
const {
  activeCode: activeAnalysisCode,
  activeItem: activeAnalysisItem,
  items: analysisItems,
  selectionRevision: analysisSelectionRevision,
  isPinned: isAnalysisPinned,
  togglePinned: toggleAnalysisPinned,
  select: selectAnalysisItem,
  activate: activateAnalysisCode,
  remove: removeAnalysisCode,
  clear: clearAnalysisSelection,
} = useStockAnalysisSelection(analysisSourceRows, {
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
    boards: selectedListedBoards.value.join(','),
    statuses: selectedStatuses.value.join(','),
    membership_board_code: membershipBoardCode.value || undefined,
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
    boards: selectedListedBoards.value.join(','),
    statuses: selectedStatuses.value.join(','),
    membership_board_code: membershipBoardCode.value || undefined,
    trade_date: tradeDate.value || undefined,
    sort_by: groupSortBy.value,
    sort_order: groupSortOrder.value,
  }
}
function currentListState(): StockListState {
  return {
    mode: inGroupMode.value ? 'group' : 'list',
    q: q.value,
    boards: [...selectedListedBoards.value],
    statuses: [...selectedStatuses.value],
    membershipBoardCode: membershipBoardCode.value,
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
  stockSet.setResultSet(
    cart.value.map((c) => ({ code: c.code, name: c.name })),
    '勾选集',
    '/stocks?restore=1',
  )
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
  try {
    await ElMessageBox.confirm(`确认删除分组「${groupDetail.value.name}」？成员关系一并清除。`, '删除分组', { confirmButtonType: 'danger', type: 'warning' })
  } catch { return }
  await deleteGroup(activeGid.value)
  ElMessage.success('已删除')
  await reloadGroups()
  lastActiveGid.value = ''
  const fallback = defaultGroup.value || groups.value[0]
  activeGid.value = fallback?.id || ''
}

onMounted(async () => {
  try {
    await Promise.all([
      whenHydrated(),
      whenRemoteHydrated(),
      auth.ensureLoaded().catch(() => undefined),
    ])
    // 分组和交易日决定首屏内容，筛选项独立加载，不阻塞个股主列表。
    void loadMembershipOptions()
    await Promise.all([reloadGroups(), ensureLoaded()])
    const restore = route.query.restore === '1' ? stockSet.consumeListState() : null
    if (restore) {
      // 返回现场已由 store 原子消费，避免后续刷新重复覆盖当前页状态。
      restoringListState = true
      q.value = restore.mode === 'group' ? (restore.groupQ || restore.q) : restore.q
      const legacyValues = restore.boards?.length
        ? restore.boards
        : restore.board ? [restore.board] : []
      selectedListedBoards.value = normalizeAllSelectedFilter(
        legacyValues.filter(value => STOCK_LISTED_BOARD_VALUES.includes(value)),
        STOCK_LISTED_BOARD_VALUES,
      )
      const restoredStatuses = restore.statuses?.length
        ? restore.statuses
        : [
            ...(legacyValues.some(value => STOCK_LISTED_BOARD_VALUES.includes(value))
              || legacyValues.length === 0 ? ['正常上市'] : []),
            ...(legacyValues.includes('ST') || restore.excludeSt === false ? ['ST'] : []),
            ...(legacyValues.includes('退市') ? ['退市'] : []),
          ]
      selectedStatuses.value = normalizeAllSelectedFilter(
        restoredStatuses,
        STOCK_STATUS_VALUES,
      )
      listedBoardsDirty.value = true
      statusesDirty.value = true
      membershipBoardCode.value = restore.membershipBoardCode || ''
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
    selectedListedBoards.value = [...defaultListedBoards.value]
    selectedStatuses.value = [...defaultStatuses.value]
    listedBoardsDirty.value = false
    statusesDirty.value = false
    sortBy.value = defaultSortBy.value
    sortOrder.value = defaultSortOrder.value
    size.value = defaultSize.value
    groupSize.value = groupSizeCfg.value
    groupSortBy.value = groupDefaultSortBy.value
    groupSortOrder.value = groupDefaultSortOrder.value
    // 交易日默认直接选中最新交易日（而非留空靠占位提示）
    restoringListState = true
    tradeDate.value = dataMax.value || ''
    restoringListState = false
    if (canViewGroups.value && settings.defaultView === 'group' && dg) {
      activeGid.value = dg.id
    } else {
      await load()
    }
  } finally {
    initializing.value = false
  }
})
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :component-value-of="componentValueOf" :layout="stocksEffective">
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
      <AppControlRow class="page-head-actions">
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
      </AppControlRow>
    </div>

    <!-- 搜索 / 筛选（置顶）-->
    <el-card shadow="never" class="filter-card">
      <AppAdvancedSearch
        group="stocks"
        :states="{
          boards: { value: selectedListedBoards, options: STOCK_LISTED_BOARD_OPTIONS, active: selectedListedBoards.length !== STOCK_LISTED_BOARD_VALUES.length, clear: () => onListedBoardsChange([]) },
          status: { value: selectedStatuses, options: STOCK_STATUS_OPTIONS, active: selectedStatuses.length !== STOCK_STATUS_VALUES.length, clear: () => onStatusesChange([]) },
          membership: { value: membershipBoardCode, options: membershipOptions, clear: () => { membershipBoardCode = ''; searchCurrentView() } },
          keyword: { value: q, clear: () => { q = ''; searchCurrentView() } }
        }"
      >
        <template #context>
          <PageSegmented
            v-if="canViewGroups"
            :model-value="currentView"
            :options="viewOptions"
            aria-label="个股范围"
            test-id="stocks-list-scope"
            tone="primary"
            @update:model-value="onViewChange"
          />
          <TradeDatePicker v-model="tradeDate" placeholder="交易日期" clearable class="app-control-width-medium" />
        </template>
        <template #boards>
          <AppFilterSelect
            :model-value="selectedListedBoards"
            :options="STOCK_LISTED_BOARD_OPTIONS"
            :visible-tag-count="2"
            all-selected-label="全部板块"
            placeholder="上市板块"
            aria-label="按上市板块筛选"
            data-testid="stocks-boards"
            @change="onListedBoardsChange"
          />
        </template>
        <template #status>
          <AppFilterSelect
            :model-value="selectedStatuses"
            :options="STOCK_STATUS_OPTIONS"
            :visible-tag-count="2"
            all-selected-label="全部状态"
            placeholder="股票状态"
            aria-label="按股票状态筛选"
            data-testid="stocks-statuses"
            @change="onStatusesChange"
          />
        </template>
        <template #membership>
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
        </template>
        <template #keyword>
          <AppSearchInput v-model="q" placeholder="代码 / 名称" class="app-control-width-long" @search="searchCurrentView" />
        </template>
        <template #commands>
          <el-button data-testid="stocks-reset-filters" :disabled="!hasQueryFilters" @click="resetQueryFilters">重置筛选</el-button>
        </template>
      </AppAdvancedSearch>
    </el-card>

    <!-- 分组横幅 -->
    <el-card v-if="inGroupMode && groupDetail" shadow="never" class="group-banner app-card-compact">
      <div class="gb-row">
        <div class="gb-main">
          <el-dropdown
            trigger="click"
            @command="switchGroup"
            :placement="APP_BOTTOM_FLOATING_PLACEMENT"
            :popper-options="APP_BOTTOM_FLOATING_POPPER_OPTIONS"
            popper-class="app-option-popper stock-group-switch-popper"
          >
            <el-button text type="primary" class="gb-name" data-testid="stocks-group-switcher">
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
                  <span class="app-inline-info app-inline-info--fill app-inline-info--nowrap">
                    <span class="color-dot" :style="{ backgroundColor: g.color }" />
                    <span class="app-option-label">{{ g.name }}（{{ formatNumber(g.member_count, 'count') }}）</span>
                  </span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-tag type="info" size="small" effect="plain">建组 {{ groupDetail.group_date || '—' }}</el-tag>
          <el-tag v-if="groupDetail.is_default" size="small" type="danger" effect="plain">默认</el-tag>
          <el-tag type="info" size="small" effect="plain">{{ formatNumber(groupDetail.count, 'count') }} 只</el-tag>
          <span class="gb-ret">整组涨幅
            <b :class="marketValueClass(groupDetail.avg_ret, { input: 'ratio' })">{{ fmtPctRatio(groupDetail.avg_ret) }}</b>
            <span class="gb-hint">（各股自加入日起·等权平均）</span>
          </span>
          <span v-if="groupDetail.description" class="gb-desc" >{{ groupDetail.description }}</span>
        </div>
        <div class="gb-ops">
          <AppIconButton
            v-permission="'stock-group:update'"
            label="编辑分组"
            size="sm"
            tone="primary"
            @click="openEdit"
          ><Edit /></AppIconButton>
          <AppActionHint
            v-if="hasPermission(auth.role, auth.permissions, 'stock-group:delete')"
            :text="groupDetail.is_default ? '默认自选分组不能删除' : '删除分组'"
            :disabled="groupDetail.is_default"
            label="删除分组"
          >
            <AppIconButton
              v-permission="'stock-group:delete'"
              label="删除分组"
              :tooltip="false"
              size="sm"
              tone="danger"
              :disabled="groupDetail.is_default"
              @click="doDeleteGroup"
            ><Delete /></AppIconButton>
          </AppActionHint>
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
      <AppStateBlock
        v-if="viewSwitching || initializing"
        state="loading"
        :title="initializing ? '正在初始化个股行情' : inGroupMode ? '正在加载分组股票' : '正在加载全市场股票'"
        description="正在读取最新行情与筛选结果，请稍候。"
      />
      <!-- 分组视图 -->
      <template v-else-if="inGroupMode">
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
          <AppTableColumn v-if="groupColVisible('code')" label="代码" prop="code" sortable="custom">
            <template #default="{ row }">
              <span class="app-inline-info app-inline-info--nowrap">
                <span>{{ row.code }}</span>
                <StockStatusTag
                  v-if="!groupColVisible('name')"
                  :is-st="row.is_st"
                  :as-of-date="row.st_as_of_date"
                  :st-only-context="stOnlyContext"
                />
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="!groupColVisible('name')" label="操作" role="action-compact">
            <template #default="{ row }">
              <AppRowActions :actions="[{ key: 'view', kind: 'navigation', label: '查看走势', onClick: () => handleStockRowClick(row) }]" />
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('name')" label="名称" prop="name" role="entity" :leading-controls="1" sortable="custom">
            <template #default="{ row }">
              <StockAnalysisNameCell
                :code="row.code"
                :name="row.name"
                :pinned="isAnalysisPinned(row.code)"
                :is-st="row.is_st"
                :st-as-of-date="row.st_as_of_date"
                :st-only-context="stOnlyContext"
                @select="handleStockRowClick(row)"
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
            <template #default="{ row }"><b :class="marketValueClass(row.ret, { input: 'ratio' })">{{ fmtPctRatio(row.ret) }}</b></template>
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
          <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" sortable="custom">
            <template #default="{ row }">
              <span class="app-inline-info app-inline-info--nowrap">
                <span>{{ row.code }}</span>
                <StockStatusTag
                  v-if="!colVisible('name')"
                  :is-st="row.is_st"
                  :as-of-date="row.st_as_of_date"
                  :st-only-context="stOnlyContext"
                />
              </span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="!colVisible('name')" label="操作" role="action-compact">
            <template #default="{ row }">
              <AppRowActions :actions="[{ key: 'view', kind: 'navigation', label: '查看走势', onClick: () => handleStockRowClick(row) }]" />
            </template>
          </AppTableColumn>
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
                :is-st="row.is_st"
                :st-as-of-date="row.st_as_of_date"
                :st-only-context="stOnlyContext"
                @select="handleStockRowClick(row)"
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
                  @click.stop="switchGroup(g.id)"
                  v-keyboard-activate
                >
                  {{ g.name }}
                </el-tag>
              </span>
              <span v-else class="muted">—</span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('industry')" label="行业" prop="industry" sortable="custom">
            <template #default="{ row }">
              <el-tag v-if="row.industry" size="small" effect="plain" type="info" class="box-tag industry-tag">{{ row.industry }}</el-tag>
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
              <el-tag v-else type="success" effect="plain" size="small">上市</el-tag>
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
          :selection-revision="analysisSelectionRevision"
          :compare-metrics="visibleCompareMetrics"
          :adjust-mode="adjustMode"
          :end-date="analysisEndDate"
          :slot2="chartPreferences.preferences.value.slot2"
          :slot3="chartPreferences.preferences.value.slot3"
          :height-ratios="chartPreferences.currentRatios.value"
          v-model:return-measurement-mode="chartPreferences.returnMeasurementMode.value"
          v-model:kline-period="chartPreferences.klinePeriod.value"
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
      <AppForm label-width="80px">
        <el-form-item label="分组名" required><el-input v-model="editForm.name" maxlength="30" show-word-limit /></el-form-item>
        <el-form-item label="建组日期"><TradeDatePicker v-model="editForm.group_date" clearable style="width: 200px" /></el-form-item>
        <el-form-item label="分组说明"><el-input v-model="editForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="颜色">
          <el-color-picker
            v-model="editForm.color"
            :disabled="groupDetail?.is_default"
            :predefine="STOCK_GROUP_COLOR_PRESETS"
          />
          <AppFormHelp>{{ groupDetail?.is_default ? '默认自选固定为红色' : '用于列表标签和分组状态识别' }}</AppFormHelp>
        </el-form-item>
      </AppForm>
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
        <PageSettingSection section-key="market-caliber" title="行情口径">
          <PageSettingItem label="复权模式">
            <PageSegmented v-model="settings.adjustMode" aria-label="复权模式" :options="[
              { label: '不复权', value: '' },
              { label: '前复权', value: 'qfq' },
              { label: '后复权', value: 'hfq' },
            ]" />
          </PageSettingItem>
        </PageSettingSection>
        <PageSettingSection section-key="default-query" title="默认查询">
          <PageSettingItem label="默认视图">
            <PageSegmented
              v-model="visibleDefaultView"
              :options="defaultViewOptions"
              aria-label="默认视图"
              test-id="stocks-default-view"
            />
          </PageSettingItem>
          <PageSettingItem label="默认上市板块">
            <AppFilterSelect
              v-model="defaultListedBoards"
              :options="STOCK_LISTED_BOARD_OPTIONS"
              :visible-tag-count="2"
              all-selected-label="全部板块"
              placeholder="默认上市板块"
              aria-label="默认上市板块"
              data-testid="stocks-default-boards"
            />
          </PageSettingItem>
          <PageSettingItem label="默认股票状态">
            <AppFilterSelect
              v-model="defaultStatuses"
              :options="STOCK_STATUS_OPTIONS"
              :visible-tag-count="2"
              all-selected-label="全部状态"
              placeholder="默认股票状态"
              aria-label="默认股票状态"
              data-testid="stocks-default-statuses"
            />
          </PageSettingItem>
        </PageSettingSection>
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
  line-height: var(--app-line-height-data);
  font-weight: var(--app-font-weight-section);
  padding: 0;
}
.box-tag {
  border-radius: var(--app-radius-mark);
  font-weight: var(--app-font-weight-section);
}
.box-tag[role='button'] {
  cursor: pointer;
}
.box-tag[role='button']:focus-visible {
  outline: var(--app-focus-ring);
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
  line-height: var(--app-line-height-data);
  font-weight: var(--app-font-weight-section);
  margin: 0 2px;
}
.gb-hint {
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

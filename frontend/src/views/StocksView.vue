<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit } from '@element-plus/icons-vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
import { listStocks, type StockBasic, type StockListParams } from '@/api/stocks'
import {
  addMembers,
  createGroup,
  deleteGroup,
  getGroup,
  listGroups,
  removeMembers,
  updateGroup,
  type GroupDetail,
  type GroupMember,
  type GroupSummary,
} from '@/api/stockGroup'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { useStockSet, type StockListState } from '@/stores/stockSet'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import { useTradeDates } from '@/composables/useTradeDates'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageEntry, getPageLayout, type SlotConfigMeta } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getErrorMessage } from '@/utils/error'

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
}
const { settings, isDirty, reset } = usePageSettings('stocks', stocksDefaults)

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
} = useRemoteLayoutConfig(stocksLayout)

// 设置抽屉的「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

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
const defaultSize = computed<number>(() => {
  const value = Number(componentValueOf('table', 'pageSize'))
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_PAGE_SIZE
})
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
const groupSizeCfg = computed<number>(() => {
  const value = Number(componentValueOf('groupTable', 'pageSize'))
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_PAGE_SIZE
})
// 分组每页条数：单向，组件配置层默认值 → 会话 ref（分页器改动不写回）。
const groupSize = ref(groupSizeCfg.value)
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
const excludeSt = ref(Boolean(settings.excludeSt))        // 默认排除 ST
const tradeDate = ref('')          // 交易日期（默认最新，展示当日涨跌幅）
const sortBy = ref(defaultSortBy.value)      // 服务端排序字段（默认涨跌幅，初值取组件配置默认排序）
const sortOrder = ref<'asc' | 'desc'>(defaultSortOrder.value)  // 默认正序
const page = ref(1)
// 每页条数：单向，组件配置层默认值（slot 'table'.pageSize）→ 会话 ref；分页器改动不写回。
const size = ref(defaultSize.value)
const total = ref(0)
const rows = ref<StockBasic[]>([])

// ST / 退市板块下「排除 ST」无意义（隐藏），其余板块默认排除 ST
watch(board, (b) => {
  excludeSt.value = b !== 'ST' && b !== '退市'
})
// 选交易日自动触发查询（初始化/恢复时设值不触发，避免重复加载）
watch(tradeDate, () => { if (!restoringListState) search() })
watch(() => settings.excludeSt, (value) => {
  if (inGroupMode.value) return
  if (board.value === 'ST' || board.value === '退市') return
  excludeSt.value = Boolean(value)
  search()
})
watch(defaultSortBy, (value) => {
  if (inGroupMode.value) return
  if (sortBy.value === String(value)) return
  sortBy.value = String(value)
  search()
})
watch(defaultSortOrder, (value) => {
  if (inGroupMode.value) return
  if (sortOrder.value === value) return
  sortOrder.value = value
  search()
})
// 每页条数单向：抽屉/配置层默认值 → 会话 ref 并重载；分页器改动只进会话态（见模板 size-change）。
watch(defaultSize, (value) => {
  if (inGroupMode.value) return
  if (restoringListState) return
  size.value = value
  search()
})
watch(groupDefaultSortBy, (value) => {
  if (!inGroupMode.value) return
  if (groupSortBy.value === String(value)) return
  groupSortBy.value = String(value)
  groupSearch()
})
watch(groupDefaultSortOrder, (value) => {
  if (!inGroupMode.value) return
  if (groupSortOrder.value === value) return
  groupSortOrder.value = value
  groupSearch()
})
// 分组每页条数单向：配置层默认值 → 会话 ref 并重载；分页器改动只进会话态。
watch(groupSizeCfg, (value) => {
  if (!inGroupMode.value) return
  if (restoringListState) return
  groupSize.value = value
  groupSearch()
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await listStocks({
      q: q.value || undefined,
      board: board.value || undefined,
      exclude_st: excludeSt.value,
      trade_date: tradeDate.value || undefined,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      page: page.value,
      size: size.value,
    })
    rows.value = data.list
    total.value = data.total
  } catch (error) {
    loadError.value = getErrorMessage(error, '个股列表加载失败')
  } finally {
    loading.value = false
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
const groupQ = ref('')
const groupSortBy = ref(groupDefaultSortBy.value)
const groupSortOrder = ref<'asc' | 'desc'>(groupDefaultSortOrder.value)
const groupTotal = computed(() => groupDetail.value?.members.total ?? 0)
let restoringListState = false
let groupSearchTimer: ReturnType<typeof setTimeout> | null = null

const auth = useAuthStore()
const canViewGroups = computed(() => hasPermission(auth.role, auth.permissions, 'stock-group:view'))
const settingsComponentSlotIds = computed(() => (
  canViewGroups.value ? undefined : ['table']
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
        { label: '普通查询', value: 'list' },
        { label: '默认分组', value: 'group' },
      ]
    : [{ label: '普通查询', value: 'list' }]
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
watch(activeGid, async (gid) => {
  cart.value = []   // 切换上下文清空选择
  if (!restoringListState) groupPage.value = 1
  if (!gid) {
    groupDetail.value = null
    await load()
    return
  }
  if (!canViewGroups.value) {
    activeGid.value = ''
    return
  }
  await loadGroupDetail()
})
watch(() => settings.defaultView, async (value) => {
  if (restoringListState) return
  if (value === 'group') {
    const dg = defaultGroup.value
    if (canViewGroups.value && dg && dg.member_count > 0 && activeGid.value !== dg.id) activeGid.value = dg.id
  } else if (activeGid.value) {
    activeGid.value = ''
  } else {
    await load()
  }
})
async function loadGroupDetail() {
  if (!activeGid.value) return
  if (!canViewGroups.value) {
    groupDetail.value = null
    activeGid.value = ''
    return
  }
  groupLoading.value = true
  groupError.value = ''
  try {
    groupDetail.value = await getGroup(activeGid.value, {
      page: groupPage.value,
      size: groupSize.value,
      q: groupQ.value || undefined,
      sort_by: groupSortBy.value,
      sort_order: groupSortOrder.value,
    })
  } catch (error) {
    groupError.value = getErrorMessage(error, '分组明细加载失败')
  } finally {
    groupLoading.value = false
  }
}
const groupRows = computed<GroupMember[]>(() => groupDetail.value?.members.list ?? [])
function groupSearch() {
  if (groupSearchTimer) clearTimeout(groupSearchTimer)
  groupSearchTimer = null
  groupPage.value = 1
  loadGroupDetail()
}
function scheduleGroupSearch() {
  if (groupSearchTimer) clearTimeout(groupSearchTimer)
  groupSearchTimer = setTimeout(() => {
    groupSearch()
  }, 300)
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
  if (v === null || v === undefined) return '—'
  return v.toFixed(2)
}
function fmtPctRatio(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return (v > 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
}
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'muted'
  return v > 0 ? 'up' : v < 0 ? 'down' : ''
}
function tagStyle(color?: string) {
  const c = color || '#73757d'
  return {
    color: c,
    borderColor: c,
    backgroundColor: `${c}14`,
  }
}

// ── 持久化选择「购物车」：跨分页 / 跨搜索累积 ──
const cart = ref<{ code: string; name: string | null }[]>([])
const cartSet = computed(() => new Set(cart.value.map((c) => c.code)))
const cartCodes = computed(() => cart.value.map((c) => c.code))
function inCart(code: string): boolean {
  return cartSet.value.has(code)
}
function toggle(row: { code: string; name: string | null }) {
  const i = cart.value.findIndex((c) => c.code === row.code)
  if (i >= 0) cart.value.splice(i, 1)
  else cart.value.push({ code: row.code, name: row.name })
}
const curRows = computed<{ code: string; name: string | null }[]>(() =>
  inGroupMode.value ? groupRows.value : rows.value,
)
const allCurChecked = computed(() => curRows.value.length > 0 && curRows.value.every((r) => inCart(r.code)))
const someCurChecked = computed(() => curRows.value.some((r) => inCart(r.code)) && !allCurChecked.value)
function toggleAllCur(val: boolean) {
  if (val) {
    for (const r of curRows.value) if (!inCart(r.code)) cart.value.push({ code: r.code, name: r.name })
  } else {
    const codes = new Set(curRows.value.map((r) => r.code))
    cart.value = cart.value.filter((c) => !codes.has(c.code))
  }
}

// ── 进入详情：设置“当前集合” ──
function activeItems(): { code: string; name?: string | null }[] {
  if (inGroupMode.value) return groupRows.value.map((m) => ({ code: m.code, name: m.name }))
  return rows.value.map((r) => ({ code: r.code, name: r.name }))
}
function querySnapshot(): StockListParams {
  return {
    q: q.value || undefined,
    board: board.value || undefined,
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
    q: groupQ.value || undefined,
    sort_by: groupSortBy.value,
    sort_order: groupSortOrder.value,
  }
}
function currentListState(): StockListState {
  return {
    mode: inGroupMode.value ? 'group' : 'list',
    q: q.value,
    board: board.value,
    excludeSt: excludeSt.value,
    tradeDate: tradeDate.value,
    sortBy: sortBy.value,
    sortOrder: sortOrder.value,
    page: page.value,
    size: size.value,
    activeGid: activeGid.value,
    groupPage: groupPage.value,
    groupSize: groupSize.value,
    groupQ: groupQ.value,
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

// ── 存为新分组 ──
const createVisible = ref(false)
const createForm = ref<{ name: string; group_date: string; description: string; color: string }>({ name: '', group_date: '', description: '', color: '#73757d' })
const creating = ref(false)
function openCreate() {
  if (!cartCodes.value.length) return ElMessage.warning('请先勾选股票')
  createForm.value = { name: '', group_date: dataMax.value || '', description: '', color: '#73757d' }
  createVisible.value = true
}
async function doCreate() {
  if (!createForm.value.name.trim()) return ElMessage.warning('请输入分组名')
  creating.value = true
  try {
    const r = await createGroup({
      name: createForm.value.name.trim(),
      group_date: createForm.value.group_date || undefined,
      description: createForm.value.description,
      color: createForm.value.color,
      codes: cartCodes.value,
    })
    ElMessage.success(`已创建分组（${cartCodes.value.length} 只）`)
    createVisible.value = false
    cart.value = []
    await reloadGroups()
    activeGid.value = r.id
  } finally {
    creating.value = false
  }
}

// ── 加入已有分组 ──
const addVisible = ref(false)
const addTargetGid = ref('')
const addDate = ref('')
const adding = ref(false)
function openAddTo() {
  if (!cartCodes.value.length) return ElMessage.warning('请先勾选股票')
  addTargetGid.value = groups.value[0]?.id ?? ''
  addDate.value = dataMax.value || ''
  addVisible.value = true
}
async function doAddTo() {
  if (!addTargetGid.value) return ElMessage.warning('请选择目标分组')
  adding.value = true
  try {
    const r = await addMembers(addTargetGid.value, cartCodes.value, addDate.value || undefined)
    ElMessage.success(`已加入 ${r.added} 只`)
    addVisible.value = false
    cart.value = []
    await reloadGroups()
    if (activeGid.value === addTargetGid.value) await loadGroupDetail()
  } finally {
    adding.value = false
  }
}

// ── 从分组移出 ──
async function removeFromGroup() {
  if (!inGroupMode.value || !cartCodes.value.length) return
  await removeMembers(activeGid.value, cartCodes.value)
  ElMessage.success(`已移出 ${cartCodes.value.length} 只`)
  cart.value = []
  await Promise.all([reloadGroups(), loadGroupDetail()])
}

// ── 编辑 / 删除分组 ──
const editVisible = ref(false)
const editForm = ref<{ name: string; group_date: string; description: string; color: string }>({ name: '', group_date: '', description: '', color: '#73757d' })
function openEdit() {
  if (!groupDetail.value) return
  editForm.value = { name: groupDetail.value.name, group_date: groupDetail.value.group_date || '', description: groupDetail.value.description || '', color: groupDetail.value.color || '#73757d' }
  editVisible.value = true
}
async function doEdit() {
  await updateGroup(activeGid.value, {
    name: editForm.value.name.trim(),
    group_date: editForm.value.group_date || undefined,
    description: editForm.value.description,
    color: editForm.value.color,
  })
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
  activeGid.value = ''
  await reloadGroups()
}

onMounted(async () => {
  await auth.ensureLoaded().catch(() => undefined)
  await reloadGroups()
  const restore = route.query.restore === '1' ? stockSet.listState : null
  if (restore) {
    restoringListState = true
    q.value = restore.q
    board.value = restore.board
    excludeSt.value = restore.excludeSt
    tradeDate.value = restore.tradeDate
    sortBy.value = restore.sortBy
    sortOrder.value = restore.sortOrder
    page.value = restore.page
    // size/groupSize 是组件配置层默认值派生的会话 ref，恢复上次浏览态时直接赋值会话值即可。
    size.value = restore.size
    groupSize.value = restore.groupSize
    groupPage.value = restore.groupPage
    groupQ.value = restore.groupQ
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
  if (canViewGroups.value && settings.defaultView === 'group' && dg && dg.member_count > 0) {
    activeGid.value = dg.id
  } else {
    await load()
  }
})
onBeforeUnmount(() => {
  if (groupSearchTimer) clearTimeout(groupSearchTimer)
})
</script>

<template>
  <LayoutHost :layout="stocksEffective">
    <template #action>
    <div class="lh-action">
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        个股查询
        <HelpTip title="个股查询说明" :width="440">按代码/名称/板块筛选个股；支持分组查看与集合内翻页。</HelpTip>
      </h2>
      <p class="page-subtitle">按代码/名称/板块筛选个股行情，可跨分页勾选与分组管理。</p>
      </div>
      <div class="page-head-actions">
        <el-select v-if="canViewGroups" v-model="activeGid" placeholder="查看分组" clearable filterable style="width: 220px">
          <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="`${g.name}（${g.member_count}）`">
            <span class="group-option">
              <span class="color-dot" :style="{ backgroundColor: g.color }" />
              <span>{{ g.name }}（{{ g.member_count }}）</span>
            </span>
          </el-option>
        </el-select>
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>

    <!-- 搜索 / 筛选（置顶）-->
    <el-card v-if="!inGroupMode" shadow="never" class="filter-card">
      <AppControlRow class="filter-row">
        <TradeDatePicker v-model="tradeDate" placeholder="交易日期" clearable style="width: 180px" />
        <el-input v-model="q" placeholder="代码 / 名称" style="width: 220px" clearable @keyup.enter="search" @clear="search" />
        <el-select v-model="board" placeholder="全部板块" style="width: 130px" clearable @change="search">
          <el-option label="主板" value="主板" />
          <el-option label="创业板" value="创业板" />
          <el-option label="科创板" value="科创板" />
          <el-option label="ST 板块" value="ST" />
          <el-option label="退市板块" value="退市" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="search">查询</el-button>
      </AppControlRow>
    </el-card>

    <!-- 分组横幅 -->
    <el-card v-if="inGroupMode && groupDetail" shadow="never" class="group-banner">
      <div class="gb-row">
        <div class="gb-main">
          <span class="gb-name gb-name-edit" title="点击编辑分组" @click="openEdit">
            <span class="color-dot" :style="{ backgroundColor: groupDetail.color }" />
            {{ groupDetail.name }}
            <el-icon class="gb-edit-icon"><Edit /></el-icon>
          </span>
          <el-tag size="small" effect="plain">建组 {{ groupDetail.group_date || '—' }}</el-tag>
          <el-tag v-if="groupDetail.is_default" size="small" type="danger" effect="plain">默认</el-tag>
          <el-tag size="small" effect="plain">{{ groupDetail.count }} 只</el-tag>
          <span class="gb-ret">整组涨幅
            <b :class="pctClass(groupDetail.avg_ret)">{{ fmtPctRatio(groupDetail.avg_ret) }}</b>
            <span class="gb-hint">（各股自加入日起·等权平均）</span>
          </span>
        </div>
        <div class="gb-ops">
          <span v-if="groupDetail.description" class="gb-desc">{{ groupDetail.description }}</span>
          <el-input
            v-model="groupQ"
            placeholder="组内搜索"
            size="small"
            clearable
            style="width: 160px"
            @input="scheduleGroupSearch"
            @keyup.enter="groupSearch"
            @clear="groupSearch"
          />
          <el-button v-permission="'stock-group:delete'" size="small" type="danger" plain :disabled="groupDetail.is_default" @click="doDeleteGroup">删除分组</el-button>
        </div>
      </div>
    </el-card>
    </div>
    </template>

    <template #main>
    <el-card shadow="never">
      <AppStateBlock
        v-if="groupListError && !inGroupMode"
        state="error"
        size="compact"
        title="分组列表加载失败"
        :description="groupListError"
        retry
        @retry="reloadGroups"
      />
      <!-- 分组视图 -->
      <template v-if="inGroupMode">
        <AppStateBlock
          v-if="groupError && !groupDetail"
          state="error"
          title="分组明细加载失败"
          :description="groupError"
          retry
          @retry="loadGroupDetail"
        />
        <template v-else>
        <AppStateBlock
          v-if="groupError"
          state="error"
          size="compact"
          title="分组明细刷新失败"
          :description="groupError"
          retry
          @retry="loadGroupDetail"
        />
        <AppDataTable :data="groupRows" :loading="groupLoading" row-key="code"
          :border="tableBorder('groupTable')"
          :default-sort="groupElementDefaultSort"
          clickable
          :pagination="{ currentPage: groupPage, pageSize: groupSize, total: groupTotal, pageSizes: PAGE_SIZE_OPTIONS }"
          @row-click="(r: GroupMember) => enterDetail(r.code)"
          @sort-change="onGroupSortChange"
          @page-change="(p:number)=>{ groupPage=p; loadGroupDetail() }"
          @size-change="(s:number)=>{ groupSize=s; groupPage=1; loadGroupDetail() }">
          <AppTableColumn role="structural">
            <template #header>
              <el-checkbox :model-value="allCurChecked" :indeterminate="someCurChecked" @change="toggleAllCur" />
            </template>
            <template #default="{ row }">
              <span @click.stop><el-checkbox :model-value="inCart(row.code)" @change="() => toggle(row)" /></span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="groupColVisible('code')" label="代码" prop="code" sortable="custom" />
          <AppTableColumn v-if="groupColVisible('name')" label="名称" prop="name" sortable="custom">
            <template #default="{ row }">{{ row.name || '—' }}</template>
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
      </template>

      <!-- 普通查询 -->
      <template v-else>
        <AppStateBlock
          v-if="loadError && !rows.length"
          state="error"
          title="个股列表加载失败"
          :description="loadError"
          retry
          @retry="load"
        />
        <template v-else>
        <AppStateBlock
          v-if="loadError"
          state="error"
          size="compact"
          title="个股列表刷新失败"
          :description="loadError"
          retry
          @retry="load"
        />
        <AppDataTable :data="rows" :loading="loading" row-key="code"
          :border="tableBorder('table')"
          clickable
          :pagination="{ currentPage: page, pageSize: size, total, pageSizes: PAGE_SIZE_OPTIONS }"
          @row-click="(r: StockBasic) => enterDetail(r.code)"
          :default-sort="tableElementDefaultSort"
          @sort-change="onSortChange"
          @page-change="(p:number)=>{ page=p; load() }"
          @size-change="(s:number)=>{ size=s; page=1; load() }">
          <AppTableColumn role="structural">
            <template #header>
              <el-checkbox :model-value="allCurChecked" :indeterminate="someCurChecked" @change="toggleAllCur" />
            </template>
            <template #default="{ row }">
              <span @click.stop><el-checkbox :model-value="inCart(row.code)" @change="() => toggle(row)" /></span>
            </template>
          </AppTableColumn>
          <AppTableColumn v-if="colVisible('code')" label="代码" prop="code" sortable="custom" />
          <AppTableColumn v-if="colVisible('name')" label="名称" prop="name" sortable="custom">
            <template #default="{ row }">
              <span>{{ row.name || '—' }}</span>
              <el-tag v-if="row.is_st" type="danger" size="small" effect="plain" style="margin-left:6px">ST</el-tag>
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
              <span v-if="row.groups?.length" class="tag-line">
                <el-tag
                  v-for="g in row.groups"
                  :key="g.id"
                  size="small"
                  effect="plain"
                  class="box-tag"
                  :style="tagStyle(g.color)"
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
    </el-card>
    </template>

    <template #footer>
    <!-- 多选购物车条：固定底部（footer 区），选择跨分页/跨搜索累积 -->
    <el-card v-if="cart.length" shadow="never" class="cart-card">
      <div class="cart-row">
        <div class="cart-info">
          <span class="cart-n">已选 <b>{{ cart.length }}</b> 只</span>
          <div class="chips">
            <el-tag v-for="c in cart.slice(0, 30)" :key="c.code" size="small" closable @close="toggle(c)" class="chip">
              {{ c.name || c.code }}
            </el-tag>
            <span v-if="cart.length > 30" class="more">… 等 {{ cart.length }} 只</span>
          </div>
        </div>
        <div class="cart-ops">
          <el-button size="small" type="primary" @click="viewCartOneByOne">逐个查看</el-button>
          <template v-if="inGroupMode">
            <el-button v-permission="'stock-group:member-update'" size="small" type="danger" plain @click="removeFromGroup">从本组移出</el-button>
          </template>
          <template v-else>
            <el-button v-permission="'stock-group:create'" size="small" @click="openCreate">存为新分组</el-button>
            <el-button v-permission="'stock-group:member-update'" size="small" @click="openAddTo">加入已有分组</el-button>
          </template>
          <el-button size="small" text @click="cart = []">清空</el-button>
        </div>
      </div>
    </el-card>
    </template>

    <template #overlays>
    <!-- 存为新分组 -->
    <el-dialog v-model="createVisible" title="存为新分组" width="460px">
      <el-form label-width="80px">
        <el-form-item label="分组名">
          <el-input v-model="createForm.name" placeholder="如：5月观察龙头" maxlength="30" show-word-limit />
        </el-form-item>
        <el-form-item label="建组日期">
          <TradeDatePicker v-model="createForm.group_date" placeholder="默认最新交易日" clearable style="width: 200px" />
          <span class="f-hint">这批股票加入日期默认 = 建组日期（涨幅基准）</span>
        </el-form-item>
        <el-form-item label="分组说明">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="createForm.color" :predefine="['#f66055', '#f58a07', '#1677ff', '#0ea968', '#73757d', '#b882ff']" />
          <span class="f-hint">用于列表标签和分组状态识别</span>
        </el-form-item>
      </el-form>
      <div class="f-codes">将加入 {{ cartCodes.length }} 只：{{ cart.slice(0, 8).map(c => c.name || c.code).join('、') }}{{ cart.length > 8 ? ' …' : '' }}</div>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button v-permission="'stock-group:create'" type="primary" :loading="creating" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 加入已有分组 -->
    <el-dialog v-model="addVisible" title="加入已有分组" width="440px">
      <el-form label-width="80px">
        <el-form-item label="目标分组">
          <el-select v-model="addTargetGid" filterable style="width: 100%">
            <el-option v-for="g in groups" :key="g.id" :value="g.id" :label="`${g.name}（${g.member_count}）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="加入日期">
          <TradeDatePicker v-model="addDate" placeholder="默认最新交易日" clearable style="width: 200px" />
          <span class="f-hint">作为这批股票的涨幅基准</span>
        </el-form-item>
      </el-form>
      <div class="f-codes">将加入 {{ cartCodes.length }} 只（已在组内的保留原加入日期）</div>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button v-permission="'stock-group:member-update'" type="primary" :loading="adding" @click="doAddTo">加入</el-button>
      </template>
    </el-dialog>

    <!-- 编辑分组 -->
    <el-dialog v-model="editVisible" title="编辑分组" width="460px">
      <el-form label-width="80px">
        <el-form-item label="分组名"><el-input v-model="editForm.name" maxlength="30" show-word-limit /></el-form-item>
        <el-form-item label="建组日期"><TradeDatePicker v-model="editForm.group_date" clearable style="width: 200px" /></el-form-item>
        <el-form-item label="分组说明"><el-input v-model="editForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="editForm.color" :disabled="groupDetail?.is_default" :predefine="['#f66055', '#f58a07', '#1677ff', '#0ea968', '#73757d', '#b882ff']" />
          <span class="f-hint">{{ groupDetail?.is_default ? '默认自选固定为红色' : '用于列表标签和分组状态识别' }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button v-permission="'stock-group:update'" type="primary" @click="doEdit">保存</el-button>
      </template>
    </el-dialog>

    <PageSettingsDrawer
      v-model="settingsOpen"
      title="个股查询"
      :dirty="isDirty || layoutDirty"
      page-key="stocks"
      :config="drawerConfig"
      :business-visible="true"
      :component-slot-ids="settingsComponentSlotIds"
      :component-meta-overrides="settingsComponentMetaOverrides"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="默认查询">
          <div class="setting-item">
            <div class="setting-label">默认视图</div>
            <PageSegmented
              v-model="visibleDefaultView"
              :options="defaultViewOptions"
              aria-label="默认视图"
              test-id="stocks-default-view"
            />
          </div>
          <PageToggleRow v-model="settings.excludeSt" label="默认排除 ST" />
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
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  font-size: var(--app-font-size-body);
  color: var(--page-settings-text-subtle);
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
}
.gb-name-edit {
  cursor: pointer;
  transition: color 0.15s;
}
.gb-name-edit:hover {
  color: var(--el-color-primary);
}
.gb-edit-icon {
  font-size: var(--app-font-size-table);
  color: var(--app-placeholder-text);
  margin-left: 2px;
}
.gb-name-edit:hover .gb-edit-icon {
  color: var(--el-color-primary);
}
.tag-line {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  margin-left: 6px;
  flex-wrap: wrap;
}
.box-tag {
  border-radius: 4px;
  font-weight: var(--app-font-weight-section);
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
.cart-card {
  border: 1px solid var(--el-color-primary-light-7);
  flex: 0 0 auto;
}
.cart-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--app-space-4);
  flex-wrap: wrap;
}
.cart-info {
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-3);
  flex: 1;
  min-width: 260px;
}
.cart-n {
  font-size: var(--app-font-size-table);
  white-space: nowrap;
  padding-top: 2px;
}
.cart-n b {
  color: var(--market-up-color);
  font-size: var(--app-font-size-data);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
  max-height: 64px;
  overflow: auto;
}
.chip {
  cursor: default;
}
.more {
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
  align-self: center;
}
.cart-ops {
  display: flex;
  gap: var(--app-space-2);
  align-items: center;
  flex-shrink: 0;
}
.f-codes {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  margin-top: 4px;
}
</style>

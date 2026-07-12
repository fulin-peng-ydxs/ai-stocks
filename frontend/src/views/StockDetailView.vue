<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { getBars, getIndicators, getTradeEval, listStocks, type Bar, type StockBasic, type TradeEval } from '@/api/stocks'
import { addMembers, getGroup, listGroups, removeMembers, type GroupSummary } from '@/api/stockGroup'
import { listTradeProfiles, type TradeProfileSummary } from '@/api/tradeProfile'
import AppStateBlock from '@/components/AppStateBlock.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import { useStockSet } from '@/stores/stockSet'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import { usePageSettings } from '@/composables/usePageSettings'
import { useKlinePrefs } from '@/composables/useKlinePrefs'
import CandleChart from '@/components/CandleChart.vue'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const route = useRoute()
const router = useRouter()
// 工作标签按 path 缓存独立实例；代码固定为该实例创建时的路由，避免停用标签监听全局路由后被其他个股标签串改。
const code = ref(String(route.params.code))
const settingsOpen = ref(false)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const detailLayout = getPageLayout('stock-detail')
const {
  effective: detailEffective,
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
} = useRemoteLayoutConfig(detailLayout)

// 抽屉「布局」段由 PageSettingsDrawer 按 config 自动渲染（本页无组件配置，仅布局段）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }
const detailDefaults = {
  adjustMode: 'qfq' as '' | 'qfq' | 'hfq',
  showTradeCard: true,
  showNav: true,
  indicators: {
    ma20: true,
    ma60: true,
    dist_to_high_2y: true,
    is_high_2y: true,
    is_bull_arrange: true,
    ma20_up: true,
    is_platform_breakout: true,
    is_vol_breakout: true,
  },
}
const { settings, isDirty, reset } = usePageSettings('stock-detail', detailDefaults)

// ── 通用导航：当前集合（分组成员 / 列表勾选 / 查询结果）上一个·下一个·直选 ──
const stockSet = useStockSet()
const auth = useAuthStore()
const canViewGroups = computed(() => hasPermission(auth.role, auth.permissions, 'stock-group:view'))
const setIndex = computed(() => stockSet.indexOf(code.value))
const inSet = computed(() => setIndex.value >= 0)
const prevCode = computed(() => stockSet.neighbor(code.value, -1))
const nextCode = computed(() => stockSet.neighbor(code.value, 1))
function gotoCode(c: string | null) {
  if (c && c !== '__more__' && c !== code.value) router.push(`/stocks/${c}`)
}
const collectionTotal = computed(() => stockSet.total || stockSet.items.length)
const collectionTotalPages = computed(() => Math.max(1, Math.ceil(collectionTotal.value / Math.max(stockSet.pageSize || 20, 1))))
const minLoadedPage = computed(() => stockSet.loadedPages.length ? Math.min(...stockSet.loadedPages) : 1)
const maxLoadedPage = computed(() => stockSet.loadedPages.length ? Math.max(...stockSet.loadedPages) : 1)
const canUseCollectionQuery = computed(() => !stockSet.query || stockSet.query.kind !== 'group' || canViewGroups.value)
const canLoadPrev = computed(() => !!stockSet.query && canUseCollectionQuery.value && minLoadedPage.value > 1)
const canLoadNext = computed(() => !!stockSet.query && canUseCollectionQuery.value && maxLoadedPage.value < collectionTotalPages.value)
const setLoading = ref(false)
function clearUnauthorizedGroupSet() {
  if (canViewGroups.value) return
  stockSet.clearGroupContext()
}
async function loadSetPage(page: number) {
  if (!stockSet.query || stockSet.loadedPages.includes(page)) return
  if (stockSet.query.kind === 'group' && !canViewGroups.value) {
    stockSet.clearGroupContext()
    return
  }
  setLoading.value = true
  try {
    if (stockSet.query.kind === 'group') {
      const data = await getGroup(stockSet.query.groupId, { ...stockSet.query.params, page, size: stockSet.pageSize })
      stockSet.appendPage(data.members.list.map((r) => ({ code: r.code, name: r.name })), page)
      stockSet.setTotal(data.members.total)
    } else {
      const data = await listStocks({ ...stockSet.query.params, page, size: stockSet.pageSize })
      stockSet.appendPage(data.list.map((r) => ({ code: r.code, name: r.name })), page)
      stockSet.setTotal(data.total)
    }
  } finally {
    setLoading.value = false
  }
}
async function gotoNeighbor(dir: -1 | 1) {
  const c = stockSet.neighbor(code.value, dir)
  if (c) return gotoCode(c)
  if (dir < 0 && canLoadPrev.value) {
    await loadSetPage(minLoadedPage.value - 1)
    return gotoCode(stockSet.neighbor(code.value, dir))
  }
  if (dir > 0 && canLoadNext.value) {
    await loadSetPage(maxLoadedPage.value + 1)
    return gotoCode(stockSet.neighbor(code.value, dir))
  }
}
const loading = ref(false)
const error = ref('')
const adjust = ref<string>(settings.adjustMode || '')
// 显示范围（缩放）：默认来自全局 K 线偏好，数据始终全量加载，可自由拖动看全部
const { validDefault: klineDefault } = useKlinePrefs()
const viewDays = ref(klineDefault.value)
const bars = ref<Bar[]>([])
const name = ref('')
const latestQuote = ref<Bar | null>(null)
const latest = ref<Record<string, unknown> | null>(null)

// 始终至少加载 5 年数据保证 MA60/MA120 有足够热身窗口，displayBars 控制图表可见范围
const MIN_HISTORY_DAYS = 1250
const chartLookback = computed(() => viewDays.value >= 99999 ? 6000 : Math.max(viewDays.value, MIN_HISTORY_DAYS))
// 展示用：按选项切末尾 N 根；热身用：剩余部分仅参与 MA 计算不渲染
const displayBars = computed(() => viewDays.value >= 99999 ? bars.value : bars.value.slice(-viewDays.value))
const warmupBars = computed(() => viewDays.value >= 99999 ? [] : bars.value.slice(0, -viewDays.value || undefined))
const latestPct = computed(() => {
  const b = latestQuote.value
  if (!b?.pre_close || b.pre_close <= 0) return null
  return ((b.close / b.pre_close) - 1) * 100
})
const latestClose = computed(() => latestQuote.value?.close ?? null)

// 个股详情页展示的关键指标（取最新一日）
const INDICATOR_FIELDS: { key: string; label: string }[] = [
  { key: 'ma20', label: 'MA20' },
  { key: 'ma60', label: 'MA60' },
  { key: 'dist_to_high_2y', label: '距两年高(比)' },
  { key: 'is_high_2y', label: '两年新高' },
  { key: 'is_bull_arrange', label: '多头排列' },
  { key: 'ma20_up', label: 'MA20 向上' },
  { key: 'is_platform_breakout', label: '平台突破' },
  { key: 'is_vol_breakout', label: '放量突破' },
]
const visibleIndicatorFields = computed(() => INDICATOR_FIELDS.filter((f) => settings.indicators[f.key as keyof typeof settings.indicators]))

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
  return String(v)
}
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return (v > 0 ? '+' : '') + v.toFixed(2) + '%'
}
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'muted'
  return v > 0 ? 'up' : v < 0 ? 'down' : ''
}

// ── 买卖指标方案评估（v2.0：替代固定买点引擎）──
const tradeProfiles = ref<TradeProfileSummary[]>([])
const tradeId = ref('')
const tradeEval = ref<TradeEval | null>(null)
const tradeLoading = ref(false)
const tradeError = ref('')

// 同一详情标签内切换复权或区间时取消旧请求，避免较慢响应覆盖最新数据。
let reqCtrl: AbortController | null = null
function isAbort(e: unknown): boolean {
  const c = e as { code?: string; name?: string }
  return c?.code === 'ERR_CANCELED' || c?.name === 'CanceledError'
}

async function evalTrade(signal?: AbortSignal) {
  if (!tradeId.value) return
  tradeLoading.value = true
  tradeError.value = ''
  try {
    const r = await getTradeEval(code.value, tradeId.value, undefined, signal)
    if (!signal?.aborted) tradeEval.value = r
  } catch (e) {
    if (!isAbort(e)) {
      tradeEval.value = null
      tradeError.value = (e as Error).message || '买卖信号加载失败'
    }
  } finally {
    if (!signal?.aborted) tradeLoading.value = false
  }
}

async function load() {
  reqCtrl?.abort()                      // 取消上一次在途请求
  const ctrl = new AbortController()
  reqCtrl = ctrl
  loading.value = true
  error.value = ''
  try {
    const [b, ind, quote] = await Promise.all([
      getBars(code.value, { adjust: adjust.value, lookback: chartLookback.value }, ctrl.signal),
      getIndicators(code.value, { lookback: 1 }, ctrl.signal),
      getBars(code.value, { adjust: '', lookback: 1 }, ctrl.signal),
    ])
    if (ctrl.signal.aborted) return
    bars.value = b.bars
    name.value = b.name || ''
    latest.value = ind.indicators.length ? ind.indicators[ind.indicators.length - 1] : null
    latestQuote.value = quote.bars.length ? quote.bars[quote.bars.length - 1] : null
    if (tradeId.value) evalTrade(ctrl.signal)  // 不阻塞主图
  } catch (e) {
    if (isAbort(e)) return
    error.value = (e as Error).message
  } finally {
    if (reqCtrl === ctrl) loading.value = false  // 仅最新一次负责收尾
  }
}
watch(viewDays, () => load())
watch(() => settings.adjustMode, (value) => {
  adjust.value = value || ''
  load()
})

onMounted(async () => {
  await auth.ensureLoaded().catch(() => undefined)
  clearUnauthorizedGroupSet()
  try {
    tradeProfiles.value = await listTradeProfiles()
    if (tradeProfiles.value.length) tradeId.value = tradeProfiles.value[0].id
  } catch {
    /* 方案列表失败不阻塞 */
  }
  await Promise.all([load(), loadGroups(), loadStockGroups()])
})

// ── 分组编辑 ──
const groups = ref<GroupSummary[]>([])
const stockGroups = ref<StockBasic['groups']>([])
const groupOpsLoading = ref(false)
const selectedGroupIds = ref<string[]>([])
const selectedGroups = computed(() => selectedGroupIds.value.map((id) => {
  const fromAll = groups.value.find((g) => g.id === id)
  const fromStock = stockGroups.value.find((g) => g.id === id)
  return fromAll ?? fromStock ?? null
}).filter((g): g is GroupSummary | StockBasic['groups'][number] => !!g))
const visibleSelectedGroups = computed(() => selectedGroups.value.slice(0, 2))
const hiddenSelectedGroupCount = computed(() => Math.max(0, selectedGroups.value.length - visibleSelectedGroups.value.length))
let syncingGroupSelect = false
function tagStyle(color?: string) {
  const c = color || '#909399'
  return { color: c, borderColor: c, backgroundColor: `${c}14` }
}
async function loadGroups() {
  // 次级加载按自身 view 码优雅降级：无 stock-group:view 的部分授权角色不拉分组、也不因此 403 卡住详情页主体
  // （K 线/指标/交易评估仍可用）。默认业务角色含该码不受影响。与 StocksView.reloadGroups 同口径。
  if (!canViewGroups.value) {
    groups.value = []
    return
  }
  groups.value = await listGroups()
}
async function loadStockGroups() {
  if (!canViewGroups.value) {
    stockGroups.value = []
    selectedGroupIds.value = []
    return
  }
  const data = await listStocks({ q: code.value, page: 1, size: 1 })
  stockGroups.value = data.list.find((r) => r.code === code.value)?.groups ?? []
  syncingGroupSelect = true
  selectedGroupIds.value = stockGroups.value.map((g) => g.id)
  syncingGroupSelect = false
}
async function onGroupsChange(value: unknown) {
  if (syncingGroupSelect) return
  if (!canViewGroups.value) return
  const nextIds = Array.isArray(value) ? value.map(String) : []
  const prev = new Set(stockGroups.value.map((g) => g.id))
  const next = new Set(nextIds)
  const add = nextIds.filter((id) => !prev.has(id))
  const remove = [...prev].filter((id) => !next.has(id))
  if (!add.length && !remove.length) return
  groupOpsLoading.value = true
  try {
    await Promise.all([
      ...add.map((gid) => addMembers(gid, [code.value])),
      ...remove.map((gid) => removeMembers(gid, [code.value])),
    ])
    await Promise.all([loadGroups(), loadStockGroups()])
    ElMessage.success('分组已同步')
  } finally {
    groupOpsLoading.value = false
  }
}
async function removeSelectedGroup(gid: string) {
  if (groupOpsLoading.value) return
  const next = selectedGroupIds.value.filter((id) => id !== gid)
  selectedGroupIds.value = next
  await onGroupsChange(next)
}

// ── 集合下拉：保留全量集合语义，候选项按 100 条懒加载，搜索合并在同一个下拉里 ──
const DROPDOWN_PAGE_SIZE = 100
const dropdownItems = ref<{ code: string; name?: string | null }[]>([])
const dropdownPage = ref(1)
const dropdownTotal = ref(0)
const dropdownKeyword = ref('')
const dropdownLoading = ref(false)
const dropdownLoadedPages = ref<number[]>([])
let dropdownScrollEl: HTMLElement | null = null
let dropdownSearchTimer: ReturnType<typeof setTimeout> | null = null
let dropdownRequestSeq = 0

const dropdownHasMore = computed(() => dropdownItems.value.length < dropdownTotal.value)
const currentDropdownItem = computed(() => {
  const fromSet = stockSet.items.find((it) => it.code === code.value)
  return fromSet ?? { code: code.value, name: name.value || null }
})
const dropdownOptions = computed(() => {
  const current = currentDropdownItem.value
  if (!current.code || dropdownItems.value.some((it) => it.code === current.code)) return dropdownItems.value
  return [current, ...dropdownItems.value]
})

function mergeItems(base: { code: string; name?: string | null }[], incoming: { code: string; name?: string | null }[]) {
  const seen = new Set(base.map((it) => it.code))
  return [...base, ...incoming.filter((it) => !seen.has(it.code))]
}

async function fetchDropdownPage(page: number, keyword: string) {
  if (stockSet.query) {
    if (stockSet.query.kind === 'group') {
      if (!canViewGroups.value) {
        stockSet.clearGroupContext()
        return { total: 0, items: [] }
      }
      const data = await getGroup(stockSet.query.groupId, {
        ...stockSet.query.params,
        q: keyword || stockSet.query.params.q,
        page,
        size: DROPDOWN_PAGE_SIZE,
      })
      return {
        total: data.members.total,
        items: data.members.list.map((r) => ({ code: r.code, name: r.name })),
      }
    }
    const data = await listStocks({
      ...stockSet.query.params,
      q: keyword || stockSet.query.params.q,
      page,
      size: DROPDOWN_PAGE_SIZE,
    })
    return {
      total: data.total,
      items: data.list.map((r) => ({ code: r.code, name: r.name })),
    }
  }

  const q = keyword.trim().toLowerCase()
  const source = q
    ? stockSet.items.filter((it) => it.code.toLowerCase().includes(q) || (it.name || '').toLowerCase().includes(q))
    : stockSet.items
  const start = (page - 1) * DROPDOWN_PAGE_SIZE
  return {
    total: source.length,
    items: source.slice(start, start + DROPDOWN_PAGE_SIZE),
  }
}

async function loadDropdownPage(page: number, replace = false) {
  if (dropdownLoading.value || (!replace && dropdownLoadedPages.value.includes(page))) return
  dropdownLoading.value = true
  const seq = ++dropdownRequestSeq
  try {
    const keyword = dropdownKeyword.value.trim()
    const data = await fetchDropdownPage(page, keyword)
    if (seq !== dropdownRequestSeq || keyword !== dropdownKeyword.value.trim()) return
    dropdownTotal.value = data.total
    dropdownPage.value = page
    dropdownLoadedPages.value = replace ? [page] : [...dropdownLoadedPages.value, page]
    dropdownItems.value = replace ? data.items : mergeItems(dropdownItems.value, data.items)

    if (!keyword) {
      stockSet.setTotal(data.total)
      stockSet.appendPage(data.items, page)
    }
  } finally {
    dropdownLoading.value = false
  }
}

async function resetDropdown(keyword = '') {
  dropdownRequestSeq += 1
  dropdownKeyword.value = keyword
  dropdownTotal.value = 0
  dropdownLoadedPages.value = []
  dropdownItems.value = []

  if (!keyword) {
    dropdownItems.value = stockSet.items
    dropdownTotal.value = collectionTotal.value
    dropdownLoadedPages.value = stockSet.loadedPages.length ? [...stockSet.loadedPages] : [1]
    dropdownPage.value = dropdownLoadedPages.value.length ? Math.max(...dropdownLoadedPages.value) : 1
    return
  }

  dropdownPage.value = 1
  await loadDropdownPage(1, true)
}

function onCollectionSearch(query: string) {
  if (dropdownSearchTimer) clearTimeout(dropdownSearchTimer)
  dropdownSearchTimer = setTimeout(() => {
    resetDropdown(query.trim())
  }, 180)
}

function onCollectionSelect(c: string | null) {
  if (!c || c === '__more__') return
  if (stockSet.indexOf(c) < 0) {
    stockSet.mergeItemsNear(dropdownItems.value, code.value)
  }
  gotoCode(c)
}

function detachDropdownScroll() {
  if (dropdownScrollEl) {
    dropdownScrollEl.removeEventListener('scroll', onDropdownScroll)
    dropdownScrollEl = null
  }
}

function onDropdownScroll() {
  if (!dropdownScrollEl || dropdownLoading.value || !dropdownHasMore.value) return
  const distance = dropdownScrollEl.scrollHeight - dropdownScrollEl.scrollTop - dropdownScrollEl.clientHeight
  if (distance <= 40) {
    const nextPage = dropdownLoadedPages.value.length ? Math.max(...dropdownLoadedPages.value) + 1 : dropdownPage.value + 1
    loadDropdownPage(nextPage)
  }
}

function attachDropdownScroll() {
  detachDropdownScroll()
  dropdownScrollEl = document.querySelector('.stock-set-dropdown .el-select-dropdown__wrap') as HTMLElement | null
  dropdownScrollEl?.addEventListener('scroll', onDropdownScroll)
}

async function onCollectionVisibleChange(visible: boolean) {
  if (!visible) {
    detachDropdownScroll()
    return
  }
  if (!dropdownItems.value.length || dropdownKeyword.value) await resetDropdown('')
  await nextTick()
  attachDropdownScroll()
}

onBeforeUnmount(() => {
  reqCtrl?.abort()
  if (dropdownSearchTimer) clearTimeout(dropdownSearchTimer)
  detachDropdownScroll()
})
</script>

<template>
  <LayoutHost :layout="detailEffective">
    <template #action>
    <div class="page-head">
      <div class="title">
        <el-button text @click="router.push('/stocks?restore=1')">‹ 返回</el-button>
        <h2>{{ name || '—' }}</h2>
        <span class="code-sub">{{ code }}</span>
        <span class="quote-sub" :class="pctClass(latestPct)">
          {{ latestClose == null ? '--' : latestClose.toFixed(2) }}
          {{ fmtPct(latestPct) }}
        </span>
        <el-select
          v-if="canViewGroups"
          v-permission="'stock-group:member-update'"
          v-model="selectedGroupIds"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="2"
          size="small"
          placeholder="所属分组"
          style="width: 260px"
          :loading="groupOpsLoading"
          @change="onGroupsChange"
        >
          <template #tag>
            <el-tag
              v-for="g in visibleSelectedGroups"
              :key="g.id"
              class="group-select-tag"
              size="small"
              closable
              :disable-transitions="true"
              :style="tagStyle(g.color)"
              @close.stop="removeSelectedGroup(g.id)"
            >
              {{ g.name }}
            </el-tag>
            <el-tag
              v-if="hiddenSelectedGroupCount"
              class="group-select-tag more"
              size="small"
              :disable-transitions="true"
            >
              +{{ hiddenSelectedGroupCount }}
            </el-tag>
          </template>
          <el-option
            v-for="g in groups"
            :key="g.id"
            :value="g.id"
            :label="g.name"
          >
            <span class="group-option">
              <span class="color-dot" :style="{ backgroundColor: g.color }" />
              <span>{{ g.name }}（{{ g.member_count }}）</span>
            </span>
          </el-option>
        </el-select>
      </div>
      <div class="page-head-actions">
        <div class="ops">
          <KlineRangeSelect v-model="viewDays" />
        </div>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #main>
    <!-- 通用集合导航条 -->
    <div v-if="settings.showNav && stockSet.has" class="nav-bar">
      <span class="nav-label">
        {{ stockSet.label }}
        <span v-if="inSet" class="nav-pos">{{ setIndex + 1 }}/{{ collectionTotal }}</span>
        <span v-else class="nav-pos muted">不在集合内 · 共 {{ collectionTotal }} 只</span>
      </span>
      <el-button-group class="nav-btns">
        <el-button size="small" :loading="setLoading" :disabled="!prevCode && !canLoadPrev" @click="gotoNeighbor(-1)">‹ 上一个</el-button>
        <el-button size="small" :loading="setLoading" :disabled="!nextCode && !canLoadNext" @click="gotoNeighbor(1)">下一个 ›</el-button>
      </el-button-group>
      <el-select
        :model-value="code"
        placeholder="从集合中选择"
        filterable
        remote
        clearable
        reserve-keyword
        size="small"
        popper-class="stock-set-dropdown"
        style="width: 260px"
        :remote-method="onCollectionSearch"
        :loading="dropdownLoading"
        @change="onCollectionSelect"
        @visible-change="onCollectionVisibleChange"
      >
        <el-option
          v-for="(it, i) in dropdownOptions"
          :key="it.code"
          :value="it.code"
          :label="`${i + 1}. ${it.name || ''} ${it.code}`"
        />
        <el-option
          v-if="dropdownHasMore"
          key="__more__"
          value="__more__"
          disabled
          :label="dropdownLoading ? '加载中...' : '向下滚动加载更多'"
        />
      </el-select>
      <el-button size="small" text circle title="退出集合" @click="stockSet.clear()">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <AppStateBlock
      v-if="error && !bars.length"
      state="error"
      title="个股详情加载失败"
      :description="error"
      retry
      @retry="load"
    />

    <template v-else>
      <AppStateBlock
        v-if="error"
        state="error"
        size="compact"
        title="个股详情刷新失败"
        :description="error"
        retry
        @retry="load"
      />
      <el-card shadow="never" v-loading="loading" :body-style="{ padding: '0' }">
        <CandleChart :bars="displayBars" :warmup-bars="warmupBars" :zoom-start="0" :zoom-end="100" />
      </el-card>

      <el-card shadow="never" class="ind-card" header="最新指标快照">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item v-for="f in visibleIndicatorFields" :key="f.key" :label="f.label">
            {{ latest ? fmt(latest[f.key]) : '—' }}
          </el-descriptions-item>
        </el-descriptions>
        <p class="note">注：RS 相对强度为全市场横截面指标，个股单独查询不计算；请在策略筛选/每日榜单中查看。</p>
      </el-card>

      <!-- 买卖指标方案评估 -->
      <el-card v-if="settings.showTradeCard" shadow="never" class="trade-card">
        <template #header>
          <div class="trade-head">
            <span>买卖信号评估</span>
            <el-select v-model="tradeId" size="small" style="width: 220px" @change="() => evalTrade()">
              <el-option v-for="p in tradeProfiles" :key="p.id" :value="p.id"
                :label="p.name + (p.is_preset ? '（系统内置）' : '')" />
            </el-select>
            <span class="hint" v-if="tradeEval">交易日 {{ tradeEval.date }} · v{{ tradeEval.version }}</span>
          </div>
        </template>
        <div v-loading="tradeLoading">
          <AppStateBlock
            v-if="tradeError"
            state="error"
            size="compact"
            title="买卖信号加载失败"
            :description="tradeError"
            retry
            @retry="evalTrade()"
          />
          <el-empty v-else-if="!tradeEval" class="app-empty app-empty--compact" description="选择买卖方案以评估当日信号" />
          <div v-else class="trade-body">
            <div class="signal-row">
              <el-tag :type="tradeEval.buy_signal ? 'danger' : 'info'" effect="dark" size="large">
                {{ tradeEval.buy_signal ? '✓ 触发买入' : '买入未触发' }}
              </el-tag>
              <el-tag :type="tradeEval.sell_signal ? 'warning' : 'info'" effect="dark" size="large">
                {{ tradeEval.sell_signal ? '✓ 触发卖出' : '卖出未触发' }}
              </el-tag>
            </div>
            <div class="cond-cols">
              <div class="cond-col">
                <div class="cond-title">买入条件（{{ tradeEval.buy.op === 'AND' ? '需全部满足' : '满足任一' }}）</div>
                <div v-for="(cc, i) in tradeEval.buy.conds" :key="i" class="cond-line">
                  <el-tag :type="cc.met ? 'success' : 'info'" size="small" effect="plain">
                    {{ cc.met ? '✓' : '✗' }}
                  </el-tag>
                  <span>{{ cc.label }}</span>
                </div>
              </div>
              <div class="cond-col">
                <div class="cond-title">卖出条件（{{ tradeEval.sell.op === 'AND' ? '需全部满足' : '满足任一' }}）</div>
                <el-empty v-if="!tradeEval.sell.conds.length" class="app-empty app-empty--tiny" description="无卖出条件" />
                <div v-for="(cc, i) in tradeEval.sell.conds" :key="i" class="cond-line">
                  <el-tag :type="cc.met ? 'success' : 'info'" size="small" effect="plain">
                    {{ cc.met ? '✓' : '✗' }}
                  </el-tag>
                  <span>{{ cc.label }}</span>
                </div>
                <div v-if="tradeEval.backstop && (tradeEval.backstop.take_profit || tradeEval.backstop.stop_loss || tradeEval.backstop.max_hold_days)" class="backstop">
                  兜底：
                  <span v-if="tradeEval.backstop.take_profit">止盈 {{ (tradeEval.backstop.take_profit * 100).toFixed(0) }}%</span>
                  <span v-if="tradeEval.backstop.stop_loss"> · 止损 {{ (tradeEval.backstop.stop_loss * 100).toFixed(0) }}%</span>
                  <span v-if="tradeEval.backstop.max_hold_days"> · 最多持 {{ tradeEval.backstop.max_hold_days }} 日</span>
                </div>
              </div>
            </div>
            <p class="note">点时安全：仅用 ≤ 当日数据求值。兜底止盈止损需结合持仓成本，在回测验证中生效。</p>
          </div>
        </div>
      </el-card>
    </template>
    </template>

    <template #overlays>
    <PageSettingsDrawer
      v-model="settingsOpen"
      title="个股详情"
      :dirty="isDirty || layoutDirty"
      page-key="stock-detail"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="图表设置" desc="结构参考同花顺，但颜色跟随当前主题。">
          <div class="setting-item">
            <div class="setting-label">复权模式</div>
            <PageSegmented v-model="settings.adjustMode" :options="[
              { label: '不复权', value: '' },
              { label: '前复权', value: 'qfq' },
              { label: '后复权', value: 'hfq' },
            ]" />
          </div>
        </PageSettingSection>

        <KlineSettingSection />

        <PageSettingSection title="指标快照">
          <PageToggleRow v-model="settings.indicators.ma20" label="MA20" />
          <PageToggleRow v-model="settings.indicators.ma60" label="MA60" />
          <PageToggleRow v-model="settings.indicators.dist_to_high_2y" label="距两年高(比)" />
          <PageToggleRow v-model="settings.indicators.is_high_2y" label="两年新高" />
          <PageToggleRow v-model="settings.indicators.is_bull_arrange" label="多头排列" />
          <PageToggleRow v-model="settings.indicators.ma20_up" label="MA20 向上" />
          <PageToggleRow v-model="settings.indicators.is_platform_breakout" label="平台突破" />
          <PageToggleRow v-model="settings.indicators.is_vol_breakout" label="放量突破" />
        </PageSettingSection>

        <PageSettingSection title="辅助模块">
          <PageToggleRow v-model="settings.showNav" label="显示集合导航条" />
          <PageToggleRow v-model="settings.showTradeCard" label="显示买卖信号评估卡" />
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
  align-items: center;
  margin-bottom: 14px;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.title h2 {
  margin: 0;
  font-size: 20px;
}
.code-sub {
  color: #909399;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.quote-sub {
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.up {
  color: #f56c6c;
}
.down {
  color: #2e9e5b;
}
.group-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.group-select-tag {
  margin: 2px 4px 2px 0;
  border-radius: 4px;
  border-style: solid;
  font-weight: 600;
}
.group-select-tag.more {
  color: var(--el-text-color-secondary);
  border-color: var(--el-border-color);
  background: var(--el-fill-color-light);
}
.color-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: 0 0 auto;
}
.ops {
  display: flex;
  gap: 10px;
}
.setting-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.setting-label {
  font-size: 14px;
  color: var(--page-settings-text-subtle);
}
.nav-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 14px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  flex-wrap: wrap;
}
.nav-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  flex: 1;
}
.nav-pos {
  font-weight: 400;
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}
.group-card {
  margin-top: 16px;
}
.group-edit-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.group-tags,
.group-add {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.box-tag {
  border-radius: 4px;
  font-weight: 600;
}
.muted {
  color: #c0c4cc;
}
.ind-card,
.trade-card {
  margin-top: 16px;
}
.note {
  margin: 10px 0 0;
  color: #909399;
  font-size: 12px;
}
.trade-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.hint {
  color: #909399;
  font-size: 12px;
}
.signal-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.cond-cols {
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
}
.cond-col {
  flex: 1;
  min-width: 240px;
}
.cond-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--el-text-color-regular);
}
.cond-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 13px;
}
.backstop {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>

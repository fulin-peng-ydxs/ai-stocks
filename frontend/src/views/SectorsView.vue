<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { Sort } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import CandleChart from '@/components/CandleChart.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import SectorCompareChart from '@/components/SectorCompareChart.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import {
  getSectorBars,
  listSectors,
  type BoardType,
  type SectorBar,
  type SectorRow,
  type SectorSortField,
} from '@/api/sectors'
import type { Bar } from '@/api/stocks'
import { ALL_DAYS, useKlinePrefs } from '@/composables/useKlinePrefs'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useTableSort } from '@/composables/useTableSort'
import { useTradeDates } from '@/composables/useTradeDates'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getErrorMessage, getErrorStatus } from '@/utils/error'

const route = useRoute()
const { dataMin, dataMax, ensureLoaded } = useTradeDates()
const settingsOpen = ref(false)

const sectorsDefaults = { defaultType: '' as BoardType | '' }
const { settings, isDirty, reset } = usePageSettings('sectors', sectorsDefaults)

const sectorsLayout = getPageLayout('sectors')
const {
  effective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
} = useRemoteLayoutConfig(sectorsLayout)
const drawerConfig = {
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  layerValuesOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
}

const DEFAULT_SORT = 'pct_today:desc'
const SORTABLE_FIELDS = ['pct_today', 'pct_5d', 'net_inflow'] as const
const {
  sortBy,
  sortOrder,
  elementDefaultSort,
  onSortChange: onTableSortChange,
} = useTableSort<SectorSortField>({
  slotId: 'table',
  defaultSort: DEFAULT_SORT,
  componentValueOf,
  setComponentKnob,
  allowedFields: SORTABLE_FIELDS,
})

const TYPE_OPTIONS: { label: string; value: BoardType | '' }[] = [
  { label: '全部板块', value: '' },
  { label: '概念', value: 'concept' },
  { label: '行业', value: 'industry' },
]
const CHART_MODE_OPTIONS = [
  { label: '强弱对比', value: 'compare' },
  { label: '指数 K 线', value: 'kline' },
]

const defaultSize = computed<number>(() => {
  const value = componentValueOf('table', 'pageSize')
  return typeof value === 'number' ? value : 20
})
const hiddenColumns = computed<string[]>(() =>
  (componentValueOf('table', 'hiddenColumns') as string[]) ?? [],
)
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

const loading = ref(false)
const loadError = ref('')
const forbidden = ref(false)
const tradeDate = ref<string | null>('')
const marketDate = ref<string | null>(null)
const boardType = ref<BoardType | ''>(settings.defaultType)
const keyword = ref('')
const page = ref(1)
const size = ref(defaultSize.value)
const total = ref(0)
const rows = ref<SectorRow[]>([])
const fundFlowDate = ref<string | null>(null)
const boardLookup = ref<Record<string, SectorRow>>({})

let restoring = false
let searchTimer: ReturnType<typeof setTimeout> | null = null

// 行点击只切换主观察对象；勾选“对比”会把板块固定在图中，跨分页仍保留。
const COMPARE_MAX = 6
const activeCode = ref('')
const pinnedCodes = ref<string[]>([])
const { validDefault: klineDefaultRange } = useKlinePrefs()
const rangeDays = ref<number>(klineDefaultRange.value)
const chartMode = ref<'compare' | 'kline'>('compare')
const basis = ref<'first' | 'mid'>('first')
const chartLoading = ref(false)
const chartError = ref('')
const compareBars = ref<Record<string, SectorBar[]>>({})
let chartRequestVersion = 0

const activeRow = computed(() => boardLookup.value[activeCode.value] ?? null)
const chartCodes = computed(() => {
  if (!activeCode.value) return []
  if (chartMode.value === 'kline') return [activeCode.value]
  return Array.from(new Set([activeCode.value, ...pinnedCodes.value])).slice(0, COMPARE_MAX)
})
const compareRows = computed(() =>
  chartCodes.value
    .map((code) => boardLookup.value[code])
    .filter((row): row is SectorRow => Boolean(row)),
)
const compareSeries = computed(() =>
  compareRows.value
    .filter((row) => compareBars.value[row.board_code]?.length)
    .map((row) => ({
      code: row.board_code,
      name: row.name,
      bars: compareBars.value[row.board_code]!,
    })),
)
const klineBars = computed<Bar[]>(() =>
  (compareBars.value[activeCode.value] ?? []).map((bar) => ({
    date: bar.trade_date,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    pre_close: null,
    volume: bar.volume,
    amount: bar.amount,
    turnover_rate: null,
  })),
)

function chartEnd(): string {
  return tradeDate.value || marketDate.value || dataMax.value || ''
}
function rangeStart(): string {
  const endValue = chartEnd()
  if (rangeDays.value === ALL_DAYS) return dataMin.value || endValue
  const end = endValue ? new Date(`${endValue}T00:00:00`) : new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - rangeDays.value)
  return `${start.getFullYear()}-${`${start.getMonth() + 1}`.padStart(2, '0')}-${`${start.getDate()}`.padStart(2, '0')}`
}

async function loadChart(): Promise<void> {
  const codes = chartCodes.value
  if (!codes.length) {
    compareBars.value = {}
    chartError.value = ''
    return
  }
  const start = rangeStart()
  const end = chartEnd() || start
  if (!start || !end) return

  const requestVersion = ++chartRequestVersion
  chartLoading.value = true
  chartError.value = ''
  try {
    const results = await Promise.all(
      codes.map(async (code) => {
        const result = await getSectorBars(code, start, end)
        return [code, result.list] as const
      }),
    )
    if (requestVersion !== chartRequestVersion) return
    compareBars.value = Object.fromEntries(results)
  } catch (error) {
    if (requestVersion !== chartRequestVersion) return
    chartError.value = getErrorMessage(error, '板块走势加载失败')
  } finally {
    if (requestVersion === chartRequestVersion) chartLoading.value = false
  }
}

function isPinned(code: string): boolean {
  return pinnedCodes.value.includes(code)
}
function togglePinned(row: SectorRow, checked: boolean): void {
  boardLookup.value = { ...boardLookup.value, [row.board_code]: row }
  if (checked) {
    if (!isPinned(row.board_code)) {
      const capacity = activeCode.value && !isPinned(activeCode.value) ? COMPARE_MAX - 1 : COMPARE_MAX
      pinnedCodes.value = [...pinnedCodes.value, row.board_code].slice(-capacity)
    }
  } else {
    pinnedCodes.value = pinnedCodes.value.filter((code) => code !== row.board_code)
  }
  void loadChart()
}
function removeCompared(code: string): void {
  if (code === activeCode.value) {
    const next = pinnedCodes.value.find((item) => item !== code) || rows.value[0]?.board_code || ''
    activeCode.value = next
  }
  pinnedCodes.value = pinnedCodes.value.filter((item) => item !== code)
  void loadChart()
}
function selectRow(row: SectorRow): void {
  boardLookup.value = { ...boardLookup.value, [row.board_code]: row }
  if (activeCode.value === row.board_code) return
  activeCode.value = row.board_code
  void loadChart()
}
function rowClassName({ row }: { row: SectorRow }): string {
  return row.board_code === activeCode.value ? 'sector-row--active' : ''
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  forbidden.value = false
  try {
    const data = await listSectors({
      trade_date: tradeDate.value || undefined,
      board_type: boardType.value || undefined,
      sort_by: sortBy.value,
      order: sortOrder.value,
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      size: size.value,
    })
    rows.value = data.list
    total.value = data.total
    marketDate.value = data.trade_date
    fundFlowDate.value = data.fund_flow_date
    boardLookup.value = {
      ...boardLookup.value,
      ...Object.fromEntries(data.list.map((row) => [row.board_code, row])),
    }

    const maxPage = Math.max(1, Math.ceil(data.total / size.value))
    if (page.value > maxPage) {
      page.value = maxPage
      return load()
    }

    // 首屏直接呈现可用走势，避免必须先理解控件才能看到内容。
    if (!activeCode.value && data.list.length) {
      activeCode.value = data.list[0]!.board_code
      pinnedCodes.value = data.list.slice(1, 3).map((row) => row.board_code)
      void loadChart()
    }
  } catch (error) {
    if (getErrorStatus(error) === 403) forbidden.value = true
    loadError.value = getErrorMessage(error, '板块列表加载失败')
  } finally {
    loading.value = false
  }
}

function search(): void {
  page.value = 1
  void load()
}
function scheduleSearch(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = null
    search()
  }, 300)
}
function onDateChange(): void {
  if (restoring) return
  search()
  void loadChart()
}

watch([sortBy, sortOrder], () => {
  if (restoring) return
  page.value = 1
  void load()
})
watch(defaultSize, (value) => {
  if (restoring) return
  size.value = value
  page.value = 1
  void load()
})
watch([rangeDays, chartMode], () => {
  if (restoring) return
  void loadChart()
})

interface SanitizedQuery {
  type?: BoardType
  sort?: SectorSortField
  order?: 'asc' | 'desc'
  keyword?: string
  page?: string
}
function sanitizeQuery(raw: typeof route.query): SanitizedQuery {
  const result: SanitizedQuery = {}
  const get = (key: string): string => {
    const value = raw[key]
    return typeof value === 'string' ? value : ''
  }
  const type = get('type')
  if (type === 'concept' || type === 'industry') result.type = type
  const sort = get('sort')
  if ((SORTABLE_FIELDS as readonly string[]).includes(sort)) result.sort = sort as SectorSortField
  const order = get('order')
  if (order === 'asc' || order === 'desc') result.order = order
  const queryKeyword = get('keyword').slice(0, 50)
  if (queryKeyword) result.keyword = queryKeyword
  const pageNumber = Number(get('page'))
  if (Number.isInteger(pageNumber) && pageNumber >= 1) result.page = String(pageNumber)
  return result
}

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}
function fmtInflow(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}亿`
}
function pctClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'muted'
  return value > 0 ? 'up' : value < 0 ? 'down' : ''
}
function fmtFlowDate(value: string | null): string {
  return value ? value.slice(5) : '—'
}

onMounted(async () => {
  await ensureLoaded().catch(() => undefined)
  const query = sanitizeQuery(route.query)
  restoring = true
  if (!tradeDate.value) tradeDate.value = dataMax.value || ''
  boardType.value = query.type ?? settings.defaultType
  keyword.value = query.keyword ?? ''
  page.value = query.page ? Number(query.page) : 1
  size.value = defaultSize.value
  if (query.sort) {
    onTableSortChange({
      prop: query.sort,
      order: (query.order ?? 'desc') === 'desc' ? 'descending' : 'ascending',
    })
  }
  restoring = false
  void load()
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <!-- <div class="page-kicker">MARKET SECTORS</div> -->
            <h2 class="app-page-title">板块行情</h2>
            <p class="page-subtitle">从强弱排行定位主线，点选板块后在同一视野比较走势。</p>
          </div>
          <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
        </div>

        <el-card shadow="never" class="filter-card">
          <AppControlRow class="filter-row">
            <PageSegmented
              v-model="boardType"
              :options="TYPE_OPTIONS"
              aria-label="板块类型"
              test-id="sectors-type"
              size="small"
              @update:model-value="search"
            />
            <TradeDatePicker
              v-model="tradeDate"
              placeholder="交易日期"
              class="date-picker"
              @update:model-value="onDateChange"
            />
            <el-input
              v-model="keyword"
              placeholder="搜索板块"
              class="keyword-input"
              clearable
              maxlength="50"
              data-testid="sectors-keyword"
              @input="scheduleSearch"
              @clear="search"
              @keyup.enter="search"
            />
            <div class="filter-divider" aria-hidden="true" />
            <KlineRangeSelect v-model="rangeDays" test-id="sectors-range" />
            <PageSegmented
              v-model="chartMode"
              :options="CHART_MODE_OPTIONS"
              aria-label="图表模式"
              test-id="sectors-chart-mode"
              size="small"
            />
          </AppControlRow>
        </el-card>
      </div>
    </template>

    <template #main>
      <AppStateBlock
        v-if="forbidden"
        state="error"
        variant="permission"
        title="无权限查看板块行情"
        description="请联系系统管理员调整权限"
      />
      <AppStateBlock
        v-else-if="loadError && !rows.length"
        state="error"
        title="板块行情加载失败"
        :description="loadError"
        retry
        @retry="load"
      />
      <div v-else class="sector-workspace" data-testid="sectors-workspace">
        <section class="rank-panel" aria-label="板块强弱排行">
          <header class="panel-head rank-head">
            <div>
              <div class="panel-eyebrow">强弱排行</div>
              <h3 class="app-section-title">{{ marketDate || tradeDate || '最新交易日' }}</h3>
            </div>
            <div class="rank-meta app-caption-text">
              <span>{{ total }} 个板块</span>
              <span>点击行切换走势</span>
            </div>
          </header>

          <AppStateBlock
            v-if="loadError"
            state="error"
            size="compact"
            title="排行刷新失败"
            :description="loadError"
            retry
            @retry="load"
          />

          <AppDataTable
            data-testid="sectors-table"
            :data="rows"
            :loading="loading"
            row-key="board_code"
            :row-class-name="rowClassName"
            :border="tableBorder('table')"
            :default-sort="elementDefaultSort"
            clickable
            aria-label="板块强弱排行"
            :pagination="{ currentPage: page, pageSize: size, total, pageSizes: PAGE_SIZE_OPTIONS, small: true }"
            @row-click="selectRow"
            @sort-change="onTableSortChange"
            @page-change="(value: number) => { page = value; void load() }"
            @size-change="(value: number) => { size = value; page = 1; void load() }"
          >
            <AppTableColumn v-if="colVisible('name')" label="板块" prop="name" role="name">
              <template #default="{ row }">
                <div
                  class="sector-name-cell"
                  :data-testid="row?.board_code ? `sectors-row-${row.board_code}` : undefined"
                >
                  <el-checkbox
                    :model-value="isPinned(row.board_code)"
                    :aria-label="`${isPinned(row.board_code) ? '移出' : '加入'}对比：${row.name}`"
                    :data-testid="row?.board_code ? `sectors-pin-${row.board_code}` : undefined"
                    @click.stop
                    @change="(checked: boolean) => togglePinned(row, checked)"
                  />
                  <div class="sector-name-copy">
                    <el-button link type="primary" class="sector-select" @click.stop="selectRow(row)">
                      {{ row.name }}
                    </el-button>
                    <span>{{ row.board_type === 'concept' ? '概念' : '行业' }} · {{ row.member_count ?? '—' }}只</span>
                  </div>
                </div>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_today')"
              label="今日"
              prop="pct_today"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <strong class="app-data-text" :class="pctClass(row.pct_today)">{{ fmtPct(row.pct_today) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_5d')"
              label="5日"
              prop="pct_5d"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.pct_5d)">{{ fmtPct(row.pct_5d) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow')"
              label="净流入"
              prop="net_inflow"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #header>
                <span>净流入</span><span class="header-date">{{ fmtFlowDate(fundFlowDate) }}</span>
              </template>
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.net_inflow)">{{ fmtInflow(row.net_inflow) }}</span>
              </template>
            </AppTableColumn>
            <template #empty>
              <span>{{ keyword.trim() ? '没有匹配板块，换个关键词试试' : '暂无板块数据，请先运行板块采集' }}</span>
            </template>
          </AppDataTable>
        </section>

        <section class="chart-panel" aria-label="板块走势分析" data-testid="sectors-chart">
          <header class="panel-head chart-head">
            <div class="chart-identity">
              <div class="panel-eyebrow">当前观察</div>
              <div class="chart-title-line">
                <h3 class="chart-title" data-testid="sectors-chart-title">{{ activeRow?.name || '等待选择板块' }}</h3>
                <span v-if="activeRow" class="board-code">{{ activeRow.board_code }}</span>
              </div>
              <p>{{ chartMode === 'compare' ? `与 ${Math.max(0, chartCodes.length - 1)} 个板块对比区间强弱` : '查看板块指数开高低收与量能' }}</p>
            </div>
            <div v-if="activeRow" class="leader-summary app-caption-text">
              <template v-if="activeRow.leader_stock">
                领涨 {{ activeRow.leader_stock }}
                <strong :class="pctClass(activeRow.leader_pct)">{{ fmtPct(activeRow.leader_pct) }}</strong>
              </template>
              <template v-else>成分 {{ activeRow.member_count ?? '—' }} 只</template>
            </div>
          </header>

          <div v-if="activeRow" class="market-strip" aria-label="板块关键指标">
            <div class="market-metric market-metric--lead">
              <span>今日涨幅</span>
              <strong :class="pctClass(activeRow.pct_today)">{{ fmtPct(activeRow.pct_today) }}</strong>
            </div>
            <div class="market-metric">
              <span>5 日</span>
              <strong :class="pctClass(activeRow.pct_5d)">{{ fmtPct(activeRow.pct_5d) }}</strong>
            </div>
            <div class="market-metric">
              <span>20 日</span>
              <strong :class="pctClass(activeRow.pct_20d)">{{ fmtPct(activeRow.pct_20d) }}</strong>
            </div>
            <div class="market-metric">
              <span>即时净流入</span>
              <strong :class="pctClass(activeRow.net_inflow)">{{ fmtInflow(activeRow.net_inflow) }}</strong>
            </div>
            <div class="market-metric">
              <span>涨 / 跌</span>
              <strong><i class="up">{{ activeRow.up_count }}</i> / <i class="down">{{ activeRow.down_count }}</i></strong>
            </div>
          </div>

          <div v-if="chartMode === 'compare' && chartCodes.length" class="compare-rail" aria-label="当前对比板块">
            <span class="compare-label">对比队列</span>
            <div
              v-for="row in compareRows"
              :key="row.board_code"
              class="compare-chip"
              :class="{ active: row.board_code === activeCode }"
              :data-testid="`sectors-compare-${row.board_code}`"
              role="button"
              tabindex="0"
              @click="selectRow(row)"
              @keydown.enter="selectRow(row)"
            >
              <span>{{ row.name }}</span>
              <AppIconButton
                v-if="row.board_code !== activeCode || compareRows.length > 1"
                class="chip-remove"
                :label="`移除对比：${row.name}`"
                :data-testid="`sectors-remove-${row.board_code}`"
                size="xs"
                :native-title="false"
                @click.stop="removeCompared(row.board_code)"
              >
                <el-icon><Close /></el-icon>
              </AppIconButton>
            </div>
            <span v-if="chartCodes.length < COMPARE_MAX" class="compare-hint">勾选左侧板块加入，最多 {{ COMPARE_MAX }} 个</span>
          </div>

          <div class="chart-stage" v-loading="chartLoading">
            <AppStateBlock
              v-if="chartError"
              state="error"
              title="板块走势加载失败"
              :description="chartError"
              retry
              @retry="loadChart"
            />
            <AppStateBlock
              v-else-if="!activeCode"
              state="empty"
              title="选择一个板块"
              description="点击左侧排行中的任意一行即可查看走势"
            />
            <AppStateBlock
              v-else-if="!chartLoading && chartMode === 'compare' && !compareSeries.length"
              state="empty"
              title="暂无指数走势"
              description="可切换其他板块，或先运行板块指数采集"
            />
            <AppStateBlock
              v-else-if="!chartLoading && chartMode === 'kline' && !klineBars.length"
              state="empty"
              title="暂无 K 线数据"
              description="可切换其他板块，或先运行板块指数采集"
            />
            <SectorCompareChart
              v-else-if="chartMode === 'compare'"
              :series="compareSeries"
              :basis="basis"
              fill
            />
            <CandleChart v-else :bars="klineBars" fill />
          </div>

          <footer v-if="chartMode === 'compare'" class="chart-footer">
            <span>基准</span>
            <el-radio-group v-model="basis" size="small" aria-label="归一化基准" data-testid="sectors-compare-basis">
              <el-radio-button value="first">区间首日 = 0</el-radio-button>
              <el-radio-button value="mid">区间中点 = 0</el-radio-button>
            </el-radio-group>
            <span class="chart-note">仅比较相对涨跌，不比较指数点位</span>
          </footer>
        </section>
      </div>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="板块行情"
        :dirty="isDirty || layoutDirty"
        page-key="sectors"
        :config="drawerConfig"
        :business-visible="true"
        @reset="reset(); resetLayout()"
      >
        <template #business>
          <PageSettingSection title="默认查询">
            <div class="setting-item">
              <div class="setting-label">默认类型</div>
              <PageSegmented
                v-model="settings.defaultType"
                :options="TYPE_OPTIONS"
                aria-label="默认类型"
                test-id="sectors-default-type"
              />
            </div>
          </PageSettingSection>
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.page-kicker,
.panel-eyebrow {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.page-subtitle {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.filter-card {
  margin-bottom: 0;
}
.filter-card :deep(.el-card__body) {
  padding: var(--app-space-3) var(--app-space-4);
}
.filter-row {
  flex-wrap: wrap;
}
.date-picker {
  width: 164px;
}
.keyword-input {
  width: 200px;
}
.filter-divider {
  width: 1px;
  height: var(--app-control-height-md);
  margin: 0 var(--app-space-1);
  background: var(--el-border-color-lighter);
}
.sector-workspace {
  height: 100%;
  min-height: 0;
  min-width: 860px;
  display: grid;
  grid-template-columns: minmax(360px, 0.82fr) minmax(500px, 1.18fr);
  gap: var(--app-space-3);
  overflow-x: auto;
}
.rank-panel,
.chart-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
  box-shadow: inset 0 1px 0 color-mix(in srgb, white 18%, transparent);
}
.rank-panel,
.chart-panel {
  display: flex;
  flex-direction: column;
}
.panel-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.rank-head {
  min-height: 64px;
  background: color-mix(in srgb, var(--el-color-primary-light-9) 42%, var(--el-bg-color));
}
.rank-meta {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
}
.rank-panel :deep(.app-data-table) {
  flex: 1 1 auto;
  min-height: 0;
}
.rank-panel :deep(.el-table__row.sector-row--active > td.el-table__cell) {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, var(--el-bg-color));
}
.rank-panel :deep(.el-table__row.sector-row--active > td:first-child) {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
.sector-name-cell {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}
.sector-name-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  line-height: var(--app-line-height-table);
}
.sector-select {
  overflow: hidden;
  padding: 0;
  height: auto;
  min-height: 0;
  font-weight: var(--app-font-weight-section);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sector-select:hover {
  color: var(--el-color-primary-dark-2);
}
.sector-select:focus-visible {
  border-radius: 2px;
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: 1px;
}
.sector-name-copy > span {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-date {
  margin-left: var(--app-space-1);
  color: var(--el-text-color-placeholder);
  font-size: var(--app-font-size-tiny);
}
.chart-panel {
  position: relative;
}
.chart-head {
  min-height: 72px;
}
.chart-identity {
  min-width: 0;
}
.chart-title-line {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}
.chart-title {
  overflow: hidden;
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-title-md);
  line-height: var(--app-line-height-title-md);
  font-weight: var(--app-font-weight-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.board-code {
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-micro);
}
.chart-identity p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.leader-summary {
  flex: 0 0 auto;
  text-align: right;
}
.leader-summary strong {
  margin-left: var(--app-space-1);
  font-variant-numeric: tabular-nums;
}
.market-strip {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: repeat(5, minmax(84px, 1fr));
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: color-mix(in srgb, var(--el-fill-color-light) 54%, var(--el-bg-color));
}
.market-metric {
  min-width: 0;
  padding: var(--app-space-2) var(--app-space-3);
  border-right: 1px solid var(--el-border-color-lighter);
}
.market-metric:last-child {
  border-right: 0;
}
.market-metric span {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
}
.market-metric strong {
  display: block;
  overflow: hidden;
  margin-top: 2px;
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-data);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-metric strong i {
  font-style: normal;
}
.market-metric--lead {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 58%, transparent);
}
.compare-rail {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  min-height: 42px;
  padding: var(--app-space-2) var(--app-space-3);
  overflow-x: auto;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}
.compare-label,
.compare-hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
}
.compare-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  height: var(--app-control-height-sm);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius);
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  cursor: pointer;
  font: inherit;
  font-size: var(--app-font-size-caption);
}
.compare-chip:hover,
.compare-chip.active {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.compare-chip:focus-visible {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: 1px;
}
.chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  --app-icon-button-size: 18px;
  --app-icon-button-glyph: 11px;
  border-radius: 50%;
  color: var(--el-text-color-secondary);
}
.chart-stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 300px;
  overflow: hidden;
}
.chart-stage :deep(.cmp-wrap),
.chart-stage :deep(.cmp),
.chart-stage :deep(.candle-wrap) {
  height: 100%;
}
.chart-footer {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-height: 44px;
  padding: var(--app-space-2) var(--app-space-3);
  border-top: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.chart-note {
  margin-left: auto;
  color: var(--el-text-color-placeholder);
}
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-body);
}
.up {
  color: var(--market-up-color);
}
.down {
  color: var(--market-down-color);
}
.muted {
  color: var(--app-placeholder-text);
}
@media (max-width: 1180px) {
  .page-subtitle,
  .chart-note {
    display: none;
  }
  .filter-divider {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .compare-chip {
    transition: none;
  }
}
</style>

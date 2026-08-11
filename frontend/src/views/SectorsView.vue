<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import { computed, onMounted, ref, watch } from 'vue'
import type { Sort } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { listSectors, type BoardType, type SectorRow, type SectorSortField } from '@/api/sectors'
import { usePageSettings } from '@/composables/usePageSettings'
import { useTableSort } from '@/composables/useTableSort'
import { useTradeDates } from '@/composables/useTradeDates'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getErrorMessage, getErrorStatus } from '@/utils/error'

const router = useRouter()
const route = useRoute()
const { dataMax, ensureLoaded } = useTradeDates()
const settingsOpen = ref(false)

// 默认类型属业务态偏好（页面记忆）；'' = 全部板块。默认排序、每页条数、列显隐迁入组件配置层 table slot。
const sectorsDefaults = {
  defaultType: '' as BoardType | '',
}
const { settings, isDirty, reset } = usePageSettings('sectors', sectorsDefaults)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
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

// 设置抽屉的「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, layerValuesOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, componentLayerValuesOf }

// 排序走通用列头排序 + defaultSort 配置（与 StocksView 同链路），不另设周期控件——周期属数据窗口，留给详情页图表。
const DEFAULT_SORT = 'pct_today:desc'
const SORTABLE_FIELDS = ['pct_today', 'pct_5d', 'pct_10d', 'pct_20d', 'net_inflow', 'up_count'] as const
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
  { label: '概念板块', value: 'concept' },
  { label: '行业板块', value: 'industry' },
]

// ── 组件配置消费的派生值 ──
const defaultSize = computed<number>(() => {
  const v = componentValueOf('table', 'pageSize')
  return typeof v === 'number' ? v : 20
})
const hiddenColumns = computed<string[]>(() => (componentValueOf('table', 'hiddenColumns') as string[]) ?? [])
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

// ── 筛选与列表状态 ──
const loading = ref(false)
const loadError = ref('')
const forbidden = ref(false)
const tradeDate = ref<string | null>('')
const boardType = ref<BoardType | ''>(settings.defaultType)
const keyword = ref('')
const page = ref(1)
const size = ref(defaultSize.value)
const total = ref(0)
const rows = ref<SectorRow[]>([])
const fundFlowDate = ref<string | null>(null)

let restoring = false
let searchTimer: ReturnType<typeof setTimeout> | null = null

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
    fundFlowDate.value = data.fund_flow_date
    // 分页越界回落（筛选/条数变化后总数缩小导致当前页超界）。
    const maxPage = Math.max(1, Math.ceil(data.total / size.value))
    if (page.value > maxPage) {
      page.value = maxPage
      return load()
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
  if (!restoring) search()
}

watch([sortBy, sortOrder], () => {
  if (restoring) return
  page.value = 1
  void load()
})
watch(defaultSize, (v) => {
  if (restoring) return
  size.value = v
  page.value = 1
  void load()
})

// ── 筛选态 URL query（白名单）──
interface SanitizedQuery {
  type?: BoardType
  sort?: SectorSortField
  order?: 'asc' | 'desc'
  keyword?: string
  page?: string
}
function currentQuery(): Record<string, string> {
  const q: Record<string, string> = {}
  if (boardType.value) q.type = boardType.value
  q.sort = sortBy.value
  q.order = sortOrder.value
  if (keyword.value.trim()) q.keyword = keyword.value.trim()
  if (page.value > 1) q.page = String(page.value)
  return q
}
function sanitizeQuery(raw: typeof route.query): SanitizedQuery {
  const out: SanitizedQuery = {}
  const get = (k: string): string => {
    const v = raw[k]
    return typeof v === 'string' ? v : ''
  }
  const type = get('type')
  if (type === 'concept' || type === 'industry') out.type = type
  const sort = get('sort')
  if ((SORTABLE_FIELDS as readonly string[]).includes(sort)) out.sort = sort as SectorSortField
  const order = get('order')
  if (order === 'asc' || order === 'desc') out.order = order
  const keyword = get('keyword').slice(0, 50)
  if (keyword) out.keyword = keyword
  const pageNum = Number(get('page'))
  if (Number.isInteger(pageNum) && pageNum >= 1) out.page = String(pageNum)
  return out
}

// 仅点板块名进详情，携带来源筛选态 query。
function enterDetail(row: SectorRow): void {
  router.push({ path: `/sectors/${row.board_code}`, query: currentQuery() })
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(2) + '%'
}
function fmtInflow(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(2) + '亿'
}
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'muted'
  return v > 0 ? 'up' : v < 0 ? 'down' : ''
}
function fmtFlowDate(v: string | null): string {
  return v ? v.slice(5) : '—'
}

onMounted(async () => {
  // 交易日默认选中最新交易日（而非留空靠占位提示）。
  await ensureLoaded().catch(() => undefined)
  const q = sanitizeQuery(route.query)
  restoring = true
  if (!tradeDate.value) tradeDate.value = dataMax.value || ''
  // 优先级：URL query > 已保存偏好 > 默认值。
  boardType.value = q.type ?? settings.defaultType
  keyword.value = q.keyword ?? ''
  page.value = q.page ? Number(q.page) : 1
  size.value = defaultSize.value
  // 主排序：query.sort/order 优先；否则组件配置默认排序（useTableSort 已生效）。
  if (q.sort) {
    onTableSortChange({ prop: q.sort, order: (q.order ?? 'desc') === 'desc' ? 'descending' : 'ascending' })
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
          <h2>板块行情</h2>
          <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
        </div>

        <el-card shadow="never" class="filter-card">
          <AppControlRow class="filter-row">
            <el-select
              v-model="boardType"
              placeholder="全部板块"
              style="width: 130px"
              data-testid="sectors-type"
              @change="search"
            >
              <el-option v-for="opt in TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
            <TradeDatePicker v-model="tradeDate" placeholder="交易日期" style="width: 180px" @update:model-value="onDateChange" />
            <el-input
              v-model="keyword"
              placeholder="搜索板块名称…"
              style="width: 220px"
              clearable
              maxlength="50"
              data-testid="sectors-keyword"
              @input="scheduleSearch"
              @clear="search"
              @keyup.enter="search"
            />
            <el-button type="primary" :loading="loading" data-testid="sectors-search" @click="search">查询</el-button>
          </AppControlRow>
        </el-card>
      </div>
    </template>

    <template #main>
      <el-card shadow="never">
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
          title="板块列表加载失败"
          :description="loadError"
          retry
          @retry="load"
        />
        <template v-else>
          <AppStateBlock
            v-if="loadError"
            state="error"
            size="compact"
            title="板块列表刷新失败"
            :description="loadError"
            retry
            @retry="load"
          />
          <AppDataTable
            :data="rows"
            :loading="loading"
            row-key="board_code"
            :border="tableBorder('table')"
            :default-sort="elementDefaultSort"
            aria-label="板块行情列表"
            :pagination="{ currentPage: page, pageSize: size, total, pageSizes: PAGE_SIZE_OPTIONS }"
            @sort-change="onTableSortChange"
            @page-change="(p: number) => { page = p; void load() }"
            @size-change="(s: number) => { size = s; page = 1; void load() }"
          >
            <AppTableColumn v-if="colVisible('name')" label="板块名称" prop="name" role="name">
              <template #default="{ row }">
                <el-link type="primary" :underline="false" @click="enterDetail(row)">{{ row.name }}</el-link>
              </template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('member_count')" label="成分股数" prop="member_count" role="number" align="right">
              <template #default="{ row }">{{ row.member_count ?? '—' }}</template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('updown')" label="上涨/下跌" prop="up_count" sortable="custom" role="number" align="center">
              <template #default="{ row }">
                <span class="up">{{ row.up_count }}</span> / <span class="down">{{ row.down_count }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('pct_today')" label="今日涨幅" prop="pct_today" sortable="custom" role="number" align="right">
              <template #default="{ row }"><b :class="pctClass(row.pct_today)">{{ fmtPct(row.pct_today) }}</b></template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('pct_5d')" label="5日涨幅" prop="pct_5d" sortable="custom" role="number" align="right">
              <template #default="{ row }"><b :class="pctClass(row.pct_5d)">{{ fmtPct(row.pct_5d) }}</b></template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('pct_10d')" label="10日涨幅" prop="pct_10d" sortable="custom" role="number" align="right">
              <template #default="{ row }"><b :class="pctClass(row.pct_10d)">{{ fmtPct(row.pct_10d) }}</b></template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('pct_20d')" label="20日涨幅" prop="pct_20d" sortable="custom" role="number" align="right">
              <template #default="{ row }"><b :class="pctClass(row.pct_20d)">{{ fmtPct(row.pct_20d) }}</b></template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('net_inflow')" label="即时净流入" prop="net_inflow" sortable="custom" role="number" align="right">
              <template #default="{ row }">
                <b :class="pctClass(row.net_inflow)">{{ fmtInflow(row.net_inflow) }}</b>
                <span class="flow-date muted">{{ fmtFlowDate(fundFlowDate) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn v-if="colVisible('leader')" label="领涨股" prop="leader_stock" role="name">
              <template #default="{ row }">
                <template v-if="row.leader_stock">
                  {{ row.leader_stock }} <b :class="pctClass(row.leader_pct)">{{ fmtPct(row.leader_pct) }}</b>
                </template>
                <span v-else class="muted">—</span>
              </template>
            </AppTableColumn>
            <template #empty>
              <span>{{ keyword.trim() ? '无匹配板块，请调整搜索关键词' : '暂无板块数据，请先在数据采集页运行板块采集' }}</span>
            </template>
          </AppDataTable>
        </template>
      </el-card>
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
  justify-content: space-between;
  align-items: center;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}
.page-head h2 {
  margin: 0;
  font-size: var(--app-font-size-page-title-sm);
}
.filter-card {
  margin-bottom: 0;
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
.up {
  color: var(--market-up-color);
}
.down {
  color: var(--market-down-color);
}
.muted {
  color: var(--app-placeholder-text);
}
.flow-date {
  margin-left: 4px;
  font-size: var(--app-font-size-caption);
}
</style>

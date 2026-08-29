<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import StockCodeMultiSelect from '@/components/data/StockCodeMultiSelect.vue'
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  getOverview, getCatalog, getDimensions, getStockQuality, LAYER_DESC, BOARD_ISSUE_ITEMS,
  type Overview, type CatalogTable, type Dimension, type StockQuality,
} from '@/api/data'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpHint from '@/components/HelpHint.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const settingsOpen = ref(false)
const overviewDefaults = {
  focusLayer: 'all' as 'all' | 'L12' | 'L34',
  kpi: { latestTradeDate: true, codes: true, barRows: true, board: true, score: true, quality: true, gaps: true },
}
const { settings, isDirty, reset } = usePageSettings('data-overview', overviewDefaults)

// 布局声明统一取自 pageRegistry（单一事实源），不再页面内联手写 PageLayout。
const overviewLayout = getPageLayout('data-overview')
const {
  effective: overviewEffective,
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
} = useRemoteLayoutConfig(overviewLayout)

// 抽屉「布局 / 组件设置」由 PageSettingsDrawer 自动渲染；tabs 与表格字段按 registry 实例元数据继承。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf, componentAllowedLayers }
// 工作区 tab 单向：组件配置层默认值（workspace.defaultActive）→ 会话 ref；切换不写回配置层。
const workspaceTabDefault = computed<'assets' | 'stocks' | 'board'>(() =>
  (componentValueOf('workspace', 'defaultActive') as 'assets' | 'stocks' | 'board') || 'assets',
)
const activeWorkspaceTab = ref(workspaceTabDefault.value)
watch(workspaceTabDefault, (value) => { activeWorkspaceTab.value = value })
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}
const loading = ref(true)
const error = ref('')
const ov = ref<Overview | null>(null)
const tables = ref<CatalogTable[]>([])
const dims = ref<Dimension[]>([])

// 逐股质量
const sq = ref<StockQuality | null>(null)
const sqLoading = ref(true)
const sqError = ref('')
const sqSelected = ref<string[]>([])
const sqPage = ref(1)
const { pageSize: sqSize, changePageSize: changeSqSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('stockTable', 'pageSize'),
  fallback: DEFAULT_PAGE_SIZE,
  shouldSync: () => sq.value != null,
  resetPage: () => { sqPage.value = 1 },
  reload: () => loadSq(),
})

const DIM_STATUS: Record<string, { label: string; type: 'success' | 'info' | 'warning' }> = {
  collected: { label: '已采集', type: 'success' },
  partial: { label: '部分覆盖', type: 'warning' },
  planned: { label: '规划中', type: 'info' },
}

// 数据资产表（DM-D13）：数据字典 + 维度注册表合并为一张表。
// 已采集维度映射到物理表显示运行时统计；规划中维度（无物理表）作占位行。
const assets = computed(() => {
  const dimByTable: Record<string, Dimension> = {}
  for (const d of dims.value) for (const t of d.tables) dimByTable[t] = d
  const rows: any[] = []
  for (const t of tables.value) {
    const d = dimByTable[t.table]
    rows.push({
      key: t.table, name_cn: t.name_cn, table: t.table,
      status: d?.status ?? 'collected', source: d?.source ?? '—',
      rows: t.rows, latest_time: t.latest_time, fresh: t.fresh,
      open_issues: t.open_issues, fields: t.fields, purpose: t.purpose,
      relations: t.relations, planned: false,
    })
  }
  // 规划中维度：无对应物理表的（如股东数/筹码峰）作占位行
  for (const d of dims.value) {
    if (d.tables.every((t) => !tables.value.find((x) => x.table === t))) {
      rows.push({
        key: 'dim:' + d.dimension, name_cn: d.name_cn, table: '—',
        status: d.status, source: d.source, rows: 0, latest_time: null, fresh: null,
        open_issues: 0, fields: [], purpose: d.descr, relations: [], planned: true,
      })
    }
  }
  return rows
})

// 表级质量徽章：纳入鲜活度（最新时间空/滞后 → 不再误判"正常"）。
function tableQuality(row: any): { type: string; text: string } {
  if (row.planned) return { type: 'info', text: '规划中' }
  if (row.fresh === false) return { type: 'danger', text: row.latest_time ? '数据滞后' : '无数据' }
  if (row.open_issues > 0) return { type: 'warning', text: `${row.open_issues} 待处理` }
  return { type: 'success', text: '正常' }
}

const scoreColor = computed(() => {
  const s = ov.value?.quality.score ?? 0
  return s >= 90 ? 'var(--el-color-success)' : s >= 70 ? 'var(--app-warning-text)' : 'var(--app-danger-text)'
})

// 逐股四层列（DM-D15）：每列即一层，hover 出具体结果，点击进对应解决页。
// 列头短名（去掉 "Lx " 前缀）；层定义说明统一引用 data.ts 的权威 LAYER_DESC（单一出处）
const LAYER_CN: Record<string, string> = {
  L1: '入库闸门', L2: '字段契约', L3: '正确性', L4: '覆盖鲜活',
}
function layerCell(k: string, lay: any): { type: string; text: string; tip: string } {
  if (!lay) return { type: 'info', text: '—', tip: '' }
  if (lay.ok) {
    const okTip: Record<string, string> = {
      L1: '入库无异常', L2: '市值字段完整', L3: '无复权因子跳变/涨跌幅异常', L4: '无缺口且数据鲜活',
    }
    return { type: 'success', text: '达标', tip: okTip[k] }
  }
  if (k === 'L1') return { type: 'danger', text: `${lay.issues} 问题`, tip: `入库问题 ${lay.issues} 项（行情·收盘价为空/开高低修补）→ 点击查看并修复` }
  if (k === 'L2') return { type: 'danger', text: '缺', tip: '市值字段缺失（总市值/流通市值未补全）→ 点击前往质量页恢复' }
  if (k === 'L3') return { type: 'danger', text: `${lay.issues} 问题`, tip: `正确性问题 ${lay.issues} 项（复权·因子跳变/涨跌幅异常）→ 点击查看并修复` }
  // L4
  const parts: string[] = []
  if (lay.gap_days) parts.push(`缺口 ${lay.gap_days} 天${lay.gap_lo ? `（${lay.gap_lo}~${lay.gap_hi}）` : ''}`)
  if (lay.stale_days) parts.push(`滞后 ${lay.stale_days} 天`)
  return { type: 'danger', text: '不达标', tip: (parts.join(' · ') || '覆盖/鲜活不达标') + ' → 点击带区间前往重采' }
}
function shouldShowLayer(k: string): boolean {
  if (settings.focusLayer === 'L12') return k === 'L1' || k === 'L2'
  if (settings.focusLayer === 'L34') return k === 'L3' || k === 'L4'
  return true
}
function goLayer(k: string, row: any) {
  const lay = row.layers[k]
  if (k === 'L4') {
    // 带 code + 区间跳采集页（缺口区间，或滞后起点→全局最新），采集页预填后可直接重采
    const lo = lay?.gap_lo || lay?.stale_lo
    const hi = lay?.gap_hi || sq.value?.latest_trade_date
    const query: Record<string, string> = { task_type: 'stock_ingest', recipe: 'range_refetch', code: row.code }
    if (lo) { query.start = (lo as string).slice(0, 10); query.end = ((hi as string) || lo).slice(0, 10) }
    router.push({ path: '/data/ingest', query })
  } else {
    router.push(`/data/quality?code=${row.code}`)   // L1/L2/L3 → 质量页按类型恢复
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [o, c, d] = await Promise.all([getOverview(), getCatalog(), getDimensions()])
    ov.value = o
    tables.value = c.tables
    dims.value = d.dimensions
    await loadSq()
  } catch (e) {
    error.value = getErrorMessage(e, '数据概览加载失败')
  } finally {
    loading.value = false
  }
}

async function loadSq() {
  sqLoading.value = true
  sqError.value = ''
  try {
    sq.value = await getStockQuality({
      codes: sqSelected.value.length ? sqSelected.value.join(',') : undefined,
      page: sqPage.value, size: sqSize.value,
    })
  } catch (error) {
    sqError.value = getErrorMessage(error, '逐股质量加载失败')
  } finally {
    sqLoading.value = false
  }
}
function onSqSelect() { sqPage.value = 1; loadSq() }

function gotoQuality(severity?: string, issueType?: string) {
  const q: Record<string, string> = {}
  if (severity) q.severity = severity
  if (issueType) q.issue_type = issueType
  router.push(Object.keys(q).length ? { path: '/data/quality', query: q } : '/data/quality')
}
function gotoGap() { router.push('/data/ingest') }
function gotoBoard() {
  router.push({ path: '/data/ingest', query: { task_type: 'board', mode: 'update' } })
}
function gotoBoardTab() {
  activeWorkspaceTab.value = 'board'
}
const boardCoverageItems = computed(() => {
  const board = ov.value?.board
  return [
    {
      key: 'member',
      label: '成分覆盖',
      desc: '板块字典已匹配成分股的覆盖进度',
      ready: board?.member_ready,
      target: board?.member_target,
    },
    {
      key: 'bar',
      label: '指数覆盖',
      desc: '板块指数行情可用于趋势对照的覆盖进度',
      ready: board?.bar_ready,
      target: board?.bar_target,
    },
    {
      key: 'fund',
      label: '资金流覆盖',
      desc: '资金流快照可用于板块热度跟踪的覆盖进度',
      ready: board?.fund_ready,
      target: board?.fund_target,
    },
  ].map((item) => ({ ...item, pct: coveragePct(item.ready, item.target), status: coverageStatus(item.ready, item.target) }))
})
const boardOverallCoverage = computed(() => {
  const totals = boardCoverageItems.value.reduce((acc, item) => ({
    ready: acc.ready + (item.ready ?? 0),
    target: acc.target + (item.target ?? 0),
  }), { ready: 0, target: 0 })
  return coveragePct(totals.ready, totals.target)
})
const boardIssueItems = computed(() => {
  const issues = ov.value?.board?.issues_by_type ?? {}
  const known = BOARD_ISSUE_ITEMS
    .map((item) => ({ ...item, count: issues[item.key] ?? 0 }))
    .filter((item) => item.count > 0)
  const knownCount = known.reduce((sum, item) => sum + item.count, 0)
  const otherCount = Math.max(0, (ov.value?.board?.open_issues ?? 0) - knownCount)
  return otherCount
    ? [...known, { key: '', label: '其他板块问题', hint: '前往质量台账查看', count: otherCount }]
    : known
})
const boardFreshnessItems = computed(() => {
  const board = ov.value?.board
  const latest = ov.value?.latest_trade_date || ''
  return [
    { key: 'trade', label: '最新交易日', value: ov.value?.latest_trade_date, stale: false, status: '基准' },
    {
      key: 'bar', label: '板块指数', value: board?.latest_bar_date,
      ...coverageFreshness(board?.latest_bar_date, latest, board?.bar_ready, board?.bar_target),
    },
    {
      key: 'fund', label: '资金流快照', value: board?.latest_fund_date,
      ...coverageFreshness(board?.latest_fund_date, latest, board?.fund_ready, board?.fund_target),
    },
  ]
})
function dateOnly(value?: string | null): string {
  return (value || '—').slice(0, 10)
}
function boardUpdateStatus(status?: string): { label: string; type: 'success' | 'danger' | 'warning' | 'info' } {
  if (status === 'success') return { label: '成功', type: 'success' }
  if (status === 'failed') return { label: '失败', type: 'danger' }
  if (status === 'running') return { label: '运行中', type: 'warning' }
  return { label: status || '未知', type: 'info' }
}
function coverageText(ready: number | undefined, total: number | undefined): string {
  return `${ready ?? 0}/${total ?? 0}`
}
function coveragePct(ready: number | undefined, total: number | undefined): number {
  if (!total) return 0
  return Math.round(((ready ?? 0) / total) * 100)
}
// 与分层质量模型同阈值的状态档：ready/total ≥ 99% 绿、≥ 90% 橙、其余红。
function coverageStatus(ready: number | undefined, total: number | undefined): 'success' | 'warning' | 'exception' {
  if (!total) return 'exception'
  const rate = (ready ?? 0) / total
  if (rate >= 0.99) return 'success'
  if (rate >= 0.9) return 'warning'
  return 'exception'
}
// 日期追平只代表至少一个板块有当日数据；覆盖率同时达标后才能称为整体“同步”。
function coverageFreshness(
  value: string | null | undefined,
  latest: string,
  ready: number | undefined,
  target: number | undefined,
): { stale: boolean; status: '无数据' | '滞后' | '未齐' | '同步' } {
  if (!value) return { stale: true, status: '无数据' }
  if (!latest || value < latest) return { stale: true, status: '滞后' }
  if (coverageStatus(ready, target) !== 'success') return { stale: true, status: '未齐' }
  return { stale: false, status: '同步' }
}

onMounted(load)
</script>

<template>
  <LayoutHost :layout="overviewEffective">
    <template #action>
    <div class="page-head">
      <div>
      <h2 class="app-page-title">
        数据概览
        <HelpTip title="数据概览看什么？" :width="420">
          <HelpTipItem question="页面提供什么">
            <ul>
              <li>展示核心 KPI、按数据维度归并的数据资产表、四层质量达标率和逐股分层体检。</li>
            </ul>
          </HelpTipItem>
          <HelpTipItem question="问题如何处理">
            <ul>
              <li>所有质量和缺口数字均可点击，并直达对应明细页处理。</li>
            </ul>
          </HelpTipItem>
        </HelpTip>
      </h2>
      <p class="page-subtitle">家底全景：核心 KPI、数据资产表、四层质量达标率与逐股分层体检，数字可点击直达明细。</p>
      </div>
      <div class="page-head-actions">
        <el-button :loading="loading" type="primary" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #summary>
      <div v-if="!error" class="overview-summary" data-testid="overview-summary">
        <AppStateBlock
          v-if="loading && !ov"
          state="loading"
          title="正在加载数据概览…"
        />
        <div v-else class="stat-grid" data-testid="overview-kpi-grid" v-loading="loading && !!ov">
          <el-card v-if="settings.kpi.latestTradeDate" shadow="never" class="stat">
            <div class="stat-label">最新交易日 <HelpHint text="库内 daily_bar 的最大交易日，全局鲜活度的基准日" /></div>
            <div class="stat-val">{{ (ov?.latest_trade_date ?? '').slice(0, 10) || '—' }}</div>
          </el-card>
          <el-card v-if="settings.kpi.codes" shadow="never" class="stat">
            <div class="stat-label">在市 / 退市 <HelpHint text="在市 = 未退市股票数；退市 = 已退市（保留历史以防幸存者偏差）" /></div>
            <div class="stat-val">{{ ov?.codes.active ?? '—' }}<span class="sub"> / {{ ov?.codes.delisted ?? '—' }}</span></div>
          </el-card>
          <el-card v-if="settings.kpi.barRows" shadow="never" class="stat">
            <div class="stat-label">日线总行数 <HelpHint text="daily_bar 日线行情总记录数（全市场×历史交易日）" /></div>
            <div class="stat-val">{{ ov?.bar_rows?.toLocaleString() ?? '—' }}</div>
          </el-card>
          <el-card
            v-if="settings.kpi.board"
            shadow="never"
            class="stat clickable"
            data-testid="overview-board-card"
            @click="gotoBoardTab()"
          >
            <div class="stat-label">板块数据 <HelpHint text="板块规模、覆盖与质量问题概览；点击进入下方「板块数据」专区" @click.stop /></div>
            <div class="stat-val">{{ ov?.board ? (ov.board.board_dict ?? 0) + ' 板块' : '—' }}</div>
            <div class="stat-foot" v-if="ov?.board">
              概念 {{ ov.board.concept_count }} · 行业 {{ ov.board.industry_count }} · 待处理 {{ ov.board.open_issues }}
            </div>
          </el-card>
          <el-card v-if="settings.kpi.score" shadow="never" class="stat">
            <div class="stat-label">全局质量评分 <HelpHint text="在市股票中「四层质量全部达标」的占比（0~100），综合入库/契约/正确性/鲜活" /></div>
            <div class="stat-val" :style="{ color: scoreColor }">{{ ov?.quality.score ?? '—' }}</div>
          </el-card>
          <el-card v-if="settings.kpi.quality" shadow="never" class="stat clickable" @click="gotoQuality()">
            <div class="stat-label">未解决质检 <HelpHint text="尚未解决的质检问题数（按高/中/低危分级）；点击前往数据质量页逐条恢复" @click.stop /></div>
            <div class="stat-val" :class="{ danger: (ov?.quality.by_severity?.high ?? 0) > 0, warn: (ov?.quality.open ?? 0) > 0 }">
              {{ ov?.quality.open ?? '—' }}
            </div>
            <div class="stat-foot" v-if="ov?.quality.open">
              高{{ ov.quality.by_severity?.high ?? 0 }} 中{{ ov.quality.by_severity?.mid ?? 0 }} 低{{ ov.quality.by_severity?.low ?? 0 }} · 点此处理
            </div>
          </el-card>
          <el-card v-if="settings.kpi.gaps" shadow="never" class="stat clickable" @click="gotoGap">
            <div class="stat-label">缺口 / 滞后 <HelpHint text="近 90 个交易日内存在缺口(疑似漏采)或数据滞后的股票数(已排除确认停牌)；点此前往补数。下方逐股表 L4 列可见各股缺口/滞后明细" @click.stop /></div>
            <div class="stat-val" :class="{ warn: (ov?.gaps.stocks_with_gap ?? 0) > 0 }">
              {{ ov?.gaps.stocks_with_gap ?? '—' }}<span class="sub"> 只</span>
            </div>
            <div class="stat-foot" v-if="ov?.gaps">缺口/滞后共 {{ ov.gaps.gap_days_total }} 天 · 点此补数</div>
          </el-card>
        </div>

        <div class="scan-time" v-if="ov">
          最近质检时间：<b>{{ ov.last_scan_at ? ov.last_scan_at.slice(0, 19) : '尚未质检' }}</b>
          <span class="hint">（“立即质检”或定时质检任务会刷新它）</span>
        </div>
      </div>
    </template>

    <template #quality>
      <el-card
        v-if="!error && ov?.quality.by_layer?.length"
        shadow="never"
        class="quality-summary"
        data-testid="overview-quality-summary"
      >
          <template #header><span>分层质量模型（达标率）</span></template>
          <el-row :gutter="12">
            <el-col :span="6" v-for="l in ov.quality.by_layer" :key="l.layer">
              <el-tooltip :content="l.desc" placement="top">
                <div class="layer-card">
                  <div class="layer-name">{{ l.layer }} · {{ l.name_cn }}</div>
                  <el-progress :percentage="Math.round(l.pass_rate * 100)"
                               :status="l.pass_rate >= 0.99 ? 'success' : l.pass_rate >= 0.9 ? 'warning' : 'exception'" />
                  <div class="layer-foot">{{ l.pass_stocks }}/{{ l.total }} 达标 · {{ l.issues }} 问题</div>
                </div>
              </el-tooltip>
            </el-col>
          </el-row>
      </el-card>
    </template>

    <template #workspace>
      <AppStateBlock
        v-if="error"
        state="error"
        :title="ov ? '数据概览刷新失败' : '数据概览加载失败'"
        :description="error"
        retry
        @retry="load"
      />
      <el-card
        v-else
        shadow="never"
        class="overview-workspace-card"
        data-testid="overview-workspace"
      >
        <el-tabs v-model="activeWorkspaceTab" class="overview-tabs">
          <el-tab-pane label="数据资产" name="assets">
            <div class="overview-panel">
              <div class="panel-head">
                <span class="panel-title">数据资产表</span>
                <span class="hint">展开行查看字段字典与表间关联；规划中维度暂无物理表</span>
              </div>
              <AppDataTable
                :data="assets"
                size="small"
                height="100%"
                aria-label="数据资产表"
                data-testid="overview-asset-table"
                :border="tableBorder('assetTable')"
                :loading="loading"
                row-key="key"
              >
                <AppTableColumn type="expand">
                  <template #default="{ row }">
                    <div class="expand">
                      <div class="exp-line"><b>说明：</b>{{ row.purpose }}</div>
                      <div class="exp-line" v-if="row.relations?.length"><b>关联：</b>{{ row.relations.join('；') }}</div>
                      <AppDataTable v-if="row.fields?.length" :data="row.fields" size="small" class="fld-tbl" embedded>
                        <AppTableColumn label="字段" prop="name" />
                        <AppTableColumn label="中文名" prop="name_cn" />
                        <AppTableColumn label="类型" prop="type" />
                        <AppTableColumn label="说明" prop="desc" show-overflow-tooltip />
                      </AppDataTable>
                      <el-empty v-else class="app-empty app-empty--tiny" description="规划中维度，本期暂无物理表与字段" />
                    </div>
                  </template>
                </AppTableColumn>
                <AppTableColumn label="数据维度" prop="name_cn" />
                <AppTableColumn label="物理表">
                  <template #default="{ row }"><span class="mono">{{ row.table }}</span></template>
                </AppTableColumn>
                <AppTableColumn label="采集状态">
                  <template #default="{ row }">
                    <el-tag :type="DIM_STATUS[row.status]?.type ?? 'info'" size="small" effect="plain">
                      {{ DIM_STATUS[row.status]?.label ?? row.status }}
                    </el-tag>
                  </template>
                </AppTableColumn>
                <AppTableColumn label="数据源" prop="source" show-overflow-tooltip />
                <AppTableColumn label="行数" align="right">
                  <template #default="{ row }">{{ row.rows.toLocaleString() }}</template>
                </AppTableColumn>
                <AppTableColumn label="最新数据时间">
                  <template #default="{ row }">{{ (row.latest_time || '—').slice(0, 19) }}</template>
                </AppTableColumn>
                <AppTableColumn role="status">
                  <template #header>
                    <span>质量</span>
                    <HelpTip title="表级质量怎么判定？" :width="440">
                      <HelpTipItem question="时序表如何判定">
                        <ul>
                          <li>日线行情、市值指标和指数的最新数据时间须不早于全局最新交易日才算鲜活；为空或滞后时显示「无数据 / 数据滞后」，有未解决质检问题时显示问题数。</li>
                        </ul>
                      </HelpTipItem>
                      <HelpTipItem question="基础与台账表如何判定">
                        <ul>
                          <li>股票基础信息、交易日历、采集日志和质量台账没有交易日时间维度，不判断鲜活；最新时间显示「—」属正常，只要有数据即为「正常」。</li>
                        </ul>
                      </HelpTipItem>
                      <HelpTipItem question="规划中维度如何显示">
                        <ul>
                          <li>股东数、筹码分布尚无物理表，统一显示「规划中」。</li>
                        </ul>
                      </HelpTipItem>
                    </HelpTip>
                  </template>
                  <template #default="{ row }">
                    <el-tag :type="tableQuality(row).type as any" size="small" effect="plain">{{ tableQuality(row).text }}</el-tag>
                  </template>
                </AppTableColumn>
              </AppDataTable>
            </div>
          </el-tab-pane>

          <el-tab-pane label="逐股分层体检" name="stocks" lazy>
            <div class="overview-panel">
              <div class="panel-head">
                <span class="panel-title">L1 入库 / L2 契约 / L3 正确性 / L4 覆盖鲜活</span>
                <span class="hint">点击层级徽章进入解决页 · 最新交易日 {{ (sq?.latest_trade_date || '—').slice(0, 10) }}</span>
              </div>
              <div class="sq-bar">
                <StockCodeMultiSelect
                  v-model="sqSelected"
                  test-id="overview-stock-codes"
                  aria-label="逐股体检股票范围"
                  @change="onSqSelect"
                />
              </div>
              <AppStateBlock
                v-if="sqLoading && !sq"
                state="loading"
                title="正在加载逐股质量…"
              />
              <AppStateBlock
                v-else-if="sqError"
                state="error"
                :title="sq ? '逐股质量刷新失败' : '逐股质量加载失败'"
                :description="sqError"
                retry
                @retry="loadSq"
              />
              <template v-else>
                <AppDataTable
                  :data="sq?.list ?? []"
                  size="small"
                  height="100%"
                  aria-label="逐股分层体检表"
                  data-testid="overview-stock-table"
                  :border="tableBorder('stockTable')"
                  :loading="sqLoading"
                  row-key="code"
                >
                  <AppTableColumn label="代码" prop="code" />
                  <AppTableColumn label="名称" prop="name" />
                  <AppTableColumn label="最新数据">
                    <template #default="{ row }">{{ (row.latest_date || '—').slice(0, 10) }}</template>
                  </AppTableColumn>
                  <AppTableColumn v-for="k in ['L1', 'L2', 'L3', 'L4'].filter(shouldShowLayer)" :key="k" :label="LAYER_CN[k]" role="status" align="center">
                    <template #header>
                      <span>{{ LAYER_CN[k] }} <HelpHint :text="LAYER_DESC[k]" /></span>
                    </template>
                    <template #default="{ row }">
                      <el-tooltip :content="layerCell(k, row.layers[k]).tip" placement="top">
                        <el-tag :type="layerCell(k, row.layers[k]).type as any" size="small" effect="plain"
                                class="clk-tag" @click="goLayer(k, row)">
                          {{ layerCell(k, row.layers[k]).text }}
                        </el-tag>
                      </el-tooltip>
                    </template>
                  </AppTableColumn>
                </AppDataTable>
                <div class="pager">
                  <el-pagination layout="total, sizes, prev, pager, next" :total="sq?.total ?? 0"
                                 :current-page="sqPage" :page-size="sqSize" :page-sizes="PAGE_SIZE_OPTIONS" background
                                 @current-change="(p: number) => { sqPage = p; loadSq() }"
                                 @size-change="changeSqSize" />
                </div>
              </template>
            </div>
          </el-tab-pane>

          <el-tab-pane label="板块数据" name="board" lazy class="board-pane">
            <div class="overview-panel" v-if="ov?.board">
              <div class="board-hero">
                <div class="board-hero-main">
                  <span class="board-eyebrow">同花顺板块源</span>
                  <div class="board-title-line">
                    <span class="board-total">{{ ov.board.board_dict }}</span>
                    <span class="board-title-text">个概念 / 行业板块</span>
                  </div>
                  <div class="board-type-row" aria-label="板块类型分布">
                    <span>概念 <b>{{ ov.board.concept_count }}</b></span>
                    <span>行业 <b>{{ ov.board.industry_count }}</b></span>
                    <span>综合覆盖 <b>{{ boardOverallCoverage }}%</b></span>
                  </div>
                </div>
                <div class="board-hero-status" :class="{ 'is-warning': ov.board.open_issues > 0 }">
                  <span class="board-status-label">{{ ov.board.open_issues > 0 ? '待处理问题' : '质量状态' }}</span>
                  <strong>{{ ov.board.open_issues > 0 ? ov.board.open_issues : '正常' }}</strong>
                  <span>{{ ov.board.open_issues > 0 ? '项需要恢复' : '暂无板块问题' }}</span>
                </div>
              </div>

              <div class="board-layout">
                <div class="board-main">
                  <div class="board-section-head">
                    <div>
                      <span class="panel-title">覆盖进度</span>
                      <span class="hint">先确认成分、指数、资金流三条链路是否齐备</span>
                    </div>
                    <div class="board-section-actions">
                      <el-tag
                        size="small"
                        effect="plain"
                        class="board-coverage-tag"
                        :type="boardOverallCoverage >= 100 ? 'success' : 'warning'"
                      >
                        {{ boardOverallCoverage >= 100 ? '已完成' : '待补采' }}
                      </el-tag>
                      <el-button data-testid="overview-board-ingest" size="small" type="primary" @click="gotoBoard()">
                        去采集板块
                      </el-button>
                    </div>
                  </div>
                  <div class="board-coverage-grid">
                    <div v-for="item in boardCoverageItems" :key="item.key" class="cov-card">
                      <div class="cov-card-top">
                        <div>
                          <div class="cov-label">{{ item.label }}</div>
                          <div class="cov-desc">{{ item.desc }}</div>
                        </div>
                        <div class="cov-pct" :class="[item.status === 'success' ? 'done' : item.status]">{{ item.pct }}%</div>
                      </div>
                      <el-progress
                        :percentage="item.pct"
                        :status="item.status"
                        :stroke-width="9"
                        :show-text="false"
                      />
                      <div class="cov-foot">
                        <span>{{ coverageText(item.ready, item.target) }}</span>
                        <span>{{ item.pct >= 100 ? '覆盖完成' : '仍需补齐' }}</span>
                      </div>
                    </div>
                  </div>

                  <div class="board-freshness-strip">
                    <div v-for="item in boardFreshnessItems" :key="item.key" class="fresh-cell" :class="{ stale: item.stale }">
                      <span class="fresh-label">{{ item.label }}</span>
                      <strong>{{ dateOnly(item.value) }}</strong>
                      <span>{{ item.status }}</span>
                    </div>
                  </div>
                </div>

                <div class="board-side">
                  <div class="board-side-block issue-panel">
                    <div class="board-side-title">
                      <span>质量问题</span>
                      <span class="hint">点击进入对应问题列表</span>
                    </div>
                    <div v-if="boardIssueItems.length" class="board-issue-list">
                      <div
                        v-for="item in boardIssueItems"
                        :key="item.key"
                        role="button"
                        tabindex="0"
                        class="issue-card"
                        @click="gotoQuality(undefined, item.key)"
                        @keyup.enter="gotoQuality(undefined, item.key)"
                      >
                        <span class="issue-copy">
                          <span class="issue-tag">{{ item.label }}</span>
                          <span class="issue-hint">{{ item.hint }}</span>
                        </span>
                        <strong>{{ item.count }}</strong>
                      </div>
                    </div>
                    <div v-else class="issue-ok-card">
                      <span class="issue-ok-dot"></span>
                      <span>无待处理板块问题</span>
                    </div>
                  </div>

                  <div class="board-side-block" v-if="ov.board.last_update">
                    <div class="board-side-title">
                      <span>最近采集</span>
                      <el-tag size="small" effect="plain" :type="boardUpdateStatus(ov.board.last_update.status).type">
                        {{ boardUpdateStatus(ov.board.last_update.status).label }}
                      </el-tag>
                    </div>
                    <div class="board-update-card">
                      <span class="mono">{{ ov.board.last_update.table_name }}</span>
                      <strong>{{ (ov.board.last_update.updated_at || '').slice(0, 19) }}</strong>
                      <span v-if="ov.board.last_update.detail" class="hint">{{ ov.board.last_update.detail }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <AppStateBlock
              v-else
              state="empty"
              title="暂无板块数据"
              description="请先在数据采集页运行板块采集"
            >
              <template #extra>
                <el-button data-testid="overview-board-ingest" size="small" type="primary" @click="gotoBoard()">
                  去采集板块
                </el-button>
              </template>
            </AppStateBlock>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>

    <template #overlays>
    <PageSettingsDrawer
      v-model="settingsOpen"
      title="数据概览"
      :dirty="isDirty || layoutDirty"
      page-key="data-overview"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="逐股体检">
          <div class="setting-item">
            <div class="setting-label">默认关注层</div>
            <PageSegmented v-model="settings.focusLayer" aria-label="默认关注层" :options="[
              { label: '全部', value: 'all' },
              { label: 'L1-L2', value: 'L12' },
              { label: 'L3-L4', value: 'L34' },
            ]" />
          </div>
        </PageSettingSection>
        <PageSettingSection title="KPI 卡片">
          <PageToggleRow v-model="settings.kpi.latestTradeDate" label="最新交易日" />
          <PageToggleRow v-model="settings.kpi.codes" label="在市 / 退市" />
          <PageToggleRow v-model="settings.kpi.barRows" label="日线总行数" />
          <PageToggleRow v-model="settings.kpi.board" label="板块数据" />
          <PageToggleRow v-model="settings.kpi.score" label="全局质量评分" />
          <PageToggleRow v-model="settings.kpi.quality" label="未解决质检" />
          <PageToggleRow v-model="settings.kpi.gaps" label="缺口 / 滞后" />
        </PageSettingSection>
      </template>
    </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; }
.setting-item { display: flex; flex-direction: column; gap: var(--app-space-2); }
.setting-label { font-size: var(--app-font-size-body); color: var(--page-settings-text-subtle); }
.overview-summary { min-width: 0; }
.overview-workspace-card {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.overview-workspace-card :deep(.el-card__body) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px 14px 12px;
}
.overview-tabs {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.overview-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  margin-bottom: 8px;
}
.overview-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.overview-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
}
.overview-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.panel-head {
  flex: 0 0 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  margin-bottom: 8px;
}
.panel-title {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
}
.overview-panel > .el-table {
  flex: 1 1 auto;
  min-height: 0;
}
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--app-space-3); }
.stat { text-align: center; }
.stat :deep(.el-card__body) { padding: 14px 6px; }
.stat.clickable { cursor: pointer; transition: box-shadow .15s; }
.stat.clickable:hover { box-shadow: 0 0 0 1px var(--el-color-primary) inset; }
.stat-label { color: var(--el-text-color-secondary); font-size: var(--app-font-size-table); }
.stat-val { font-size: var(--app-font-size-data); font-weight: var(--app-font-weight-strong); color: var(--el-text-color-primary); margin-top: 6px; white-space: nowrap; }
.stat-val .sub { font-size: var(--app-font-size-body); font-weight: var(--app-font-weight-regular); color: var(--el-text-color-secondary); }
.stat-val.warn { color: var(--app-warning-text); }
.stat-val.danger { color: var(--app-danger-text); }
.stat-foot { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-top: 4px; }
.scan-time { font-size: var(--app-font-size-caption); color: var(--el-text-color-regular); margin-top: 8px; }
.scan-time .hint { color: var(--el-text-color-secondary); margin-left: 6px; }
.hint { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.mono { font-family: var(--app-font-family-mono); font-size: var(--app-font-size-caption); }
.expand { padding: 6px 14px; }
.exp-line { font-size: var(--app-font-size-table); margin-bottom: 6px; color: var(--el-text-color-regular); }
.fld-tbl { margin-top: 8px; }
.layer-card { padding: 8px 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }
.layer-name { font-size: var(--app-font-size-table); font-weight: var(--app-font-weight-section); margin-bottom: 6px; }
.layer-foot { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-top: 4px; }
.quality-summary :deep(.el-card__header) { padding: 9px 12px; }
.quality-summary :deep(.el-card__body) { padding: 10px 12px; }
.clk-tag { cursor: pointer; }
.clk-tag:hover { filter: brightness(0.95); text-decoration: underline; }
.sq-bar { display: flex; gap: var(--app-space-2); margin-bottom: 12px; }
.sq-bar .el-select { width: min(460px, 100%); }
.txt-warn { color: var(--app-warning-text); font-weight: var(--app-font-weight-section); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }

/* ── 板块数据 tab ── */
/* el-tabs 内容区 overflow:hidden 会裁超高内容，板块面板须自行承接滚动。 */
.board-pane {
  overflow-y: auto;
}
.board-pane > .overview-panel {
  height: auto;
  min-height: 100%;
}
.board-hero {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(150px, auto) auto;
  align-items: stretch;
  gap: var(--app-space-3);
  margin-bottom: var(--app-space-3);
}
.board-hero-main,
.board-hero-status,
.board-side-block,
.cov-card,
.fresh-cell {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-bg-color);
}
.board-hero-main {
  position: relative;
  min-width: 0;
  padding: var(--app-space-4);
  overflow: hidden;
}
.board-eyebrow {
  display: block;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
  line-height: var(--app-line-height-caption);
}
.board-title-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-top: var(--app-space-1);
}
.board-total {
  font-size: var(--app-font-size-kpi-lg);
  line-height: var(--app-line-height-compact);
  font-weight: var(--app-font-weight-strong);
  color: var(--el-text-color-primary);
}
.board-title-text {
  font-size: var(--app-font-size-body);
  color: var(--el-text-color-regular);
}
.board-type-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2) var(--app-space-4);
  margin-top: var(--app-space-3);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-table);
}
.board-type-row b {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-data);
}
.board-hero-status {
  min-width: 150px;
  padding: var(--app-space-3);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--app-space-1);
  border-color: var(--el-color-success-light-7);
}
.board-hero-status.is-warning {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}
.board-status-label,
.cov-desc,
.fresh-label,
.issue-hint {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.board-hero-status strong {
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-compact);
  color: var(--el-text-color-primary);
}
.board-hero-status span:last-child {
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-regular);
}
.board-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(260px, 0.65fr);
  gap: var(--app-space-3);
  align-items: stretch;
  flex: 1 1 auto;
  min-height: 0;
}
.board-main,
.board-side {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  min-height: 0;
}
.board-section-head,
.board-side-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.board-section-head {
  flex: 0 0 auto;
}
.board-section-head .hint,
.board-side-title .hint {
  margin-left: var(--app-space-2);
}
.board-section-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
}
.board-coverage-tag {
  cursor: default;
}
.board-coverage-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-3);
}
.cov-card {
  min-width: 0;
  padding: var(--app-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.cov-card-top,
.cov-foot {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-2);
}
.cov-card-top {
  align-items: flex-start;
}
.cov-label {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.cov-desc {
  margin-top: var(--app-space-1);
  line-height: var(--app-line-height-caption);
}
.cov-pct {
  flex: 0 0 auto;
  font-size: var(--app-font-size-data);
  font-weight: var(--app-font-weight-strong);
  color: var(--app-warning-text);
}
.cov-pct.done {
  color: var(--el-color-success);
}
.cov-pct.exception {
  color: var(--app-danger-text);
}
.cov-foot {
  align-items: center;
  font-size: var(--app-font-size-caption);
  color: var(--el-text-color-secondary);
}
.cov-foot span:first-child {
  color: var(--el-text-color-primary);
  font-weight: var(--app-font-weight-section);
}
.board-freshness-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-3);
}
.fresh-cell {
  min-width: 0;
  padding: var(--app-space-3);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--app-space-1) var(--app-space-2);
  align-items: baseline;
}
.fresh-cell strong {
  font-size: var(--app-font-size-table);
  color: var(--el-text-color-primary);
}
.fresh-cell span:last-child {
  justify-self: end;
  font-size: var(--app-font-size-caption);
  color: var(--el-color-success);
}
.fresh-cell.stale {
  border-color: var(--el-color-warning-light-5);
}
.fresh-cell.stale span:last-child,
.fresh-cell.stale strong {
  color: var(--app-warning-text);
}
.board-side-block {
  padding: var(--app-space-3);
}
.issue-panel {
  flex: 1 1 auto;
}
.board-side-title {
  margin-bottom: var(--app-space-2);
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.board-issue-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.issue-card {
  width: 100%;
  min-height: 54px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: 4px;
  background: var(--el-color-warning-light-9);
  color: inherit;
  cursor: pointer;
  text-align: left;
}
.issue-card:hover,
.issue-card:focus-visible {
  border-color: var(--app-warning-text);
  box-shadow: 0 0 0 2px var(--el-color-warning-light-8);
  outline: none;
}
.issue-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.issue-tag {
  font-size: var(--app-font-size-table);
  font-weight: var(--app-font-weight-section);
  color: var(--el-text-color-primary);
}
.issue-card strong {
  flex: 0 0 auto;
  font-size: var(--app-font-size-data);
  color: var(--app-warning-text);
}
.issue-ok-card {
  min-height: 54px;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-3);
  border: 1px solid var(--el-color-success-light-7);
  border-radius: 4px;
  color: var(--el-color-success);
  font-size: var(--app-font-size-table);
}
.issue-ok-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-success);
}
.board-update-card {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}
.board-update-card strong {
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-table);
}

@media (max-height: 700px) {
  .stat :deep(.el-card__body) { padding: 7px 6px; }
  .stat-label { font-size: var(--app-font-size-caption); }
  .stat-val { margin-top: 1px; font-size: var(--app-font-size-body); line-height: var(--app-line-height-compact); }
  .stat-foot { display: none; }
  .scan-time { margin-top: 4px; line-height: var(--app-line-height-compact); }
  .quality-summary :deep(.el-card__header) { padding: 5px 10px; }
  .quality-summary :deep(.el-card__body) { padding: 5px 10px; }
  .layer-card { padding: 3px 7px; }
  .layer-name { margin-bottom: 2px; font-size: var(--app-font-size-caption); }
  .layer-foot { display: none; }
  .panel-head { margin-bottom: 5px; }
  .overview-workspace-card :deep(.el-card__body) { padding: 6px 10px 8px; }
  .overview-tabs :deep(.el-tabs__header) { margin-bottom: 5px; }
}

@media (max-width: 1100px) {
  .board-hero {
    grid-template-columns: 1fr;
  }
  .board-layout {
    grid-template-columns: 1fr;
  }
  .board-coverage-grid,
  .board-freshness-strip {
    grid-template-columns: 1fr;
  }
}
</style>

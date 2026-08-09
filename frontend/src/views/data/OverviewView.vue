<script setup lang="ts">
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  getOverview, getCatalog, getDimensions, getStockQuality, LAYER_DESC,
  type Overview, type CatalogTable, type Dimension, type StockQuality,
} from '@/api/data'
import AppStateBlock from '@/components/AppStateBlock.vue'
import HelpTip from '@/components/HelpTip.vue'
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
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const settingsOpen = ref(false)
const overviewDefaults = {
  sqSize: DEFAULT_PAGE_SIZE,
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
  componentLayerValuesOf,
} = useRemoteLayoutConfig(overviewLayout)

// 抽屉「布局」段由 PageSettingsDrawer 按 config 自动渲染（本页无组件配置，仅布局段）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }
const activeWorkspaceTab = computed<'assets' | 'stocks' | 'board'>({
  get: () => componentValueOf('workspace', 'defaultActive') as 'assets' | 'stocks' | 'board' || 'assets',
  set: (value) => setComponentKnob('workspace', 'defaultActive', value),
})
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
const sqSelected = ref<string[]>([])           // 已选股票代码（下拉多选）
const sqOptions = ref<{ code: string; label: string }[]>([])
const sqOptLoading = ref(false)
const sqOptError = ref('')
const sqPage = ref(1)
const sqSize = ref(Number(settings.sqSize))
watch(() => settings.sqSize, (value) => {
  sqSize.value = Number(value)
  sqPage.value = 1
  if (sq.value) loadSq()
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
      L1: '入库无异常', L2: '市值字段完整', L3: '无复权跳变/异常涨跌', L4: '无缺口且数据鲜活',
    }
    return { type: 'success', text: '达标', tip: okTip[k] }
  }
  if (k === 'L1') return { type: 'danger', text: `${lay.issues} 问题`, tip: `入库问题 ${lay.issues} 项（收盘价非法/开高低修补）→ 点击查看并修复` }
  if (k === 'L2') return { type: 'danger', text: '缺', tip: '市值字段缺失（总市值/流通市值未补全）→ 点击前往质量页恢复' }
  if (k === 'L3') return { type: 'danger', text: `${lay.issues} 问题`, tip: `正确性问题 ${lay.issues} 项（复权跳变/异常涨跌）→ 点击查看并修复` }
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
    const query: Record<string, string> = { code: row.code }
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
// 下拉多选：输入代码或名称远程搜索候选股
async function remoteSearch(q: string) {
  if (!q) { sqOptions.value = []; sqOptError.value = ''; return }
  sqOptLoading.value = true
  sqOptError.value = ''
  try {
    const r = await getStockQuality({ keyword: q, size: 30 })
    sqOptions.value = r.list.map((x) => ({ code: x.code, label: `${x.code} ${x.name}` }))
  } catch (error) {
    sqOptions.value = []
    sqOptError.value = getErrorMessage(error, '股票候选加载失败')
  } finally {
    sqOptLoading.value = false
  }
}
function onSqSelect() { sqPage.value = 1; loadSq() }
// 支持粘贴逗号/空格/换行分隔的多个代码（如 600000.SH,000001.SZ）→ 拆分后追加到已选
function onSqPaste(e: ClipboardEvent) {
  const text = e.clipboardData?.getData('text') ?? ''
  if (!/[,，\s]/.test(text.trim())) return  // 单个值交给默认输入逻辑
  e.preventDefault()
  const codes = text.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
  if (!codes.length) return
  const merged = new Set([...sqSelected.value, ...codes])
  sqSelected.value = Array.from(merged)
  onSqSelect()
}

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
function coverageText(ready: number | undefined, total: number | undefined): string {
  return `${ready ?? 0}/${total ?? 0}`
}
function coveragePct(ready: number | undefined, total: number | undefined): number {
  if (!total) return 0
  return Math.round(((ready ?? 0) / total) * 100)
}

onMounted(load)
</script>

<template>
  <LayoutHost :layout="overviewEffective">
    <template #action>
    <div class="page-head">
      <h2>
        数据概览
        <HelpTip title="数据概览看什么？" :width="420">
          家底全景：核心 KPI（交易日 / 股票数 / 行数 / 质量评分 / 缺口）、按数据维度归并的「数据资产表」、
          四层质量达标率，以及逐股分层体检。所有质量/缺口数字均可点击，直达对应明细页处理。
        </HelpTip>
      </h2>
      <div class="page-head-actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
        <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
      </div>
    </div>
    </template>

    <template #summary>
      <div v-if="!error || ov" class="overview-summary" data-testid="overview-summary">
        <AppStateBlock
          v-if="error"
          state="error"
          size="compact"
          title="数据概览刷新失败"
          :description="error"
          retry
          @retry="load"
        />
        <div class="stat-grid" data-testid="overview-kpi-grid" v-loading="loading">
          <el-card v-if="settings.kpi.latestTradeDate" shadow="never" class="stat">
            <el-tooltip content="库内 daily_bar 的最大交易日，全局鲜活度的基准日" placement="top">
              <div class="stat-label">最新交易日 <span class="qm">?</span></div>
            </el-tooltip>
            <div class="stat-val">{{ (ov?.latest_trade_date ?? '').slice(0, 10) || '—' }}</div>
          </el-card>
          <el-card v-if="settings.kpi.codes" shadow="never" class="stat">
            <el-tooltip content="在市 = 未退市股票数；退市 = 已退市（保留历史以防幸存者偏差）" placement="top">
              <div class="stat-label">在市 / 退市 <span class="qm">?</span></div>
            </el-tooltip>
            <div class="stat-val">{{ ov?.codes.active ?? '—' }}<span class="sub"> / {{ ov?.codes.delisted ?? '—' }}</span></div>
          </el-card>
          <el-card v-if="settings.kpi.barRows" shadow="never" class="stat">
            <el-tooltip content="daily_bar 日线行情总记录数（全市场×历史交易日）" placement="top">
              <div class="stat-label">日线总行数 <span class="qm">?</span></div>
            </el-tooltip>
            <div class="stat-val">{{ ov?.bar_rows?.toLocaleString() ?? '—' }}</div>
          </el-card>
          <el-card
            v-if="settings.kpi.board"
            shadow="never"
            class="stat clickable"
            data-testid="overview-board-card"
            @click="gotoBoardTab()"
          >
            <el-tooltip content="板块规模、覆盖与质量问题概览；点击进入下方「板块数据」专区" placement="top">
              <div class="stat-label">板块数据 <span class="qm">?</span></div>
            </el-tooltip>
            <div class="stat-val">{{ ov?.board ? (ov.board.board_dict ?? 0) + ' 板块' : '—' }}</div>
            <div class="stat-foot" v-if="ov?.board">
              概念 {{ ov.board.concept_count }} · 行业 {{ ov.board.industry_count }} · 待处理 {{ ov.board.open_issues }}
            </div>
          </el-card>
          <el-card v-if="settings.kpi.score" shadow="never" class="stat">
            <el-tooltip content="在市股票中「四层质量全部达标」的占比（0~100），综合入库/契约/正确性/鲜活" placement="top">
              <div class="stat-label">全局质量评分 <span class="qm">?</span></div>
            </el-tooltip>
            <div class="stat-val" :style="{ color: scoreColor }">{{ ov?.quality.score ?? '—' }}</div>
          </el-card>
          <el-card v-if="settings.kpi.quality" shadow="never" class="stat clickable" @click="gotoQuality()">
            <el-tooltip content="尚未解决的质检问题数（按高/中/低危分级）；点击前往数据质量页逐条恢复" placement="top">
              <div class="stat-label">未解决质检 <span class="qm">?</span></div>
            </el-tooltip>
            <div class="stat-val" :class="{ danger: (ov?.quality.by_severity?.high ?? 0) > 0, warn: (ov?.quality.open ?? 0) > 0 }">
              {{ ov?.quality.open ?? '—' }}
            </div>
            <div class="stat-foot" v-if="ov?.quality.open">
              高{{ ov.quality.by_severity?.high ?? 0 }} 中{{ ov.quality.by_severity?.mid ?? 0 }} 低{{ ov.quality.by_severity?.low ?? 0 }} · 点此处理
            </div>
          </el-card>
          <el-card v-if="settings.kpi.gaps" shadow="never" class="stat clickable" @click="gotoGap">
            <el-tooltip content="近 90 个交易日内存在缺口(疑似漏采)或数据滞后的股票数(已排除确认停牌)；点此前往补数。下方逐股表 L4 列可见各股缺口/滞后明细" placement="top">
              <div class="stat-label">缺口 / 滞后 <span class="qm">?</span></div>
            </el-tooltip>
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
        v-if="ov?.quality.by_layer?.length"
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
        v-if="error && !ov"
        state="error"
        title="数据概览加载失败"
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
                      分两类：<br />
                      <b>时序表</b>（日线行情 / 市值指标 / 指数）：最新数据时间须 ≥ 全局最新交易日才算鲜活；
                      为空或滞后 → 「无数据 / 数据滞后」；有未解决质检问题 → 显示问题数。<br />
                      <b>基础 / 台账表</b>（股票基础信息 / 交易日历 / 采集日志 / 质量台账）：无交易日时间维度，
                      不判鲜活——最新时间显示「—」属正常，只要有数据即「正常」。<br />
                      <b>规划中维度</b>（股东数 / 筹码分布）：尚无物理表，显示「规划中」。
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
                <el-select v-model="sqSelected" multiple filterable remote clearable collapse-tags
                           allow-create default-first-option
                           :remote-method="remoteSearch" :loading="sqOptLoading" :reserve-keyword="false"
                           :no-data-text="sqOptError || '无匹配股票'"
                           placeholder="输入代码或名称搜索，可多选"
                           @change="onSqSelect" @paste.native="onSqPaste">
                  <el-option v-for="o in sqOptions" :key="o.code" :label="o.label" :value="o.code" />
                </el-select>
              </div>
              <AppStateBlock
                v-if="sqLoading && !sq"
                state="loading"
                title="正在加载逐股质量…"
              />
              <AppStateBlock
                v-else-if="sqError && !sq"
                state="error"
                title="逐股质量加载失败"
                :description="sqError"
                retry
                @retry="loadSq"
              />
              <template v-else>
                <AppStateBlock
                  v-if="sqError"
                  state="error"
                  size="compact"
                  title="逐股质量刷新失败"
                  :description="sqError"
                  retry
                  @retry="loadSq"
                />
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
                      <el-tooltip :content="LAYER_DESC[k]" placement="top"><span>{{ LAYER_CN[k] }} <span class="qm">?</span></span></el-tooltip>
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
                                 @size-change="(s: number) => { sqSize = s; sqPage = 1; loadSq() }" />
                </div>
              </template>
            </div>
          </el-tab-pane>

          <el-tab-pane label="板块数据" name="board" lazy>
            <div class="overview-panel" v-if="ov?.board">
              <div class="panel-head">
                <span class="panel-title">板块数据总览</span>
                <span class="hint">概念/行业板块的采集规模、覆盖进度、质量与最近采集状态；点击「去采集」进入板块增量采集</span>
              </div>

              <!-- 采集总览：规模 + 覆盖进度 -->
              <div class="board-section">
                <div class="board-stat-row">
                  <div class="board-stat">
                    <div class="bs-label">板块规模</div>
                    <div class="bs-value">{{ ov.board.board_dict }}<span class="bs-sub">个</span></div>
                    <div class="bs-foot">概念 {{ ov.board.concept_count }} · 行业 {{ ov.board.industry_count }}</div>
                  </div>
                  <div class="board-stat">
                    <div class="bs-label">成分覆盖</div>
                    <div class="bs-value">{{ coverageText(ov.board.member_ready, ov.board.member_target) }}</div>
                    <el-progress :percentage="coveragePct(ov.board.member_ready, ov.board.member_target)"
                                 :status="coveragePct(ov.board.member_ready, ov.board.member_target) >= 100 ? 'success' : ''"
                                 :stroke-width="8" />
                    <div class="bs-foot">已有完整成分快照的板块</div>
                  </div>
                  <div class="board-stat">
                    <div class="bs-label">指数覆盖</div>
                    <div class="bs-value">{{ coverageText(ov.board.bar_ready, ov.board.bar_target) }}</div>
                    <el-progress :percentage="coveragePct(ov.board.bar_ready, ov.board.bar_target)"
                                 :status="coveragePct(ov.board.bar_ready, ov.board.bar_target) >= 100 ? 'success' : ''"
                                 :stroke-width="8" />
                    <div class="bs-foot">指数到最新交易日</div>
                  </div>
                  <div class="board-stat">
                    <div class="bs-label">资金流覆盖</div>
                    <div class="bs-value">{{ coverageText(ov.board.fund_ready, ov.board.fund_target) }}</div>
                    <el-progress :percentage="coveragePct(ov.board.fund_ready, ov.board.fund_target)"
                                 :status="coveragePct(ov.board.fund_ready, ov.board.fund_target) >= 100 ? 'success' : ''"
                                 :stroke-width="8" />
                    <div class="bs-foot">有即时资金流</div>
                  </div>
                </div>
              </div>

              <!-- 鲜活度 -->
              <div class="board-section">
                <div class="board-subtitle">数据鲜活度</div>
                <div class="board-meta-row">
                  <span class="bm-item">最新交易日 <b>{{ (ov.latest_trade_date || '—').slice(0, 10) }}</b></span>
                  <span class="bm-item">板块指数最新 <b :class="{ warn: ov.board.latest_bar_date && ov.board.latest_bar_date < (ov.latest_trade_date || '') }">{{ ov.board.latest_bar_date || '—' }}</b></span>
                  <span class="bm-item">资金流快照 <b :class="{ warn: ov.board.latest_fund_date && ov.board.latest_fund_date < (ov.latest_trade_date || '') }">{{ ov.board.latest_fund_date || '—' }}</b></span>
                </div>
              </div>

              <!-- 质量问题 -->
              <div class="board-section">
                <div class="board-subtitle">质量问题</div>
                <div class="board-issue-row">
                  <span class="bi-item" v-if="ov.board.issues_by_type?.board_member_incomplete">
                    <el-tag size="small" effect="plain" type="warning">成分不完整</el-tag>
                    <b>{{ ov.board.issues_by_type.board_member_incomplete }}</b>
                    <span class="bi-hint">待重采</span>
                  </span>
                  <span class="bi-item" v-if="ov.board.issues_by_type?.board_index_gap">
                    <el-tag size="small" effect="plain" type="warning">指数缺口</el-tag>
                    <b>{{ ov.board.issues_by_type.board_index_gap }}</b>
                  </span>
                  <span class="bi-item" v-if="ov.board.issues_by_type?.board_fund_unmatched">
                    <el-tag size="small" effect="plain" type="warning">资金流未匹配</el-tag>
                    <b>{{ ov.board.issues_by_type.board_fund_unmatched }}</b>
                  </span>
                  <span class="bi-item" v-if="!ov.board.open_issues">
                    <span class="bi-ok">无待处理板块问题</span>
                  </span>
                  <el-button size="small" text type="primary" @click="gotoQuality()">去处理</el-button>
                </div>
              </div>

              <!-- 最近采集 -->
              <div class="board-section" v-if="ov.board.last_update">
                <div class="board-subtitle">最近采集</div>
                <div class="board-meta-row">
                  <span class="bm-item">表 <b>{{ ov.board.last_update.table_name }}</b></span>
                  <span class="bm-item">状态
                    <el-tag size="small" effect="plain"
                            :type="ov.board.last_update.status === 'success' ? 'success' : ov.board.last_update.status === 'failed' ? 'danger' : 'warning'">
                      {{ ov.board.last_update.status }}
                    </el-tag>
                  </span>
                  <span class="bm-item">时间 <b>{{ (ov.board.last_update.updated_at || '').slice(0, 19) }}</b></span>
                  <span class="bm-item" v-if="ov.board.last_update.detail"><span class="hint">{{ ov.board.last_update.detail }}</span></span>
                </div>
              </div>

              <!-- 操作 -->
              <div class="board-section board-actions">
                <el-button size="small" type="primary" plain @click="gotoBoard()">去采集板块</el-button>
                <el-button size="small" text @click="gotoQuality(undefined, 'board_index_gap,board_member_incomplete,board_fund_unmatched')">板块质量问题</el-button>
              </div>
            </div>
            <el-empty v-else class="app-empty" description="暂无板块数据，请先在数据采集页运行板块采集" />
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
            <div class="setting-label">每页条数</div>
            <PageSegmented v-model="settings.sqSize" aria-label="每页条数" :options="[
              { label: '20', value: 20 },
              { label: '50', value: 50 },
              { label: '100', value: 100 },
            ]" />
          </div>
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
.page-head h2 { margin: 0; font-size: var(--app-font-size-page-title-sm); }
.setting-item { display: flex; flex-direction: column; gap: var(--app-space-2); }
.setting-label { font-size: var(--app-font-size-body); color: var(--page-settings-text-subtle); }
.page-sub { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: var(--app-font-size-table); }
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
.qm { display: inline-block; width: 13px; height: 13px; line-height: var(--app-line-height-ornament); font-size: var(--app-font-size-tiny);
      text-align: center; border-radius: 50%; background: var(--el-fill-color-dark);
      color: var(--el-text-color-secondary); cursor: help; }
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
.board-section { margin-bottom: 14px; }
.board-section:last-child { margin-bottom: 0; }
.board-stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--app-space-3); }
.board-stat {
  padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  display: flex; flex-direction: column; gap: var(--app-space-1);
}
.board-stat .bs-label { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.board-stat .bs-value { font-size: var(--app-font-size-data); font-weight: var(--app-font-weight-strong); color: var(--el-text-color-primary); }
.board-stat .bs-sub { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); margin-left: var(--app-space-1); }
.board-stat .bs-foot { font-size: var(--app-font-size-caption); color: var(--el-text-color-secondary); }
.board-subtitle { font-size: var(--app-font-size-table); font-weight: var(--app-font-weight-section); margin-bottom: var(--app-space-2); color: var(--el-text-color-primary); }
.board-meta-row { display: flex; flex-wrap: wrap; gap: var(--app-space-2) var(--app-space-5); font-size: var(--app-font-size-table); color: var(--el-text-color-regular); }
.board-meta-row .bm-item b { color: var(--el-text-color-primary); }
.board-meta-row .bm-item b.warn { color: var(--app-warning-text); }
.board-issue-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--app-space-2) var(--app-space-4); font-size: var(--app-font-size-table); }
.board-issue-row .bi-item b { margin: 0 var(--app-space-1); color: var(--el-text-color-primary); }
.board-issue-row .bi-item .bi-hint { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.board-issue-row .bi-item .bi-ok { color: var(--el-color-success); }
.board-actions { display: flex; gap: var(--app-space-2); }

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
</style>

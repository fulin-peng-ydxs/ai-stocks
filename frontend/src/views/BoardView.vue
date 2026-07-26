<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  getIndicatorRegistry,
  type IndicatorDef,
  type ScoreProfileSummary,
  type ScoreRunRow,
} from '@/api/scoreProfile'
import { listBoardProfiles, runBoardProfile } from '@/api/board'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import HelpTip from '@/components/HelpTip.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import { usePageSettings } from '@/composables/usePageSettings'
import { downloadCsv } from '@/utils/csv'
import { ElMessage } from 'element-plus'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useStockSet } from '@/stores/stockSet'

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
  componentLayerValuesOf,
} = useRemoteLayoutConfig(boardLayout)

// 抽屉「布局」「组件设置」两段由 PageSettingsDrawer 按元数据自动渲染（见 pageRegistry.componentMeta）。
const drawerConfig = { knobs: layoutKnobs, valueOf, sourceOf, setKnob, componentValueOf, setComponentKnob, componentSourceOf, layerValuesOf, componentLayerValuesOf }

const router = useRouter()
const stockSet = useStockSet()
const loading = ref(true)
const error = ref('')
const runDate = ref<string>('')
const topN = ref(50)
const rows = ref<ScoreRunRow[]>([])
const syncingRunDate = ref(false)
const settingsOpen = ref(false)

// topN、分项达标分模式属榜单业务态偏好，保留在 usePageSettings；
// 列显隐与默认排序迁入组件配置层（slots.table.config.*），消除与 usePageSettings 的双入口（plan.md §13.3）。
const boardDefaults = {
  topN: 50,
  subScoreMode: 'full' as 'full' | 'brief' | 'hidden',
}
const { settings, isDirty, reset } = usePageSettings('board', boardDefaults)
topN.value = Number(settings.topN)

// 抽屉写值由 ComponentAutoSettings 自动渲染；页面只保留渲染/排序要读的 getter（写值经组件配置层）。
type BoardSort = 'score' | 'rank' | 'code'
const BOARD_SORT_PROPS: Record<string, BoardSort> = { total_score: 'score', rank: 'rank', code: 'code' }
const sortBy = computed<BoardSort>(() => {
  const raw = componentValueOf('table', 'defaultSort')
  return raw === 'rank' || raw === 'code' ? raw : 'score'
})
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
  setComponentKnob('table', 'defaultSort', BOARD_SORT_PROPS[prop] ?? 'score')
}

// 评分规则方案
const profiles = ref<ScoreProfileSummary[]>([])
const profileRef = ref('')
function profileKey(p: ScoreProfileSummary): string {
  return p.profile_ref || p.id
}
const curProfile = computed(() => profiles.value.find((p) => profileKey(p) === profileRef.value))
const cacheStatus = ref('')

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
const displaySubKeys = computed(() => {
  if (settings.subScoreMode === 'hidden') return []
  if (settings.subScoreMode === 'brief') return subKeys.value.slice(0, 3)
  return subKeys.value
})
const tableEmptyText = computed(() =>
  profiles.value.length ? '当前条件暂无榜单数据' : '暂无可用评分方案',
)

watch(runDate, () => {
  if (!profileRef.value || syncingRunDate.value) return
  load()
})
watch(() => settings.topN, (value) => {
  topN.value = Number(value)
  if (profileRef.value) load()
})

function scoreLevel(v: number | undefined): string {
  const n = v ?? 0
  return n >= 80 ? 'hi' : n >= 50 ? 'mid' : 'lo'
}
function gradeType(g: string): string {
  return g === '主升浪核心' ? 'danger' : g === '龙头候选' ? 'warning' : g === '观察' ? 'success' : 'info'
}

async function load() {
  if (!profileRef.value) return
  loading.value = true
  error.value = ''
  try {
    const selected = curProfile.value
    const res = await runBoardProfile({
      ...(selected?.profile_ref ? { profile_ref: selected.profile_ref } : { profile_id: selected?.id || profileRef.value }),
      run_date: runDate.value || undefined,
      top: topN.value,
    })
    rows.value = res.list
    cacheStatus.value = res.cache_status || ''
    syncingRunDate.value = true
    runDate.value = res.run_date
    syncingRunDate.value = false
    if (!res.list.length) ElMessage.info('无结果（可能该日无数据）')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
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
  const headers = ['排名', '代码', '名称', '综合分', '评级', ...subKeys.value.map((k) => nameOf(k))]
  const data = rows.value.map((r) => [
    r.rank, r.code, r.name ?? '', r.total_score, r.grade ?? '',
    ...subKeys.value.map((k) => Math.round(r.sub_scores[k] ?? 0)),
  ])
  downloadCsv(`每日榜单_${curProfile.value?.name ?? ''}_${runDate.value || 'latest'}.csv`, headers, data)
}

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    registry.value = (await getIndicatorRegistry(true)).items
    profiles.value = await listBoardProfiles()
    if (profiles.value.length) {
      profileRef.value = profileKey(profiles.value[0])
      await load()
    } else {
      loading.value = false
    }
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
        <h2 class="title-row">
          每日榜单
          <HelpTip title="榜单是怎么排出来的？" :width="420">
            <p><b>不是筛选，是打分排序</b>：选一个<b>评分规则方案</b>，对全市场（仅排除 ST）每只股票按规则打分，按综合分降序取 Top N。</p>
            <p style="margin:6px 0 2px">榜单使用你可见的评分规则方案：自己的方案、租户公开方案、全体公开方案或系统内置方案。每条规则 = 技术指标 + 权重 + 达标打分方式（布尔/分段/线性），权重自动归一到 100%。</p>
            <p style="margin:6px 0 0;color:var(--app-warning-text)"><b>⚠️ 注意</b>：全市场排序、不设硬门槛，行情差时前排也是"矮个里的高个"，<b>要看分数高低而非排名</b>。</p>
          </HelpTip>
        </h2>
        <span class="sub">
          <template v-if="runDate">交易日 {{ runDate }} · 已排除 ST</template>
          <template v-if="curProfile"> · 规则「{{ curProfile.name }}」 v{{ curProfile.version }}</template>
          <template v-if="cacheStatus"> · {{ cacheStatus === 'cached' ? '已缓存' : '已更新' }}</template>
        </span>
      </div>
      <div class="page-head-actions">
        <div class="ops">
          <span class="lbl">评分规则</span>
          <el-select v-model="profileRef" style="width: 220px" @change="load">
            <template v-if="curProfile" #label>
              <AssetProfileLabel
                :name="curProfile.name"
                :version="curProfile.version"
                :source="curProfile.source"
                :is-preset="curProfile.is_preset"
                :owner-label="curProfile.owner_label"
                :readonly="curProfile.readonly"
              />
            </template>
            <el-option v-for="p in profiles" :key="profileKey(p)" :value="profileKey(p)" :label="p.name">
              <AssetProfileLabel
                :name="p.name"
                :version="p.version"
                :source="p.source"
                :is-preset="p.is_preset"
                :owner-label="p.owner_label"
                :readonly="p.readonly"
              />
            </el-option>
          </el-select>
          <TradeDatePicker v-model="runDate" clearable />
          <span class="lbl">Top</span>
          <el-select v-model="topN" style="width: 88px" @change="load">
            <el-option :value="20" label="20" />
            <el-option :value="50" label="50" />
            <el-option :value="100" label="100" />
          </el-select>
          <el-button :loading="loading" type="primary" @click="load">刷新</el-button>
          <el-button :disabled="!rows.length" @click="exportCsv">导出 CSV</el-button>
        </div>
        <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
      </div>
    </div>

    <AppStateBlock
      v-if="error && rows.length"
      state="error"
      size="compact"
      title="榜单刷新失败"
      :description="error"
      retry
      @retry="load"
    />
    </div>
    </template>

    <template #main>
    <el-card shadow="never">
      <AppStateBlock
        v-if="loading && !rows.length"
        state="loading"
        title="正在加载榜单…"
      />
      <AppStateBlock
        v-else-if="error && !rows.length"
        state="error"
        title="榜单加载失败"
        :description="error"
        retry
        @retry="load"
      />
      <AppDataTable
        v-else
        :data="displayRows"
        :loading="loading"
        :empty-text="tableEmptyText"
        :border="tableBorder('table')"
        :default-sort="elementDefaultSort"
        clickable
        @sort-change="onTableSortChange"
        @row-click="gotoStock"
      >
        <el-table-column label="#" prop="rank" width="60" sortable :sort-by="(r:any)=>r.rank">
          <template #default="{ row }">{{ row.rank }}</template>
        </el-table-column>
        <el-table-column v-if="colVisible('code')" label="代码" prop="code" width="110" sortable />
        <el-table-column v-if="colVisible('name')" label="名称" prop="name" width="120">
          <template #default="{ row }">{{ row.name || '—' }}</template>
        </el-table-column>
        <el-table-column v-if="colVisible('score')" label="综合分" prop="total_score" width="100" sortable :sort-by="(r:any)=>r.total_score">
          <template #default="{ row }">
            <strong class="score">{{ row.total_score }}</strong>
          </template>
        </el-table-column>
        <el-table-column v-if="colVisible('grade')" label="评级" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.grade" :type="gradeType(row.grade)" effect="light">{{ row.grade }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="colVisible('subScores') && displaySubKeys.length" label="分项达标分" min-width="320">
          <template #default="{ row }">
            <div class="subchips">
              <span
                v-for="k in displaySubKeys"
                :key="k"
                class="subchip score"
                :class="scoreLevel(row.sub_scores?.[k])"
              >
                <i>{{ nameOf(k) }}</i><b>{{ Math.round(row.sub_scores?.[k] ?? 0) }}</b>
              </span>
            </div>
          </template>
        </el-table-column>
      </AppDataTable>
    </el-card>
    </template>

    <template #overlays>
    <PageSettingsDrawer
      v-model="settingsOpen"
      title="每日榜单"
      :dirty="isDirty || layoutDirty"
      page-key="board"
      :config="drawerConfig"
      @reset="reset(); resetLayout()"
    >
      <template #business>
        <PageSettingSection title="默认结果">
          <div class="setting-item">
            <div class="setting-label">Top N</div>
            <PageSegmented v-model="settings.topN" :options="[
              { label: '20', value: 20 },
              { label: '50', value: 50 },
              { label: '100', value: 100 },
            ]" />
          </div>
          <div class="setting-item">
            <div class="setting-label">分项达标分</div>
            <PageSegmented v-model="settings.subScoreMode" :options="[
              { label: '全显', value: 'full' },
              { label: '精简', value: 'brief' },
              { label: '隐藏', value: 'hidden' },
            ]" />
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
  align-items: flex-end;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}
.page-head h2 {
  margin: 0;
  font-size: var(--app-font-size-page-title-sm);
}
.title-row {
  display: flex;
  align-items: center;
}
.sub {
  color: var(--app-muted-text);
  font-size: var(--app-font-size-table);
}
.ops {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}
.ops .lbl {
  color: #606266;
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
/* 分项达标分：彩色徽章，按分值高低着色（与配置管理试算一致） */
.subchips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-control-gap);
}
.subchip.score {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  white-space: nowrap;
  padding: 2px 7px;
  border-radius: 11px;
  line-height: var(--app-line-height-comfy);
  font-size: var(--app-font-size-caption);
}
.subchip.score i {
  font-style: normal;
  color: var(--el-text-color-secondary);
}
.subchip.score b {
  font-variant-numeric: tabular-nums;
}
.subchip.score.hi {
  background: var(--score-high-bg);
}
.subchip.score.hi b {
  color: var(--score-high-text);
}
.subchip.score.mid {
  background: var(--score-mid-bg);
}
.subchip.score.mid b {
  color: var(--score-mid-text);
}
.subchip.score.lo {
  background: var(--el-fill-color);
}
.subchip.score.lo b {
  color: var(--el-text-color-secondary);
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

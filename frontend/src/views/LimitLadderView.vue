<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AppStateBlock from '@/components/AppStateBlock.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import {
  exportLimitLadder,
  filtersFromRouteQuery,
  filtersToRouteQuery,
  getLimitLadder,
  listLimitLadderTradeDates,
  normalizeLimitLadderFilters,
  type LimitLadderFilters,
  type LimitLadderResult,
  type LimitLadderStock,
} from '@/api/limitLadder'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import LimitLadder from '@/views/limit-ladder/LimitLadder.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const settingsOpen = ref(false)
const analysisVisible = ref(false)
const tradeDate = ref<string | null>(
  typeof route.query.date === 'string' ? route.query.date : null,
)
const filters = ref<LimitLadderFilters>(filtersFromRouteQuery(route.query))
const result = ref<LimitLadderResult | null>(null)
const loading = ref(false)
const error = ref('')
const exporting = ref(false)
let requestSequence = 0
let syncingRoute = false

const canViewSectors = computed(() => (
  hasPermission(auth.role, auth.permissions, 'sectors:view')
))
const workspaceMeta = computed(() => result.value?.has_snapshot
  ? `${result.value.summary.stock_count} 只 · ${filters.value.window} 日口径`
  : '等待快照')

const baseLayout = getPageLayout('limit-ladder')
const {
  effective,
  knobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  isDirty,
  resetAll,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
} = useRemoteLayoutConfig(baseLayout)
const drawerConfig = {
  knobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
}

function errorMessage(value: unknown, fallback: string): string {
  return String(
    (value as { uiMessage?: string; message?: string })?.uiMessage
      || (value as { message?: string })?.message
      || fallback,
  )
}

async function syncUrl(): Promise<void> {
  syncingRoute = true
  try {
    await router.replace({
      query: {
        ...filtersToRouteQuery(filters.value),
        ...(tradeDate.value ? { date: tradeDate.value } : {}),
      },
    })
  } finally {
    syncingRoute = false
  }
}

async function loadLadder(): Promise<void> {
  if (!tradeDate.value) return
  const sequence = ++requestSequence
  loading.value = true
  error.value = ''
  try {
    const data = await getLimitLadder(tradeDate.value, filters.value)
    if (sequence !== requestSequence) return
    result.value = data
  } catch (value) {
    if (sequence !== requestSequence) return
    error.value = errorMessage(value, '天梯加载失败，请稍后重试')
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function setFilters(next: LimitLadderFilters): Promise<void> {
  filters.value = normalizeLimitLadderFilters(next)
  await syncUrl()
  await loadLadder()
}

async function setTradeDate(next: string | null): Promise<void> {
  if (!next || next === tradeDate.value) return
  tradeDate.value = next
  filters.value = { ...filters.value, hotspotType: null, hotspotKey: null }
  result.value = null
  await syncUrl()
  await loadLadder()
}

async function exportCsv(): Promise<void> {
  if (!tradeDate.value || exporting.value) return
  exporting.value = true
  try {
    const { blob, filename } = await exportLimitLadder(tradeDate.value, filters.value)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已按当前 ${filters.value.window} 日筛选口径导出`)
  } catch (value) {
    ElMessage.error(errorMessage(value, '导出失败，请稍后重试'))
  } finally {
    exporting.value = false
  }
}

function selectStock(_stock: LimitLadderStock): void {
  ElMessage.info('走势分析将在下一阶段接入，当前筛选结果保持不变')
}

watch(
  () => route.query,
  (query) => {
    if (syncingRoute) return
    const nextDate = typeof query.date === 'string' ? query.date : tradeDate.value
    const nextFilters = filtersFromRouteQuery(query)
    const changed = nextDate !== tradeDate.value
      || JSON.stringify(nextFilters) !== JSON.stringify(filters.value)
    if (!changed) return
    tradeDate.value = nextDate
    filters.value = nextFilters
    void loadLadder()
  },
)

onMounted(async () => {
  try {
    const dates = await listLimitLadderTradeDates()
    if (!tradeDate.value) {
      tradeDate.value = dates.latest_complete_date
        || dates.latest_candidate_date
        || dates.dates[0]
        || null
    }
    if (!tradeDate.value) {
      error.value = '暂无可用交易日'
      return
    }
    await syncUrl()
    await loadLadder()
  } catch (value) {
    error.value = errorMessage(value, '交易日加载失败，请稍后重试')
  }
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <div class="page-title-line">
              <h2 class="app-page-title">连板天梯</h2>
              <el-tag size="small" type="success" effect="plain">主视图已接入</el-tag>
            </div>
            <p class="page-subtitle">按交易日观察涨停梯队，筛选、热点与导出共享同一快照口径。</p>
          </div>
          <PageSettingsTrigger :dirty="isDirty" @click="settingsOpen = true" />
        </div>
      </div>
    </template>

    <template #main>
      <MarketMasterDetailWorkspace
        v-model:analysis-visible="analysisVisible"
        eyebrow="LIMIT LADDER"
        title="涨停梯队"
        :meta="workspaceMeta"
        list-aria-label="连板天梯分层"
        data-testid="limit-ladder-workspace"
      >
        <template #list>
          <LimitLadder
            :result="result"
            :filters="filters"
            :trade-date="tradeDate"
            :loading="loading"
            :error="error"
            :exporting="exporting"
            :can-view-sectors="canViewSectors"
            @update:filters="setFilters"
            @update:trade-date="setTradeDate"
            @retry="loadLadder"
            @export="exportCsv"
            @select="selectStock"
          />
        </template>
        <template #analysis>
          <el-card
            shadow="never"
            class="analysis-placeholder"
            role="region"
            aria-label="股票走势分析"
          >
            <AppStateBlock
              state="empty"
              title="选择股票后查看走势"
              description="主结果已可研究；走势联动、详情返回和窄屏抽屉将在 T10 接入。"
            />
          </el-card>
        </template>
      </MarketMasterDetailWorkspace>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="连板天梯"
        :dirty="isDirty"
        page-key="limit-ladder"
        :config="drawerConfig"
        :business-visible="false"
        @reset="resetAll"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-title-line {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.analysis-placeholder {
  display: flex;
  min-width: 0;
  min-height: 0;
  height: 100%;
}
.analysis-placeholder :deep(.el-card__body) {
  display: flex;
  width: 100%;
  min-height: 0;
}
.analysis-placeholder .app-state-block { flex: 1 1 auto; }
@media (max-width: 720px) {
  .page-title-line { align-items: flex-start; flex-direction: column; }
}
</style>

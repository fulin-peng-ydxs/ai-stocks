<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AppStateBlock from '@/components/AppStateBlock.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'
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
import { usePageSettings } from '@/composables/usePageSettings'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import LimitLadder from '@/views/limit-ladder/LimitLadder.vue'
import {
  DEFAULT_LIMIT_LADDER_PREFERENCE,
  filtersFromLimitLadderPreference,
  normalizeLimitLadderPreference,
  type LimitLadderPreferenceV1,
} from '@/views/limit-ladder/preferences'

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

const {
  settings: preference,
  isDirty: preferenceDirty,
  reset: resetPreference,
  whenHydrated: whenPreferenceHydrated,
  remoteError: preferenceRemoteError,
  saving: preferenceSaving,
  saveError: preferenceSaveError,
  save: savePreference,
} = usePageSettings('limit-ladder', DEFAULT_LIMIT_LADDER_PREFERENCE)
const preferenceDraft = reactive<LimitLadderPreferenceV1>(
  normalizeLimitLadderPreference(DEFAULT_LIMIT_LADDER_PREFERENCE),
)

function effectivePreference(): LimitLadderPreferenceV1 {
  return preferenceRemoteError.value
    ? normalizeLimitLadderPreference(DEFAULT_LIMIT_LADDER_PREFERENCE)
    : normalizeLimitLadderPreference(preference)
}

function resetPreferenceDraft(): void {
  Object.assign(preferenceDraft, effectivePreference())
}

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

async function applySystemDefaults(): Promise<void> {
  filters.value = filtersFromLimitLadderPreference(DEFAULT_LIMIT_LADDER_PREFERENCE)
  analysisVisible.value = DEFAULT_LIMIT_LADDER_PREFERENCE.showAnalysisPanel
  await syncUrl()
  await loadLadder()
}

async function savePreferenceDefaults(): Promise<void> {
  const previous = effectivePreference()
  const normalized = normalizeLimitLadderPreference(preferenceDraft)
  Object.assign(preference, normalized)
  await savePreference()
  if (preferenceSaveError.value) {
    Object.assign(preference, previous)
    ElMessage.error('默认偏好保存失败，请检查网络后重试')
    return
  }
  Object.assign(preferenceDraft, normalized)
  settingsOpen.value = false
  ElMessage.success('已保存连板天梯默认偏好')
}

function cancelPreferenceDraft(): void {
  resetPreferenceDraft()
  settingsOpen.value = false
}

async function resetAllSettings(): Promise<void> {
  resetPreference()
  resetAll()
  resetPreferenceDraft()
  await savePreference()
  await applySystemDefaults()
  if (preferenceSaveError.value) {
    ElMessage.error('默认偏好已在本机恢复，远端保存失败，请稍后重试')
    return
  }
  ElMessage.success('已恢复并应用系统默认设置')
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
  settingsOpen,
  () => resetPreferenceDraft(),
)

watch(
  () => route.query,
  (query) => {
    if (syncingRoute) return
    const nextDate = typeof query.date === 'string' ? query.date : tradeDate.value
    const nextFilters = filtersFromRouteQuery(
      query,
      filtersFromLimitLadderPreference(effectivePreference()),
    )
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
    await whenPreferenceHydrated()
    const savedPreference = effectivePreference()
    Object.assign(preferenceDraft, savedPreference)
    filters.value = filtersFromRouteQuery(
      route.query,
      filtersFromLimitLadderPreference(savedPreference),
    )
    analysisVisible.value = savedPreference.showAnalysisPanel
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
        :dirty="isDirty || preferenceDirty"
        page-key="limit-ladder"
        :config="drawerConfig"
        :business-visible="true"
        @reset="resetAllSettings"
      >
        <template #business>
          <AppStateBlock
            v-if="preferenceRemoteError"
            state="error"
            size="inline"
            title="个人偏好读取失败"
            description="当前使用系统默认，可重新保存后再试"
          />
          <PageSettingSection title="默认筛选">
            <div class="setting-item">
              <div class="setting-label">统计窗口</div>
              <PageSegmented
                v-model="preferenceDraft.window"
                :options="[
                  { label: '10 日', value: 10 },
                  { label: '20 日', value: 20 },
                  { label: '31 日', value: 31 },
                  { label: '60 日', value: 60 },
                ]"
                aria-label="默认统计窗口"
                test-id="limit-ladder-default-window"
              />
            </div>
            <div class="setting-item">
              <div class="setting-label">纳入板块</div>
              <el-checkbox-group
                v-model="preferenceDraft.boards"
                class="board-preference-options"
                aria-label="默认纳入板块"
                data-testid="limit-ladder-default-boards"
              >
                <el-checkbox value="main">主板</el-checkbox>
                <el-checkbox value="star">科创板</el-checkbox>
                <el-checkbox value="gem">创业板</el-checkbox>
              </el-checkbox-group>
            </div>
            <PageToggleRow
              v-model="preferenceDraft.ignoreSt"
              label="默认忽略 ST"
              test-id="limit-ladder-default-ignore-st"
            />
            <PageToggleRow
              v-model="preferenceDraft.showAnalysisPanel"
              label="默认展开走势分析"
              test-id="limit-ladder-default-analysis"
            />
          </PageSettingSection>
          <div class="preference-actions">
            <el-button data-testid="limit-ladder-default-cancel" @click="cancelPreferenceDraft">
              取消
            </el-button>
            <el-button
              type="primary"
              :loading="preferenceSaving"
              data-testid="limit-ladder-default-save"
              @click="savePreferenceDefaults"
            >
              保存为默认
            </el-button>
          </div>
        </template>
      </PageSettingsDrawer>
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
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  color: var(--page-settings-text);
  font-size: var(--app-font-size-body);
}
.board-preference-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-1);
}
.preference-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--app-space-2);
  padding-top: var(--app-space-2);
}
@media (max-width: 720px) {
  .page-title-line { align-items: flex-start; flex-direction: column; }
}
</style>

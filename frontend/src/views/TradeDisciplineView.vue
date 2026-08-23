<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import HelpTip from '@/components/HelpTip.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useTradeDates } from '@/composables/useTradeDates'
import { useTradeDisciplineSummary } from '@/composables/useTradeDisciplineSummary'
import { useTableSort } from '@/composables/useTableSort'
import {
  confirmLeave,
  registerUnsavedHandler,
} from '@/composables/useUnsavedChangesGuard'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { getErrorStatus } from '@/utils/error'
import {
  listTradeDisciplineRules,
  createTradeDisciplineRule,
  getTradeDisciplineSummary,
  type CheckinSummary,
  type CheckinHistoryQuery,
  type CheckinHistoryRow,
  type TradeDisciplineRule,
} from '@/api/tradeDiscipline'
import RuleMasterList from '@/views/trade-discipline/components/RuleMasterList.vue'
import TradeRuleEditor from '@/views/trade-discipline/components/TradeRuleEditor.vue'
import TradeCheckinForm from '@/views/trade-discipline/components/TradeCheckinForm.vue'
import TradeCheckinRevisionDrawer from '@/views/trade-discipline/components/TradeCheckinRevisionDrawer.vue'
import TradeDisciplineHistory from '@/views/trade-discipline/components/TradeDisciplineHistory.vue'

type PanelKey = 'checkin' | 'rules' | 'history'

const PAGE_KEY = 'trade-discipline'
const HISTORY_SORT_FIELDS = ['trade_date'] as const
const PANEL_OPTIONS = [
  { label: '今日打卡', value: 'checkin' },
  { label: '规则管理', value: 'rules' },
  { label: '历史记录', value: 'history' },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const canViewPage = computed(
  () => auth.isSystem || auth.permissions.includes('trade-discipline:view'),
)
const canManageRules = computed(
  () => auth.isSystem || auth.permissions.includes('trade-discipline:rule-manage'),
)
const canViewCheckins = computed(
  () => auth.isSystem || auth.permissions.includes('trade-discipline:checkin-view'),
)
const canSubmitCheckins = computed(
  () => auth.isSystem || auth.permissions.includes('trade-discipline:checkin-submit'),
)

const pageLayout = getPageLayout(PAGE_KEY)
const {
  effective,
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
} = useRemoteLayoutConfig(pageLayout)
const drawerConfig = {
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
}
const { reset: resetPageSettings } = usePageSettings(PAGE_KEY, {})
const settingsOpen = ref(false)

const initialPanel = ['checkin', 'rules', 'history'].includes(String(route.query.tab))
  ? String(route.query.tab) as PanelKey
  : 'checkin'
const activePanel = ref<PanelKey>(initialPanel)

const {
  tradeDateSet,
  dataMax,
  status: tradeDateStatus,
  ensureLoaded: ensureTradeDatesLoaded,
} = useTradeDates()
const {
  changeVersion: tradeDisciplineChangeVersion,
  latestChange: latestTradeDisciplineChange,
  notifyTradeDisciplineChanged,
} = useTradeDisciplineSummary()
const rules = ref<TradeDisciplineRule[]>([])
const rulesLoading = ref(false)
const rulesError = ref(false)
const rulesReady = ref(false)
const rulesTradeDate = ref('')
const pagePermissionDenied = ref(false)
const checkinSummary = ref<CheckinSummary | null>(null)
const summaryLoading = ref(false)
const summaryError = ref(false)
const checkinTradeDate = ref('')
const selectedRuleId = ref('')
const checkinRuleIds = computed(() => new Set(checkinSummary.value?.rules.map((item) => item.rule_id) ?? []))
const displayRules = computed(() => activePanel.value === 'checkin'
  ? rules.value.filter((rule) => checkinRuleIds.value.has(rule.id))
  : rules.value)
const selectedRule = computed(
  () => displayRules.value.find((rule) => rule.id === selectedRuleId.value) ?? displayRules.value[0] ?? null,
)
const ruleEditorRef = ref<{
  isDirty: () => boolean
  requestLeave: () => Promise<boolean>
} | null>(null)
const checkinFormRef = ref<{
  isDirty: () => boolean
  requestLeave: () => Promise<boolean>
  load: () => Promise<void>
  startAmend: () => Promise<boolean>
} | null>(null)
let unregisterUnsavedHandler: (() => void) | undefined
let rulesLoadSeq = 0
let summaryLoadSeq = 0
let routeIntentReady = false

const historyPage = ref(1)
const historyQuery = ref<CheckinHistoryQuery>({})
const historyRef = ref<{ reload: () => Promise<void> } | null>(null)
const historyDetailOpen = ref(false)
const historyDetailRow = ref<CheckinHistoryRow | null>(null)
const returnToHistoryAfterAmend = ref(false)
const historyHiddenColumns = computed<string[]>(() => {
  const raw = componentValueOf('history', 'hiddenColumns')
  return Array.isArray(raw) ? raw.map(String) : []
})
const {
  sortBy: historySortBy,
  sortOrder: historySortOrder,
  elementDefaultSort: historyDefaultSort,
  onSortChange: onHistorySortChange,
} = useTableSort({
  slotId: 'history',
  defaultSort: 'trade_date:desc',
  componentValueOf,
  allowedFields: HISTORY_SORT_FIELDS,
  onChanged: () => { historyPage.value = 1 },
})
const { pageSize: historyPageSize, changePageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('history', 'pageSize'),
  fallback: 20,
  resetPage: () => { historyPage.value = 1 },
  reload: () => historyRef.value?.reload(),
})

const pageLoading = computed(
  () => tradeDateStatus.value === 'loading' || (rulesLoading.value && !rulesReady.value),
)
const pageError = computed(
  () => tradeDateStatus.value === 'error' || (rulesError.value && !rulesReady.value),
)
const latestTradeDateText = computed(() => dataMax.value || '暂无可用交易日')
const pendingRuleCount = computed(
  () => rules.value.filter((rule) => rule.has_pending_management_action).length,
)

function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

async function loadRules(tradeDate = dataMax.value): Promise<void> {
  const targetTradeDate = tradeDate ?? ''
  if (rulesTradeDate.value !== targetTradeDate) {
    rulesTradeDate.value = targetTradeDate
    rulesReady.value = false
    rules.value = []
  }
  const seq = ++rulesLoadSeq
  rulesLoading.value = true
  rulesError.value = false
  try {
    const result = await listTradeDisciplineRules(targetTradeDate)
    if (seq !== rulesLoadSeq) return
    rules.value = result
    rulesReady.value = true
    pagePermissionDenied.value = false
    if (activePanel.value !== 'checkin' && !rules.value.some((rule) => rule.id === selectedRuleId.value)) {
      selectedRuleId.value = rules.value[0]?.id ?? ''
    }
  } catch (error) {
    if (seq !== rulesLoadSeq) return
    if (getErrorStatus(error) === 403) pagePermissionDenied.value = true
    rulesError.value = true
  } finally {
    if (seq === rulesLoadSeq) rulesLoading.value = false
  }
}

async function refreshRules(): Promise<void> {
  await loadRules(activePanel.value === 'checkin' ? checkinTradeDate.value : dataMax.value)
}

async function loadCheckinSummary(): Promise<void> {
  if (!canViewCheckins.value || !checkinTradeDate.value) return
  const seq = ++summaryLoadSeq
  summaryLoading.value = true
  summaryError.value = false
  try {
    const result = await getTradeDisciplineSummary(checkinTradeDate.value)
    if (seq !== summaryLoadSeq) return
    checkinSummary.value = result
    const candidates = checkinSummary.value.rules
    if (!candidates.some((item) => item.rule_id === selectedRuleId.value)) {
      selectedRuleId.value = candidates.find((item) => !item.checkin_id)?.rule_id
        ?? candidates[0]?.rule_id ?? ''
    }
  } catch {
    if (seq !== summaryLoadSeq) return
    summaryError.value = true
  } finally {
    if (seq === summaryLoadSeq) summaryLoading.value = false
  }
}

async function loadCheckinWorkspace(): Promise<void> {
  checkinSummary.value = null
  await Promise.all([loadRules(checkinTradeDate.value), loadCheckinSummary()])
}

async function loadPage(): Promise<void> {
  if (!canViewPage.value) return
  await ensureTradeDatesLoaded()
  if (tradeDateStatus.value !== 'ready') return
  const requestedTradeDate = typeof route.query.trade_date === 'string'
    ? route.query.trade_date
    : ''
  checkinTradeDate.value ||= requestedTradeDate && tradeDateSet.value.has(requestedTradeDate)
    ? requestedTradeDate
    : dataMax.value || ''
  if (activePanel.value === 'checkin') await loadCheckinWorkspace()
  else await loadRules()
  const requestedRuleId = typeof route.query.rule_ref === 'string' ? route.query.rule_ref : ''
  if (requestedRuleId && displayRules.value.some((rule) => rule.id === requestedRuleId)) {
    selectedRuleId.value = requestedRuleId
  }
}

async function switchPanel(value: string | number | boolean): Promise<void> {
  const next = String(value) as PanelKey
  if (next === activePanel.value) return
  if (!(await confirmLeave(route.path, 'context-change'))) return
  if (activePanel.value === 'checkin' && next !== 'checkin') returnToHistoryAfterAmend.value = false
  activePanel.value = next
  await router.replace({ query: { ...route.query, tab: next } })
  if (next === 'checkin') await loadCheckinWorkspace()
  else if (next === 'rules') await loadRules()
}

async function selectRule(ruleId: string): Promise<void> {
  if (ruleId === selectedRuleId.value) return
  if (!(await confirmLeave(route.path, 'context-change'))) return
  if (activePanel.value === 'checkin') returnToHistoryAfterAmend.value = false
  selectedRuleId.value = ruleId
}

async function createRule(): Promise<void> {
  if (!canManageRules.value) return
  if (!(await confirmLeave(route.path, 'context-change'))) return
  try {
    const created = await createTradeDisciplineRule()
    await loadRules(dataMax.value)
    selectedRuleId.value = created.id
    ElMessage.success('已创建草稿（未发布）')
  } catch { /* 统一请求层已反馈 */ }
}

async function createRuleFromCheckin(): Promise<void> {
  await switchPanel('rules')
  if (activePanel.value === 'rules') await createRule()
}

async function handleRuleDeleted(): Promise<void> {
  selectedRuleId.value = ''
  await loadRules(dataMax.value)
}

async function handleRuleCopied(ruleId: string): Promise<void> {
  await loadRules(dataMax.value)
  selectedRuleId.value = ruleId
}

async function changeCheckinTradeDate(value: string): Promise<void> {
  if (value === checkinTradeDate.value) return
  if (!(await confirmLeave(route.path, 'context-change'))) return
  returnToHistoryAfterAmend.value = false
  checkinTradeDate.value = value
  selectedRuleId.value = ''
  await loadCheckinWorkspace()
}

async function handleCheckinSubmitted(): Promise<void> {
  await Promise.all([loadCheckinSummary(), loadRules(checkinTradeDate.value)])
  if (selectedRuleId.value) {
    notifyTradeDisciplineChanged({
      ruleId: selectedRuleId.value,
      tradeDate: checkinTradeDate.value,
      source: 'workbench',
    })
  }
  if (returnToHistoryAfterAmend.value) {
    returnToHistoryAfterAmend.value = false
    activePanel.value = 'history'
    await router.replace({ query: { ...route.query, tab: 'history' } })
    await nextTick()
  }
}

function changeHistoryPage(page: number): void {
  historyPage.value = page
}

function updateHistoryQuery(value: CheckinHistoryQuery): void {
  historyQuery.value = value
}

function openHistoryDetail(row: CheckinHistoryRow): void {
  historyDetailRow.value = row
  historyDetailOpen.value = true
}

async function amendFromHistory(value: { ruleId: string; tradeDate: string }): Promise<void> {
  if (!canSubmitCheckins.value) return
  historyDetailOpen.value = false
  checkinTradeDate.value = value.tradeDate
  selectedRuleId.value = value.ruleId
  returnToHistoryAfterAmend.value = true
  activePanel.value = 'checkin'
  await router.replace({ query: { ...route.query, tab: 'checkin' } })
  await loadCheckinWorkspace()
  await nextTick()
  const started = await checkinFormRef.value?.startAmend()
  if (!started) {
    returnToHistoryAfterAmend.value = false
    ElMessage.error('当前修订未能载入，无法发起修正')
    return
  }
  ElMessage.info('已载入当前修订，提交后将生成新修订并返回历史记录')
}

onMounted(() => {
  unregisterUnsavedHandler = registerUnsavedHandler(route.path, {
    isDirty: () => activePanel.value === 'checkin'
      ? checkinFormRef.value?.isDirty() ?? false
      : ruleEditorRef.value?.isDirty() ?? false,
    requestLeave: () => activePanel.value === 'checkin'
      ? checkinFormRef.value?.requestLeave() ?? true
      : ruleEditorRef.value?.requestLeave() ?? true,
  })
  void loadPage().finally(() => { routeIntentReady = true })
})
onUnmounted(() => unregisterUnsavedHandler?.())

watch(
  () => [route.query.tab, route.query.rule_ref, route.query.trade_date] as const,
  async ([tab, ruleRef, tradeDate]) => {
    if (!routeIntentReady) return
    const nextPanel = ['checkin', 'rules', 'history'].includes(String(tab))
      ? String(tab) as PanelKey
      : 'checkin'
    const nextTradeDate = typeof tradeDate === 'string' && tradeDateSet.value.has(tradeDate)
      ? tradeDate
      : checkinTradeDate.value || dataMax.value || ''
    const nextRuleId = typeof ruleRef === 'string' ? ruleRef : ''
    if (
      nextPanel === activePanel.value
      && (nextPanel !== 'checkin' || nextTradeDate === checkinTradeDate.value)
      && (!nextRuleId || nextRuleId === selectedRuleId.value)
    ) return
    if (!(await confirmLeave(route.path, 'context-change'))) {
      const restoredQuery: Record<string, string> = { tab: activePanel.value }
      if (activePanel.value === 'checkin' && checkinTradeDate.value) {
        restoredQuery.trade_date = checkinTradeDate.value
      }
      if (selectedRuleId.value) restoredQuery.rule_ref = selectedRuleId.value
      await router.replace({ query: restoredQuery })
      return
    }
    activePanel.value = nextPanel
    if (nextPanel === 'checkin') {
      checkinTradeDate.value = nextTradeDate
      selectedRuleId.value = nextRuleId
      await loadCheckinWorkspace()
    } else {
      await loadRules(dataMax.value)
      if (nextRuleId && rules.value.some((rule) => rule.id === nextRuleId)) {
        selectedRuleId.value = nextRuleId
      }
    }
  },
)

watch(tradeDisciplineChangeVersion, async () => {
  const change = latestTradeDisciplineChange.value
  if (!change || change.source === 'workbench' || change.tradeDate !== checkinTradeDate.value) return
  if (activePanel.value === 'checkin') {
    await Promise.all([loadCheckinSummary(), loadRules(checkinTradeDate.value)])
    if (selectedRuleId.value === change.ruleId) await checkinFormRef.value?.load()
  } else if (activePanel.value === 'history') {
    await historyRef.value?.reload()
  }
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title">
              交易纪律
              <HelpTip title="交易纪律工作台" :width="420">
                规则定义约束，今日打卡记录执行，历史记录保留复盘事实。规则的新版本、归档和恢复均从下一真实交易日生效。
              </HelpTip>
            </h2>
            <p class="page-subtitle">把规则、执行和复盘留在同一条可追溯的纪律轨道上。</p>
          </div>
          <div class="page-head-actions">
            <div class="trade-date-summary" role="status" aria-label="最新交易日">
              <span>最新交易日</span>
              <strong>{{ latestTradeDateText }}</strong>
              <i :class="{ ready: tradeDateStatus === 'ready' }" />
            </div>
            <PageSettingsTrigger :dirty="layoutDirty" @click="settingsOpen = true" />
          </div>
        </div>
      </div>
    </template>

    <template #main>
      <AppStateBlock
        v-if="!canViewPage || pagePermissionDenied"
        state="error"
        variant="permission"
        title="无权限查看交易纪律"
        description="当前账号未获得交易纪律基础查看权限"
      />
      <AppStateBlock
        v-else-if="pageLoading"
        state="loading"
        title="正在加载交易纪律…"
      />
      <AppStateBlock
        v-else-if="pageError"
        state="error"
        title="交易纪律加载失败"
        description="交易日或规则数据不可用，当前页面已停止写操作"
        retry
        @retry="loadPage"
      />
      <div v-else class="discipline-workspace">
        <div class="discipline-rail">
          <PageSegmented
            :model-value="activePanel"
            :options="PANEL_OPTIONS"
            tone="primary"
            size="small"
            test-id="trade-discipline-tabs"
            aria-label="交易纪律功能区"
            @update:model-value="switchPanel"
          />
          <div class="discipline-summary app-caption-text">
            <template v-if="activePanel === 'checkin'">
              <span>规则 {{ checkinSummary?.total ?? '—' }}</span>
              <span>已完成 {{ checkinSummary?.completed ?? '—' }}</span>
              <span>待打卡 {{ checkinSummary?.pending ?? '—' }}</span>
            </template>
            <template v-else>
              <span>规则 {{ displayRules.length }}</span>
              <span>待生效 {{ pendingRuleCount }}</span>
              <span>历史每页 {{ historyPageSize }} 条</span>
            </template>
          </div>
        </div>

        <section v-if="activePanel === 'checkin'" class="discipline-panel">
          <AppStateBlock
            v-if="!canViewCheckins"
            state="error"
            variant="permission"
            title="无权限查看履约打卡"
          />
          <AppStateBlock
            v-else-if="summaryError"
            state="error"
            title="履约摘要加载失败"
            description="已停止展示和提交，重试后继续"
            retry
            @retry="loadCheckinWorkspace"
          />
          <AppStateBlock v-else-if="summaryLoading" state="loading" title="正在解析当日履约状态…" />
          <AppStateBlock
            v-else-if="rulesError && !displayRules.length"
            state="error"
            title="规则列表刷新失败"
            description="当前交易日规则不可用，重试后继续"
            retry
            @retry="refreshRules"
          />
          <AppStateBlock v-else-if="!displayRules.length" state="empty" title="该交易日暂无生效规则">
            <template #extra>
              <el-button v-if="canManageRules" v-permission="'trade-discipline:rule-manage'" type="primary" @click="createRuleFromCheckin">
                创建第一套规则
              </el-button>
            </template>
          </AppStateBlock>
          <div v-else class="master-detail-shell">
            <RuleMasterList
              :rules="displayRules"
              :selected-id="selectedRuleId"
              :loading="rulesLoading"
              :error="rulesError"
              :can-manage="canManageRules"
              :checkin-states="checkinSummary?.rules"
              @select="selectRule"
              @create="createRuleFromCheckin"
              @retry="refreshRules"
            />
            <TradeCheckinForm
              v-if="selectedRule"
              ref="checkinFormRef"
              :rule-id="selectedRule.id"
              :trade-date="checkinTradeDate"
              :can-submit="canSubmitCheckins"
              @request-date-change="changeCheckinTradeDate"
              @submitted="handleCheckinSubmitted"
            />
          </div>
        </section>

        <section v-else-if="activePanel === 'rules'" class="discipline-panel">
          <div class="master-detail-shell">
            <RuleMasterList
              :rules="rules"
              :selected-id="selectedRuleId"
              :loading="rulesLoading"
              :error="rulesError"
              :can-manage="canManageRules"
              @select="selectRule"
              @create="createRule"
              @retry="refreshRules"
            />
            <TradeRuleEditor
              v-if="selectedRuleId"
              ref="ruleEditorRef"
              :rule-id="selectedRuleId"
              :trade-date="dataMax"
              :can-manage="canManageRules"
              @changed="refreshRules"
              @deleted="handleRuleDeleted"
              @copied="handleRuleCopied"
            />
            <AppStateBlock
              v-else
              state="empty"
              title="选择或新建一条规则"
              description="规则草稿会保存在服务端，发布后才生成正式版本"
            />
          </div>
        </section>

        <section v-else class="discipline-panel history-panel">
          <AppStateBlock
            v-if="!canViewCheckins"
            state="error"
            variant="permission"
            title="无权限查看履约历史"
          />
          <TradeDisciplineHistory
            v-else
            ref="historyRef"
            :query="historyQuery"
            :page="historyPage"
            :page-size="historyPageSize"
            :rules="rules"
            :border="tableBorder('history')"
            :sort-by="historySortBy"
            :sort-order="historySortOrder"
            :default-sort="historyDefaultSort"
            :hidden-columns="historyHiddenColumns"
            @update:query="updateHistoryQuery"
            @page-change="changeHistoryPage"
            @size-change="changePageSize"
            @sort-change="onHistorySortChange"
            @detail="openHistoryDetail"
          />
        </section>
      </div>
    </template>

    <template #overlays>
      <TradeCheckinRevisionDrawer
        v-model="historyDetailOpen"
        :row="historyDetailRow"
        :can-submit="canSubmitCheckins"
        @amend="amendFromHistory"
      />
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="交易纪律"
        :dirty="layoutDirty"
        :page-key="PAGE_KEY"
        :config="drawerConfig"
        @reset="resetPageSettings(); resetLayout()"
      />
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--app-space-4);
}
.page-head-actions,
.trade-date-summary,
.discipline-rail,
.discipline-summary {
  display: flex;
  align-items: center;
}
.page-head-actions { gap: var(--app-space-2); }
.trade-date-summary {
  min-height: var(--app-control-height-md);
  gap: var(--app-space-control-gap);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.trade-date-summary strong { color: var(--el-text-color-primary); font-weight: var(--app-font-weight-strong); }
.trade-date-summary i { width: 5px; height: 5px; border-radius: 50%; background: var(--el-color-warning); }
.trade-date-summary i.ready { background: var(--el-color-success); }
.discipline-workspace { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: var(--app-space-3); }
.discipline-rail { flex: none; justify-content: space-between; gap: var(--app-space-4); }
.discipline-rail :deep(.page-segmented) { min-width: 360px; }
.discipline-summary { gap: var(--app-space-3); color: var(--el-text-color-secondary); }
.discipline-panel { min-height: 0; flex: 1 1 auto; overflow: hidden; }
.master-detail-shell { height: 100%; min-height: 0; display: flex; gap: var(--app-space-4); overflow-x: auto; }
.panel-detail {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}
.panel-detail { min-width: 460px; flex: 1 1 auto; min-height: 0; overflow: auto; padding: var(--app-space-5); }
.detail-kicker { color: var(--el-color-primary); font-size: var(--app-font-size-caption); font-weight: var(--app-font-weight-section); }
.panel-detail .app-section-title { margin: var(--app-space-1) 0 var(--app-space-4); }
.rule-facts { display: grid; grid-template-columns: repeat(2, minmax(160px, 1fr)); gap: var(--app-space-3); margin: 0; }
.rule-facts > div { padding: var(--app-space-3); border-bottom: 1px solid var(--el-border-color-lighter); }
.rule-facts dt { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.rule-facts dd { margin: var(--app-space-1) 0 0; color: var(--el-text-color-primary); font-weight: var(--app-font-weight-section); }
.readonly-note { margin-top: var(--app-space-4); color: var(--el-color-warning); }
.history-panel { display: flex; }
@media (max-width: 1100px) {
  .master-detail-shell { flex-direction: column; overflow: auto; }
  .panel-detail { min-width: 0; overflow: visible; }
}
@media (max-width: 900px) {
  .page-head,
  .discipline-rail { flex-direction: column; align-items: stretch; }
  .page-head-actions { justify-content: space-between; }
  .discipline-rail :deep(.page-segmented) { min-width: 0; }
  .discipline-summary { justify-content: space-between; }
}
</style>

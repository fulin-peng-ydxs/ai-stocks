<script setup lang="ts">
import AppScrollArea from '@/components/AppScrollArea.vue'
import { provideTradeDisciplineCategories, tradeConditionMeta } from '@/composables/useTradeDisciplineCategories'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import { computed, nextTick, onActivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppDialog from '@/components/AppDialog.vue'
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
import type { StockConditionPanelDefaults } from '@/layout/configPanel'
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
  componentLayerValuesOf, componentAllowedLayers, saveRemoteUserConfig,
} = useRemoteLayoutConfig(pageLayout)
const conditionDictionary = provideTradeDisciplineCategories()
const conditionMeta = computed(() => tradeConditionMeta(conditionDictionary.categories.value))
onMounted(() => { void conditionDictionary.load() })
onActivated(() => { void conditionDictionary.load() })
const conditionDefaultsResetKey = ref(0)
const conditionPanelDefaults = computed<StockConditionPanelDefaults>(() => {
  const value = componentValueOf('stockConditions', 'defaultCollapsed')
  const configured = Array.isArray(value) ? new Set<unknown>(value) : undefined
  return {
    defaultCollapsed: configured && componentSourceOf('stockConditions', 'defaultCollapsed') !== 'default'
      ? Array.from(configured).filter((key): key is string => typeof key === 'string')
      : conditionMeta.value.stockConditions.collapseSections.map(item => item.key),
    resetKey: conditionDefaultsResetKey.value,
    sectionKeys: conditionMeta.value.stockConditions.collapseSections.map(item => item.key),
  }
})
function onComponentDefaultChange(slotId: string, field: string) {
  // 只有设置面板的显式修改重置临时开合；水合不会清除用户正在处理的分区。
  if (slotId === 'stockConditions' && field === 'defaultCollapsed') conditionDefaultsResetKey.value += 1
}
function resetSettings() {
  resetPageSettings()
  resetLayout()
  conditionDefaultsResetKey.value += 1
}
const drawerConfig = {
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  componentValueOf: (slotId: string, field: string) => slotId === 'stockConditions' && field === 'defaultCollapsed'
    ? [...conditionPanelDefaults.value.defaultCollapsed] : componentValueOf(slotId, field),
  setComponentKnob,
  componentSourceOf,
  layerValuesOf,
  componentLayerValuesOf,
  componentAllowedLayers,
  save: saveRemoteUserConfig,
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
const rulesTradeDate = ref('')
const pagePermissionDenied = ref(false)
const checkinSummary = ref<CheckinSummary | null>(null)
const summaryLoading = ref(false)
const summaryError = ref(false)
const checkinTradeDate = ref('')
const selectedRuleId = ref('')
const checkinRuleIds = computed(() => new Set(checkinSummary.value?.rules.map((item) => item.rule_id) ?? []))
const displayRules = computed(() => activePanel.value === 'checkin'
  ? rules.value.filter((rule) => checkinSummary.value
    ? checkinRuleIds.value.has(rule.id)
    : rule.effective_status === 'active' && !!rule.effective_version)
  : rules.value)
const selectedRule = computed(
  () => displayRules.value.find((rule) => rule.id === selectedRuleId.value) ?? displayRules.value[0] ?? null,
)
const isLatestCheckinDate = computed(() => checkinTradeDate.value === dataMax.value)
const checkinEmptyDescription = computed(() => isLatestCheckinDate.value
  ? '当前交易日没有可履约的正式规则；新规则发布后从下一真实交易日起生效'
  : '这是历史日期的真实空状态，不能通过新建规则补写过去的履约关系')
const ruleEditorRef = ref<{
  isDirty: () => boolean
  requestLeave: () => Promise<boolean>
  saveDraft: (showMessage?: boolean) => Promise<boolean>
  discardUnsavedChanges: () => void
} | null>(null)
const ruleLeaveDecisionVisible = ref(false)
const ruleLeaveSaving = ref(false)
let resolveRuleLeaveDecision: ((allowLeave: boolean) => void) | null = null
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
  () => tradeDateStatus.value === 'loading',
)
const pageError = computed(
  () => tradeDateStatus.value === 'error',
)
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

async function loadRules(tradeDate = dataMax.value): Promise<void> {
  const targetTradeDate = tradeDate ?? ''
  if (rulesTradeDate.value !== targetTradeDate) {
    rulesTradeDate.value = targetTradeDate
    rules.value = []
  }
  const seq = ++rulesLoadSeq
  rulesLoading.value = true
  rulesError.value = false
  try {
    const result = await listTradeDisciplineRules(targetTradeDate)
    if (seq !== rulesLoadSeq) return
    rules.value = result
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

async function openRuleManagement(): Promise<void> {
  await switchPanel('rules')
}

async function returnToLatestCheckinDate(): Promise<void> {
  if (!dataMax.value) return
  await changeCheckinTradeDate(dataMax.value)
}

async function handleRuleDeleted(): Promise<void> {
  selectedRuleId.value = ''
  await loadRules(dataMax.value)
}

async function handleRuleCopied(ruleId: string): Promise<void> {
  await loadRules(dataMax.value)
  selectedRuleId.value = ruleId
}

function requestRuleLeaveDecision(resolve: (allowLeave: boolean) => void): void {
  if (resolveRuleLeaveDecision) {
    resolve(false)
    return
  }
  resolveRuleLeaveDecision = resolve
  ruleLeaveDecisionVisible.value = true
}

function finishRuleLeaveDecision(allowLeave: boolean): void {
  ruleLeaveDecisionVisible.value = false
  resolveRuleLeaveDecision?.(allowLeave)
  resolveRuleLeaveDecision = null
}

function continueRuleEditing(): void {
  finishRuleLeaveDecision(false)
}

function discardRuleChangesAndLeave(): void {
  ruleEditorRef.value?.discardUnsavedChanges()
  finishRuleLeaveDecision(true)
}

async function saveRuleChangesAndLeave(): Promise<void> {
  if (!ruleEditorRef.value || ruleLeaveSaving.value) return
  ruleLeaveSaving.value = true
  try {
    if (await ruleEditorRef.value.saveDraft(false)) finishRuleLeaveDecision(true)
  } finally {
    ruleLeaveSaving.value = false
  }
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
onUnmounted(() => {
  unregisterUnsavedHandler?.()
  if (resolveRuleLeaveDecision) finishRuleLeaveDecision(false)
})

watch(
  () => [route.query.tab, route.query.rule_ref, route.query.trade_date] as const,
  async ([tab, ruleRef, tradeDate]) => {
    // KeepAlive 页面离开后仍会观察到其他路由的 query；只能消费属于本页面的会话参数。
    if (!routeIntentReady || route.path !== '/trade-discipline') return
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
    if (route.path !== '/trade-discipline') return
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
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :component-value-of="componentValueOf" :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title">
              {{ menuPageTitle }}
              <HelpTip
                title="交易纪律工作台"
                :width="480"
                test-id="trade-discipline-help-tip"
              >
                <HelpTipItem question="规则怎么生效">
                  <ul>
                    <li>新建时只是可编辑草稿，发布后才生成正式版本；发布新版本、归档或恢复，都从操作后的下一真实交易日起生效，避免事后改规则影响当日复盘。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="“今日”是哪一天">
                  <ul>
                    <li>今日打卡和首页今日交易纪律使用本地行情中最新已入库的交易日。当天收盘数据尚未入库时，这里仍会显示上一个交易日。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="为什么显示待生效">
                  <ul>
                    <li>正式版本已经发布，但生效日晚于当前可打卡交易日；等生效日行情入库后，规则会自动出现在今日打卡中。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="历史如何保留">
                  <ul>
                    <li>每次打卡绑定当时生效的正式版本，之后修改规则不会覆盖既有记录。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </h2>
            <p class="page-subtitle">把规则、执行和复盘留在同一条可追溯的纪律轨道上。</p>
          </div>
          <div class="page-head-actions">
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
        description="交易日数据不可用，当前页面已停止写操作"
        retry
        @retry="loadPage"
      />
      <div v-else class="discipline-workspace">
        <AppStatusNotice v-if="conditionDictionary.error.value" tone="warning" title="检查项分类加载失败">
          <el-button size="small" :loading="conditionDictionary.loading.value" @click="conditionDictionary.load">重试</el-button>
        </AppStatusNotice>
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
        </div>

        <section v-if="activePanel === 'checkin'" class="discipline-panel">
          <AppStateBlock
            v-if="!canViewCheckins"
            state="error"
            variant="permission"
            title="无权限查看履约打卡"
          />
          <AppScrollArea v-else class="master-detail-shell">
            <RuleMasterList
              :rules="displayRules"
              :selected-id="selectedRuleId"
              :loading="rulesLoading"
              :error="rulesError"
              :can-manage="canManageRules"
              :show-create="false"
              :checkin-states="checkinSummary?.rules"
              @select="selectRule"
              @retry="refreshRules"
            />
            <AppStateBlock
              v-if="summaryLoading"
              class="panel-detail"
              state="loading"
              title="正在解析当日履约状态…"
            />
            <AppStateBlock
              v-else-if="summaryError"
              class="panel-detail"
              state="error"
              title="履约摘要加载失败"
              description="已停止展示和提交，重试后继续"
              retry
              @retry="loadCheckinSummary"
            />
            <AppStateBlock
              v-else-if="rulesError && !displayRules.length"
              class="panel-detail"
              state="error"
              title="规则列表刷新失败"
              description="当前交易日规则不可用，重试后继续"
              retry
              @retry="refreshRules"
            />
            <AppStateBlock
              v-else-if="!displayRules.length"
              class="panel-detail"
              state="empty"
              title="该交易日暂无生效规则"
              :description="checkinEmptyDescription"
            >
              <template #extra>
                <el-button
                  v-if="!isLatestCheckinDate"
                  type="primary"
                  @click="returnToLatestCheckinDate"
                >
                  返回最新交易日
                </el-button>
                <el-button
                  v-else-if="canManageRules"
                  v-permission="'trade-discipline:rule-manage'"
                  type="primary"
                  plain
                  @click="openRuleManagement"
                >
                  前往规则管理
                </el-button>
              </template>
            </AppStateBlock>
            <TradeCheckinForm
              :condition-panel-defaults="conditionPanelDefaults"
              v-else-if="selectedRule"
              ref="checkinFormRef"
              :rule-id="selectedRule.id"
              :trade-date="checkinTradeDate"
              :can-submit="canSubmitCheckins"
              @request-date-change="changeCheckinTradeDate"
              @submitted="handleCheckinSubmitted"
            />
          </AppScrollArea>
        </section>

        <section v-else-if="activePanel === 'rules'" class="discipline-panel">
          <AppScrollArea class="master-detail-shell">
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
              :condition-panel-defaults="conditionPanelDefaults"
              v-if="selectedRuleId"
              ref="ruleEditorRef"
              :rule-id="selectedRuleId"
              :trade-date="dataMax"
              :can-manage="canManageRules"
              @changed="refreshRules"
              @deleted="handleRuleDeleted"
              @copied="handleRuleCopied"
              @request-leave="requestRuleLeaveDecision"
            />
            <AppStateBlock
              v-else
              state="empty"
              title="选择或新建一条规则"
              description="规则草稿会保存在服务端，发布后才生成正式版本"
            />
          </AppScrollArea>
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
      <AppDialog
        v-model="ruleLeaveDecisionVisible"
        title="未保存的规则修改"
        size="medium"
        :show-close="false"
        :close-on-click-modal="false"
        :close-on-press-escape="false"
      >
        <p class="leave-decision-copy">当前规则有未保存修改。请选择如何处理后再离开。</p>
        <template #footer>
          <el-button @click="continueRuleEditing">继续编辑</el-button>
          <el-button v-permission="'trade-discipline:rule-manage'" type="danger" plain @click="discardRuleChangesAndLeave">放弃修改</el-button>
          <el-button v-permission="'trade-discipline:rule-manage'" type="primary" :loading="ruleLeaveSaving" @click="saveRuleChangesAndLeave">保存草稿</el-button>
        </template>
      </AppDialog>
      <TradeCheckinRevisionDrawer
        :condition-panel-defaults="conditionPanelDefaults"
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
        :component-meta-overrides="conditionMeta"
        @component-default-change="onComponentDefaultChange"
        @reset="resetSettings"
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
.discipline-rail {
  display: flex;
  align-items: center;
}
.page-head-actions { gap: var(--app-space-2); }
.leave-decision-copy { margin: 0; color: var(--el-text-color-regular); line-height: var(--app-line-height-longform); }
.discipline-workspace { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: var(--app-space-3); }
.discipline-rail { flex: none; }
.discipline-rail :deep(.page-segmented) { min-width: 360px; }
.discipline-panel { min-height: 0; flex: 1 1 auto; overflow: hidden; }
.master-detail-shell {
  height: 100%;
  min-height: 0;
  --app-scroll-display: grid;
  --app-scroll-columns: 304px minmax(0, 1fr);
  --app-scroll-rows: minmax(0, 1fr);
  --app-scroll-gap: var(--app-space-3);
}
.panel-detail {
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.panel-detail { min-width: 0; min-height: 0; padding: var(--app-space-5); }
.detail-kicker { color: var(--el-color-primary); font-size: var(--app-font-size-caption); font-weight: var(--app-font-weight-section); }
.panel-detail .app-section-title { margin: var(--app-space-1) 0 var(--app-space-4); }
.rule-facts { display: grid; grid-template-columns: repeat(2, minmax(160px, 1fr)); gap: var(--app-space-3); margin: 0; }
.rule-facts > div { padding: var(--app-space-3); border-bottom: 1px solid var(--el-border-color-lighter); }
.rule-facts dt { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.rule-facts dd { margin: var(--app-space-1) 0 0; color: var(--el-text-color-primary); font-weight: var(--app-font-weight-section); }
.readonly-note { margin-top: var(--app-space-4); color: var(--el-color-warning); }
.history-panel { display: flex; }
@container app-viewport (max-width: 1100px) {
  .master-detail-shell {
    --app-scroll-columns: minmax(0, 1fr);
    --app-scroll-rows: minmax(0, min(210px, 45%)) minmax(0, 1fr);
  }
  .panel-detail { min-width: 0; }
}
@container app-viewport (max-width: 900px) {
  .page-head,
  .discipline-rail { flex-direction: column; align-items: stretch; }
  .page-head-actions { justify-content: flex-end; }
  .discipline-rail :deep(.page-segmented) { min-width: 0; }
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import HelpTip from '@/components/HelpTip.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import { useTradeDates } from '@/composables/useTradeDates'
import { confirmLeave } from '@/composables/useUnsavedChangesGuard'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import {
  listTradeDisciplineCheckins,
  listTradeDisciplineRules,
  type CheckinHistoryRow,
  type TradeDisciplineRule,
} from '@/api/tradeDiscipline'

type PanelKey = 'checkin' | 'rules' | 'history'

const PAGE_KEY = 'trade-discipline'
const PANEL_OPTIONS = [
  { label: '今日打卡', value: 'checkin' },
  { label: '规则管理', value: 'rules' },
  { label: '历史记录', value: 'history' },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const canManageRules = computed(
  () => auth.isSystem || auth.permissions.includes('trade-discipline:rule-manage'),
)
const canViewCheckins = computed(
  () => auth.isSystem || auth.permissions.includes('trade-discipline:checkin-view'),
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
  dataMax,
  status: tradeDateStatus,
  ensureLoaded: ensureTradeDatesLoaded,
} = useTradeDates()
const rules = ref<TradeDisciplineRule[]>([])
const rulesLoading = ref(false)
const rulesError = ref(false)
const selectedRuleId = ref('')
const selectedRule = computed(
  () => rules.value.find((rule) => rule.id === selectedRuleId.value) ?? rules.value[0] ?? null,
)

const historyRows = ref<CheckinHistoryRow[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyLoading = ref(false)
const historyError = ref(false)
const { pageSize: historyPageSize, changePageSize } = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('history', 'pageSize'),
  fallback: 20,
  resetPage: () => { historyPage.value = 1 },
  reload: () => loadHistory(),
})

const pageLoading = computed(
  () => tradeDateStatus.value === 'loading' || rulesLoading.value,
)
const pageError = computed(
  () => tradeDateStatus.value === 'error' || rulesError.value,
)
const latestTradeDateText = computed(() => dataMax.value || '暂无可用交易日')
const pendingRuleCount = computed(
  () => rules.value.filter((rule) => rule.has_pending_management_action).length,
)

function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

function statusLabel(rule: TradeDisciplineRule): string {
  if (rule.has_pending_management_action) return '有待生效动作'
  if (rule.effective_status === 'active') return '当前生效'
  if (rule.effective_status === 'archived') return '已归档'
  return '未发布'
}

function statusType(rule: TradeDisciplineRule): 'success' | 'warning' | 'info' {
  if (rule.has_pending_management_action) return 'warning'
  return rule.effective_status === 'active' ? 'success' : 'info'
}

function managementStatusLabel(rule: TradeDisciplineRule): string {
  const labels: Record<TradeDisciplineRule['management_status'], string> = {
    unpublished: '未发布',
    active: '已启用',
    archived: '已归档',
  }
  return labels[rule.management_status]
}

function effectiveStatusLabel(rule: TradeDisciplineRule): string {
  const labels: Record<TradeDisciplineRule['effective_status'], string> = {
    unpublished: '当日未生效',
    active: '当日生效',
    archived: '当日已归档',
  }
  return labels[rule.effective_status]
}

async function loadRules(): Promise<void> {
  rulesLoading.value = true
  rulesError.value = false
  try {
    rules.value = await listTradeDisciplineRules(dataMax.value)
    if (!rules.value.some((rule) => rule.id === selectedRuleId.value)) {
      selectedRuleId.value = rules.value[0]?.id ?? ''
    }
  } catch {
    rulesError.value = true
  } finally {
    rulesLoading.value = false
  }
}

async function loadHistory(): Promise<void> {
  if (!canViewCheckins.value) return
  historyLoading.value = true
  historyError.value = false
  try {
    const result = await listTradeDisciplineCheckins({
      page: historyPage.value,
      page_size: historyPageSize.value,
    })
    historyRows.value = result.list
    historyTotal.value = result.total
  } catch {
    historyError.value = true
  } finally {
    historyLoading.value = false
  }
}

async function loadPage(): Promise<void> {
  await ensureTradeDatesLoaded()
  if (tradeDateStatus.value !== 'ready') return
  await loadRules()
  if (activePanel.value === 'history') await loadHistory()
}

async function switchPanel(value: string | number | boolean): Promise<void> {
  const next = String(value) as PanelKey
  if (next === activePanel.value) return
  if (!(await confirmLeave(route.path, 'context-change'))) return
  activePanel.value = next
  await router.replace({ query: { ...route.query, tab: next } })
}

function selectRule(ruleId: string): void {
  selectedRuleId.value = ruleId
}

function changeHistoryPage(page: number): void {
  historyPage.value = page
  void loadHistory()
}

watch(activePanel, (panel) => {
  if (panel === 'history' && !historyRows.value.length && !historyLoading.value) {
    void loadHistory()
  }
})

onMounted(loadPage)
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
        v-if="pageLoading"
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
            <span>规则 {{ rules.length }}</span>
            <span>待生效 {{ pendingRuleCount }}</span>
            <span>历史每页 {{ historyPageSize }} 条</span>
          </div>
        </div>

        <section v-if="activePanel === 'checkin'" class="discipline-panel">
          <AppStateBlock
            v-if="!canViewCheckins"
            state="error"
            variant="permission"
            title="无权限查看履约打卡"
          />
          <AppStateBlock v-else-if="!rules.length" state="empty" title="暂无交易规则">
            <template #extra>
              <el-button v-if="canManageRules" type="primary" @click="switchPanel('rules')">
                创建第一套规则
              </el-button>
            </template>
          </AppStateBlock>
          <div v-else class="master-detail-shell">
            <aside class="rule-rail" role="listbox" aria-label="规则选择">
              <div
                v-for="rule in rules"
                :key="rule.id"
                class="rule-item"
                :class="{ active: selectedRule?.id === rule.id }"
                role="option"
                tabindex="0"
                :aria-selected="selectedRule?.id === rule.id"
                @click="selectRule(rule.id)"
                @keydown.enter="selectRule(rule.id)"
                @keydown.space.prevent="selectRule(rule.id)"
              >
                <span>{{ rule.name || rule.proposed_name || '未命名规则' }}</span>
                <el-tag :type="statusType(rule)" effect="plain" size="small">
                  {{ statusLabel(rule) }}
                </el-tag>
              </div>
            </aside>
            <div class="panel-detail">
              <div class="detail-kicker">今日履约 · {{ latestTradeDateText }}</div>
              <h3 class="app-section-title">{{ selectedRule?.name || selectedRule?.proposed_name }}</h3>
              <AppStateBlock
                state="empty"
                size="compact"
                title="履约表单尚未填写"
                description="当前规则和交易日已就绪，可在后续打卡区记录执行事实"
              />
            </div>
          </div>
        </section>

        <section v-else-if="activePanel === 'rules'" class="discipline-panel">
          <div v-if="rules.length" class="master-detail-shell">
            <aside class="rule-rail" role="listbox" aria-label="规则管理列表">
              <div
                v-for="rule in rules"
                :key="rule.id"
                class="rule-item"
                :class="{ active: selectedRule?.id === rule.id }"
                role="option"
                tabindex="0"
                :aria-selected="selectedRule?.id === rule.id"
                @click="selectRule(rule.id)"
                @keydown.enter="selectRule(rule.id)"
                @keydown.space.prevent="selectRule(rule.id)"
              >
                <span>{{ rule.name || rule.proposed_name || '未命名规则' }}</span>
                <small>{{ rule.draft_revision ? '有编辑中草稿' : statusLabel(rule) }}</small>
              </div>
            </aside>
            <div class="panel-detail">
              <div class="detail-kicker">规则状态</div>
              <h3 class="app-section-title">{{ selectedRule?.name || selectedRule?.proposed_name }}</h3>
              <dl class="rule-facts">
                <div><dt>管理状态</dt><dd>{{ selectedRule ? managementStatusLabel(selectedRule) : '—' }}</dd></div>
                <div><dt>当日有效</dt><dd>{{ selectedRule ? effectiveStatusLabel(selectedRule) : '—' }}</dd></div>
                <div><dt>正式版本</dt><dd>{{ selectedRule?.effective_version?.version_no ? `v${selectedRule.effective_version.version_no}` : '—' }}</dd></div>
                <div><dt>待生效动作</dt><dd>{{ selectedRule?.has_pending_management_action ? '是' : '否' }}</dd></div>
              </dl>
              <p v-if="!canManageRules" class="readonly-note app-caption-text">
                当前账号只有查看权限，规则维护命令不会显示。
              </p>
            </div>
          </div>
          <AppStateBlock
            v-else
            state="empty"
            title="暂无交易规则"
            description="规则创建与版本维护将在规则编辑阶段接入"
          />
        </section>

        <section v-else class="discipline-panel history-panel">
          <AppStateBlock
            v-if="!canViewCheckins"
            state="error"
            variant="permission"
            title="无权限查看履约历史"
          />
          <AppStateBlock
            v-else-if="historyError"
            state="error"
            title="履约历史加载失败"
            retry
            @retry="loadHistory"
          />
          <AppDataTable
            v-else
            :data="historyRows"
            :loading="historyLoading"
            row-key="id"
            aria-label="履约历史"
            empty-text="暂无履约记录"
            :border="tableBorder('history')"
            :pagination="{
              currentPage: historyPage,
              pageSize: historyPageSize,
              total: historyTotal,
            }"
            @page-change="changeHistoryPage"
            @size-change="changePageSize"
          >
            <AppTableColumn prop="trade_date" label="交易日" role="date" />
            <AppTableColumn prop="rule_name" label="规则" role="name" />
            <AppTableColumn prop="assessment" label="履约结果">
              <template #default="{ row }">
                <el-tag :type="row.assessment === 'complied' ? 'success' : 'danger'" effect="plain">
                  {{ row.assessment === 'complied' ? '已履约' : '未履约' }}
                </el-tag>
              </template>
            </AppTableColumn>
            <AppTableColumn prop="operation_count" label="操作数" align="right" />
            <AppTableColumn prop="current_revision_no" label="修订" align="right">
              <template #default="{ row }">r{{ row.current_revision_no }}</template>
            </AppTableColumn>
          </AppDataTable>
        </section>
      </div>
    </template>

    <template #overlays>
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
.rule-rail,
.panel-detail {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-bg-color-overlay);
}
.rule-rail { width: 288px; flex: none; min-height: 0; overflow: auto; padding: var(--app-space-2); }
.rule-item {
  width: 100%;
  min-height: 52px;
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-2);
  text-align: left;
  cursor: pointer;
}
.rule-item:hover { background: var(--el-fill-color-light); }
.rule-item:focus-visible { outline: 2px solid var(--el-color-primary-light-3); outline-offset: 1px; }
.rule-item.active { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.rule-item > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rule-item > small { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.panel-detail { min-width: 460px; flex: 1 1 auto; min-height: 0; overflow: auto; padding: var(--app-space-5); }
.detail-kicker { color: var(--el-color-primary); font-size: var(--app-font-size-caption); font-weight: var(--app-font-weight-section); }
.panel-detail .app-section-title { margin: var(--app-space-1) 0 var(--app-space-4); }
.rule-facts { display: grid; grid-template-columns: repeat(2, minmax(160px, 1fr)); gap: var(--app-space-3); margin: 0; }
.rule-facts > div { padding: var(--app-space-3); border-bottom: 1px solid var(--el-border-color-lighter); }
.rule-facts dt { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.rule-facts dd { margin: var(--app-space-1) 0 0; color: var(--el-text-color-primary); font-weight: var(--app-font-weight-section); }
.readonly-note { margin-top: var(--app-space-4); color: var(--el-color-warning); }
.history-panel { display: flex; }
@media (max-width: 900px) {
  .page-head,
  .discipline-rail { flex-direction: column; align-items: stretch; }
  .page-head-actions { justify-content: space-between; }
  .discipline-rail :deep(.page-segmented) { min-width: 0; }
  .discipline-summary { justify-content: space-between; }
  .master-detail-shell { flex-direction: column; overflow: auto; }
  .rule-rail { width: auto; max-height: 180px; }
  .panel-detail { min-width: 0; overflow: visible; }
}
</style>

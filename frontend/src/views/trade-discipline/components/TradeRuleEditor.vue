<script setup lang="ts">
import AppForm from '@/components/AppForm.vue'
import type { StockConditionPanelDefaults } from '@/layout/configPanel'
import AppFormHelp from '@/components/AppFormHelp.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'
import { computed, nextTick, onActivated, reactive, ref, watch } from 'vue'
import { CopyDocument, Delete, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIconButton from '@/components/AppIconButton.vue'
import AppReorderList from '@/components/AppReorderList.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import { decimalToMinorUnits, formatMinorUnits } from '@/utils/fixedDecimal'
import { formatMoney } from '@/utils/money'
import { conditionFilterOptions, stockConditionFields, stockConditionSummary, normalizeChecklist, stockRuleHasContent, checklistCategory, type ConditionSection, type ConditionSectionsState } from '@/utils/tradeDisciplineConditions'
import { actionSubtypeLabel, builtinActionSubtypeOptions } from '@/utils/tradeDisciplineRuleTypes'
import FixedDecimalInput from '@/views/trade-discipline/components/FixedDecimalInput.vue'
import StockRuleChecklistEditor from '@/components/trade-discipline/StockRuleChecklistEditor.vue'
import RuleSummaryCard from '@/components/trade-discipline/RuleSummaryCard.vue'
import TradeDirectionGroupGrid, {
  type TradeDirectionGroup,
} from '@/components/trade-discipline/TradeDirectionGroupGrid.vue'
import TradeDisciplineSectionPanel from '@/components/trade-discipline/TradeDisciplineSectionPanel.vue'
import {
  archiveTradeDisciplineRule,
  copyTradeDisciplineRule,
  deleteTradeDisciplineRule,
  discardTradeDisciplineRuleDraft,
  getTradeDisciplineRule,
  listTradeDisciplineRuleTypes,
  openTradeDisciplineRuleDraft,
  publishTradeDisciplineRule,
  restoreTradeDisciplineRule,
  saveTradeDisciplineRuleDraft,
  type ActionSubtypeOption,
  type ActionType,
  type DraftActionRule,
  type DraftStockRule,
  type RuleDraftPayload,
  type RuleVersionDetail,
  type TradeDisciplineRuleDetail,
} from '@/api/tradeDiscipline'

const props = defineProps<{
  conditionPanelDefaults?: StockConditionPanelDefaults
  ruleId: string
  tradeDate: string | null
  canManage: boolean
}>()

const emit = defineEmits<{
  changed: []
  deleted: []
  copied: [ruleId: string]
  requestLeave: [resolve: (allowLeave: boolean) => void]
}>()

const detail = ref<TradeDisciplineRuleDetail | null>(null)
const loading = ref(false)
const loadError = ref(false)
const command = ref('')
const editing = ref(false)
const draftRevision = ref<number | null>(null)
const form = ref<RuleDraftPayload>(emptyPayload())
const expandedRule = ref<{
  kind: 'stock' | 'action'
  item: DraftStockRule | DraftActionRule
} | null>(null)
const stockSectionStates = reactive<Record<string, ConditionSectionsState>>({})
const stockChecklistRefs = new Map<string, InstanceType<typeof StockRuleChecklistEditor>>()
function stockStateKey(item: DraftStockRule) { return `${props.ruleId}:${ruleKey(item)}` }
function setStockChecklistRef(item: DraftStockRule, component: unknown) {
  const key = stockStateKey(item)
  if (component) stockChecklistRefs.set(key, component as InstanceType<typeof StockRuleChecklistEditor>)
  else stockChecklistRefs.delete(key)
}
function revealStockCondition(item: DraftStockRule, section: ConditionSection, itemId?: string) {
  expandedRule.value = { kind: 'stock', item }
  const key = stockStateKey(item)
  stockSectionStates[key] = { ...stockSectionStates[key], [section]: true }
  void nextTick(() => stockChecklistRefs.get(key)?.reveal(section, itemId))
}
watch([() => props.ruleId, () => props.conditionPanelDefaults?.resetKey], () => {
  Object.keys(stockSectionStates).forEach(key => delete stockSectionStates[key])
})
const actionSubtypeOptions = ref<ActionSubtypeOption[]>(builtinActionSubtypeOptions.map((item) => ({ ...item })))
const typesError = ref(false)
async function refreshTypes() {
  try { actionSubtypeOptions.value = await listTradeDisciplineRuleTypes(); typesError.value = false }
  catch { typesError.value = true }
}
onActivated(() => { if (!loading.value) void refreshTypes() })
let baseline = ''
let loadRequest = 0

const dirty = computed(() => editing.value && fingerprint(form.value) !== baseline)
const enabledStockRules = computed(() => form.value.stock_rules.filter((item) => item.enabled))
const allocatedCapitalUnits = computed(() => enabledStockRules.value.reduce(
  (sum, item) => sum + (decimalToMinorUnits(item.max_capital) ?? 0n), 0n,
))
const totalCapitalUnits = computed(() => decimalToMinorUnits(form.value.capital) ?? 0n)
const remainingCapitalUnits = computed(() => totalCapitalUnits.value - allocatedCapitalUnits.value)
const allocatedCapitalText = computed(() => formatMoney(
  formatMinorUnits(allocatedCapitalUnits.value),
))
const remainingCapitalText = computed(() => formatMoney(
  formatMinorUnits(remainingCapitalUnits.value),
))
const capitalExceeded = computed(() => remainingCapitalUnits.value < 0n)
const hasSavedDraft = computed(() => Boolean(detail.value?.draft))
const isArchived = computed(() => detail.value?.management_status === 'archived')
const isUnpublished = computed(() => detail.value?.management_status === 'unpublished')
const canEditDetails = computed(() => props.canManage && editing.value && !isArchived.value)
const latestVersionLabel = computed(() => detail.value?.latest_version_no
  ? `当前正式 v${detail.value.latest_version_no}` : '尚无正式版本')

const actionGroups: TradeDirectionGroup[] = [
  { value: 'buy', label: '买入规则', hint: '建仓与加仓条件', testId: 'buy-rule-group' },
  { value: 'sell', label: '卖出规则', hint: '止盈、止损与减仓条件', testId: 'sell-rule-group' },
]

function subtypeOptions(side: ActionType): ActionSubtypeOption[] {
  return actionSubtypeOptions.value.filter((option) => option.action_type === side)
}

function subtypeLabel(item: DraftActionRule): string {
  return actionSubtypeLabel(item, actionSubtypeOptions.value)
}

function missingSubtypeLabel(item: DraftActionRule): string {
  const label = subtypeLabel(item)
  return item.action_subtype === 'do_t' ? `${label}（历史类型）` : `${label}（已从列表删除）`
}

function subtypeIsMissing(item: DraftActionRule, side: ActionType): boolean {
  return Boolean(item.action_subtype)
    && !subtypeOptions(side).some((option) => option.name === item.action_subtype)
}

function stockCapitalMeta(item: DraftStockRule): string {
  return item.max_capital ? `上限 · ${formatMoney(item.max_capital)} 元` : '未设置资金上限'
}

function cardTitle(item: DraftStockRule | DraftActionRule, fallback: string): string {
  return item.name?.trim() || fallback
}

function cardIndex(index: number): string {
  return String(index + 1).padStart(2, '0')
}

function isRuleExpanded(kind: 'stock' | 'action', item: DraftStockRule | DraftActionRule): boolean {
  return expandedRule.value?.kind === kind && expandedRule.value.item === item
}

function toggleRule(kind: 'stock' | 'action', item: DraftStockRule | DraftActionRule): void {
  expandedRule.value = isRuleExpanded(kind, item) ? null : { kind, item }
}

function groupedActionRules(side: ActionType) {
  return form.value.action_rules.filter(item => item.action_type === side)
}

function emptyPayload(): RuleDraftPayload {
  return { name: null, capital: null, max_positions: null, stock_rules: [], action_rules: [] }
}

function clonePayload(source: RuleDraftPayload | RuleVersionDetail | null): RuleDraftPayload {
  if (!source) return emptyPayload()
  return {
    name: source.name ?? null,
    capital: source.capital,
    max_positions: source.max_positions ?? null,
    stock_rules: source.stock_rules.map((item, index) => ({
      detail_id: item.detail_id ?? null,
      name: item.name ?? null,
      max_capital: item.max_capital,
      price_min: item.price_min ?? null, price_max: item.price_max ?? null,
      st_filter: item.st_filter ?? 'any', loss_filter: item.loss_filter ?? 'any',
      st_risk_filter: item.st_risk_filter ?? 'any',
      content: item.content ?? null,
      checklist_items: normalizeChecklist(item.checklist_items ?? []),
      display_order: index + 1,
      enabled: Boolean(item.enabled),
    })),
    action_rules: source.action_rules.map((item, index) => ({
      detail_id: item.detail_id ?? null,
      name: item.name ?? null,
      action_type: item.action_type ?? null,
      action_subtype: item.action_subtype ?? null,
      action_subtype_label: item.action_subtype_label ?? null,
      content: item.content ?? null,
      display_order: index + 1,
      enabled: Boolean(item.enabled),
    })),
  }
}

function fingerprint(payload: RuleDraftPayload): string {
  return JSON.stringify(payload)
}

function setEditorSource(source: RuleDraftPayload | RuleVersionDetail | null, revision: number | null) {
  form.value = clonePayload(source)
  expandedRule.value = null
  draftRevision.value = revision
  baseline = fingerprint(form.value)
  editing.value = revision !== null
}

async function load(): Promise<void> {
  if (!props.ruleId) return
  const request = ++loadRequest
  loading.value = true
  loadError.value = false
  try {
    const [result, types] = await Promise.all([
      getTradeDisciplineRule(props.ruleId, props.tradeDate),
      listTradeDisciplineRuleTypes(),
    ])
    if (request !== loadRequest) return
    detail.value = result
    typesError.value = false
    actionSubtypeOptions.value = types
    if (result.draft) setEditorSource(result.draft, result.draft.draft_revision)
    else setEditorSource(result.latest_version, null)
  } catch {
    if (request === loadRequest) loadError.value = true
  } finally {
    if (request === loadRequest) loading.value = false
  }
}

async function beginEdit(): Promise<void> {
  if (!detail.value || isArchived.value) return
  command.value = 'open'
  try {
    const draft = await openTradeDisciplineRuleDraft(detail.value.id)
    detail.value.draft = draft
    setEditorSource(draft, draft.draft_revision)
    emit('changed')
  } finally {
    command.value = ''
  }
}

function normalizedPayload(): RuleDraftPayload {
  return {
    name: form.value.name?.trim() || null,
    capital: form.value.capital === '' ? null : form.value.capital,
    max_positions: form.value.max_positions ?? null,
    stock_rules: form.value.stock_rules.map((item, index) => ({
      ...item,
      name: item.name?.trim() || null,
      content: item.content ?? null,
      checklist_items: normalizeChecklist(item.checklist_items ?? []).map(entry => ({ ...entry, text: entry.text.trim() })),
      max_capital: item.max_capital === '' ? null : item.max_capital,
      display_order: index + 1,
    })),
    action_rules: form.value.action_rules.map((item, index) => ({
      ...item,
      name: item.name?.trim() || null,
      content: item.content ?? null,
      display_order: index + 1,
    })),
  }
}

async function saveDraft(showMessage = true): Promise<boolean> {
  if (!detail.value || draftRevision.value === null || !dirty.value) return false
  if (!validateConditions()) return false
  command.value = 'save'
  try {
    const saved = await saveTradeDisciplineRuleDraft(detail.value.id, {
      ...normalizedPayload(),
      expected_revision: draftRevision.value,
    })
    detail.value.draft = saved
    setEditorSource(saved, saved.draft_revision)
    actionSubtypeOptions.value = await listTradeDisciplineRuleTypes()
      .catch(() => actionSubtypeOptions.value)
    if (showMessage) ElMessage.success('草稿已保存，当前正式版本未改变')
    emit('changed')
    return true
  } catch {
    return false
  } finally {
    command.value = ''
  }
}

function restoreBaseline(): void {
  const source = detail.value?.draft ?? detail.value?.latest_version ?? null
  setEditorSource(source, detail.value?.draft?.draft_revision ?? null)
}

function discardUnsavedChanges(): void {
  restoreBaseline()
}

function requestLeave(): Promise<boolean> {
  if (!dirty.value) return Promise.resolve(true)
  return new Promise((resolve) => emit('requestLeave', resolve))
}

async function discardSavedDraft(): Promise<void> {
  if (!detail.value?.draft) return
  try {
    await ElMessageBox.confirm(
      `放弃编辑中草稿并恢复${latestVersionLabel.value}？`,
      '放弃工作草稿',
      { type: 'warning', confirmButtonText: '放弃草稿', confirmButtonType: 'danger' },
    )
  } catch { return }
  command.value = 'discard'
  try {
    await discardTradeDisciplineRuleDraft(detail.value.id)
    await load()
    ElMessage.success('工作草稿已放弃，正式版本未改变')
    emit('changed')
  } finally {
    command.value = ''
  }
}

function validateConditions(): boolean {
  const maximum = form.value.max_positions
  if (maximum != null && (!Number.isInteger(maximum) || maximum < 1 || maximum > 2147483647)) {
    return warn('最大同时持仓数必须为正整数，留空表示不限')
  }
  for (const item of form.value.stock_rules) {
    const low = decimalToMinorUnits(item.price_min, 4)
    const high = decimalToMinorUnits(item.price_max, 4)
    if ((item.price_min != null && (low === null || low <= 0n))
      || (item.price_max != null && (high === null || high <= 0n))) {
      revealStockCondition(item, 'basic')
      return warn('股价上下限必须大于 0，最多4位小数')
    }
    if (low !== null && high !== null && low > high) {
      revealStockCondition(item, 'basic')
      return warn('股价下限不能大于上限')
    }
  }
  return true
}

function validateForPublish(): boolean {
  if (!validateConditions()) return false
  if (!form.value.name?.trim()) return warn('发布前请填写规则名称')
  if (totalCapitalUnits.value <= 0n) return warn('发布前请填写大于 0 的总本金')
  if (!enabledStockRules.value.length) return warn('发布前至少启用一条选股规则')
  for (const item of form.value.stock_rules) {
    if (!item.name?.trim() || !stockRuleHasContent(item)) {
      revealStockCondition(item, 'technical')
      return warn('选股规则需填写名称，且至少填写一项条件或补充说明')
    }
    const empty = item.checklist_items?.find(entry => !entry.text.trim())
    if (empty) {
      revealStockCondition(item, checklistCategory(empty.category), empty.item_id)
      return warn('请填写或删除空检查项')
    }
  }
  if (capitalExceeded.value) {
    const excess = formatMoney(formatMinorUnits(-remainingCapitalUnits.value))
    return warn(`启用选股规则合计超出本金 ${excess} 元`)
  }
  if (!enabledStockRules.value.every((item) => (decimalToMinorUnits(item.max_capital) ?? 0n) > 0n)) {
    return warn('启用的选股规则必须填写大于 0 的资金上限')
  }
  const actions = form.value.action_rules.filter((item) => item.enabled)
  if (!actions.some((item) => item.action_type === 'buy')) return warn('发布前至少启用一条买入规则')
  if (!actions.some((item) => item.action_type === 'sell')) return warn('发布前至少启用一条卖出规则')
  if (form.value.action_rules.some((item) => (
    !item.name?.trim() || !item.action_type || !item.action_subtype?.trim() || !item.content?.trim()
  ))) {
    return warn('买卖规则名称、类型和内容不能为空')
  }
  return true
}

function warn(message: string): false {
  ElMessage.warning(message)
  return false
}

async function publish(): Promise<void> {
  if (!detail.value || draftRevision.value === null || !dirty.value || !validateForPublish()) return
  if (!(await saveDraft(false))) return
  command.value = 'publish'
  try {
    const result = await publishTradeDisciplineRule(detail.value.id, draftRevision.value!)
    ElMessage.success(result.changed
      ? `已发布 v${result.version_no}，从 ${result.effective_from_trade_date} 生效`
      : `草稿与 v${result.version_no} 一致，未生成新版本`)
    await load()
    emit('changed')
  } finally {
    command.value = ''
  }
}

async function copyRule(): Promise<void> {
  if (!detail.value) return
  if (dirty.value && !(await requestLeave())) return
  let source: 'published' | 'draft' = detail.value.draft ? 'draft' : 'published'
  if (detail.value.draft && detail.value.latest_version) {
    try {
      await ElMessageBox.confirm(
        '该规则同时存在正式版本和编辑中草稿，请选择复制来源。',
        '复制规则',
        {
          confirmButtonType: 'primary',
          confirmButtonText: '复制草稿',
          cancelButtonText: '复制正式版本',
          distinguishCancelAndClose: true,
        },
      )
    } catch (action) {
      if (action === 'cancel') source = 'published'
      else return
    }
  }
  command.value = 'copy'
  try {
    const copied = await copyTradeDisciplineRule(detail.value.id, source)
    ElMessage.success('已复制为草稿（未发布）')
    emit('copied', copied.id)
  } finally {
    command.value = ''
  }
}

async function archiveOrRestore(): Promise<void> {
  if (!detail.value) return
  if (detail.value.draft) {
    ElMessage.warning('归档前请先发布或放弃工作草稿')
    return
  }
  const restoring = isArchived.value
  try {
    await ElMessageBox.confirm(
      restoring ? '恢复后将从下一真实交易日重新生效。' : '归档后将从下一真实交易日起停止生效。',
      restoring ? '恢复规则' : '归档规则',
      { confirmButtonType: restoring ? 'success' : 'danger', type: 'warning', confirmButtonText: restoring ? '恢复' : '归档' },
    )
  } catch { return }
  command.value = restoring ? 'restore' : 'archive'
  try {
    const result = restoring
      ? await restoreTradeDisciplineRule(detail.value.id)
      : await archiveTradeDisciplineRule(detail.value.id)
    ElMessage.success(`${restoring ? '恢复' : '归档'}动作已提交，从 ${result.effective_from_trade_date} 生效`)
    await load()
    emit('changed')
  } finally {
    command.value = ''
  }
}

async function removeUnpublished(): Promise<void> {
  if (!detail.value || !isUnpublished.value) return
  try {
    await ElMessageBox.confirm(
      `删除未发布规则「${form.value.name || '未命名规则'}」？`,
      '删除未发布规则',
      { type: 'warning', confirmButtonText: '删除', confirmButtonType: 'danger' },
    )
  } catch { return }
  command.value = 'delete'
  try {
    await deleteTradeDisciplineRule(detail.value.id)
    ElMessage.success('未发布规则已删除')
    emit('deleted')
  } finally {
    command.value = ''
  }
}

function addStockRule(): void {
  if (!canEditDetails.value) return
  const item: DraftStockRule = {
    detail_id: null, name: null, max_capital: null, content: null, checklist_items: [],
    price_min: null, price_max: null, st_filter: 'any', loss_filter: 'any', st_risk_filter: 'any',
    display_order: form.value.stock_rules.length + 1, enabled: true,
  }
  form.value.stock_rules.push(item)
  expandedRule.value = { kind: 'stock', item }
}

function addActionRule(side: ActionType): void {
  if (!canEditDetails.value) return
  const firstSubtype = subtypeOptions(side)[0]?.name ?? null
  const item: DraftActionRule = {
    detail_id: null, name: null, action_type: side, action_subtype: firstSubtype,
    content: null, display_order: form.value.action_rules.length + 1, enabled: true,
  }
  form.value.action_rules.push(item)
  expandedRule.value = { kind: 'action', item }
}

function copyStockRule(index: number): void {
  if (!canEditDetails.value) return
  const source = form.value.stock_rules[index]
  const copied: DraftStockRule = {
    ...source,
    checklist_items: (source.checklist_items ?? []).map(entry => ({ ...entry, item_id: `tdci_${crypto.randomUUID()}` })),
    detail_id: null,
    name: source.name ? `${source.name}-副本` : null,
  }
  form.value.stock_rules.splice(index + 1, 0, copied)
  expandedRule.value = { kind: 'stock', item: copied }
}

function copyActionRule(index: number): void {
  if (!canEditDetails.value) return
  const source = form.value.action_rules[index]
  const copied: DraftActionRule = {
    ...source,
    detail_id: null,
    name: source.name ? `${source.name}-副本` : null,
  }
  form.value.action_rules.splice(index + 1, 0, copied)
  expandedRule.value = { kind: 'action', item: copied }
}

// 新增/复制项没有 detail_id，以对象身份分配稳定 key，重排时保留展开内容和输入焦点。
const ruleKeys = new WeakMap<object, string>()
let nextRuleKey = 0
function ruleKey(item: DraftStockRule | DraftActionRule): string {
  if (item.detail_id) return item.detail_id
  if (!ruleKeys.has(item)) ruleKeys.set(item, `local-rule-${++nextRuleKey}`)
  return ruleKeys.get(item)!
}

function reorderStock(items: DraftStockRule[]): void {
  if (canEditDetails.value && !command.value) form.value.stock_rules = items
}

function removeStock(index: number): void {
  if (!canEditDetails.value) return
  const [removed] = form.value.stock_rules.splice(index, 1)
  if (expandedRule.value?.item === removed) expandedRule.value = null
}
function removeAction(index: number): void {
  if (!canEditDetails.value) return
  const [removed] = form.value.action_rules.splice(index, 1)
  if (expandedRule.value?.item === removed) expandedRule.value = null
}

function reorderActions(side: ActionType, items: DraftActionRule[]): void {
  if (!canEditDetails.value || command.value) return
  // 仅替换当前方向占用的位置，另一方向的顺序和内容保持稳定。
  let index = 0
  form.value.action_rules = form.value.action_rules.map(item => (
    item.action_type === side ? items[index++] : item
  ))
}

function managementText(): string {
  const event = detail.value?.latest_management_event
  if (!event) return isUnpublished.value ? '草稿（未发布）' : latestVersionLabel.value
  const verb = event.event_type === 'archive' ? '归档' : event.event_type === 'restore' ? '恢复' : `发布 v${event.version_no}`
  return detail.value?.has_pending_management_action
    ? `${verb}，待 ${event.effective_from_trade_date} 生效`
    : `${verb}已生效`
}

function effectiveText(): string {
  if (detail.value?.effective_status === 'active') return `当前按 v${detail.value.effective_version?.version_no ?? '—'} 履约`
  return detail.value?.effective_status === 'archived' ? '当前已归档' : '当前尚未生效'
}

watch(() => [props.ruleId, props.tradeDate], load, { immediate: true })

defineExpose({
  isDirty: () => dirty.value,
  requestLeave,
  saveDraft,
  discardUnsavedChanges,
})
</script>

<template>
  <AppScrollArea as="section" class="rule-editor" aria-label="规则编辑工作区" data-testid="rule-editor">
    <AppStateBlock v-if="loading" state="loading" title="正在加载规则…" />
    <AppStateBlock v-else-if="loadError" state="error" title="规则详情加载失败" retry @retry="load" />
    <template v-else-if="detail">
      <header class="rule-editor__head">
        <div>
          <div class="detail-kicker">{{ latestVersionLabel }}</div>
          <h3 class="app-section-title">{{ form.name || detail.name || '未命名规则' }}</h3>
        </div>
        <AppStatusNotice v-if="typesError" tone="warning" title="买卖类型加载失败" action-text="重试" @action="refreshTypes" />
        <div v-if="canManage" class="rule-editor__commands">
          <el-button v-permission="'trade-discipline:rule-manage'" :loading="command === 'copy'" @click="copyRule">复制</el-button>
          <el-button
            v-if="!isUnpublished"
            v-permission="'trade-discipline:rule-manage'"
            :type="isArchived ? 'success' : 'danger'"
            plain
            :loading="command === 'archive' || command === 'restore'"
            @click="archiveOrRestore"
          >{{ isArchived ? '恢复' : '归档' }}</el-button>
          <el-button v-else v-permission="'trade-discipline:rule-manage'" type="danger" plain :loading="command === 'delete'" @click="removeUnpublished">删除</el-button>
        </div>
      </header>

      <AppStatusNotice v-if="!canManage" class="readonly-notice" title="当前账号只有查看权限" />
      <AppStatusNotice
        v-else-if="isArchived"
        class="readonly-notice"
        tone="warning"
        title="归档规则不可编辑"
        description="恢复后可重新创建工作草稿"
      />
      <AppStatusNotice
        v-else-if="!editing"
        class="readonly-notice"
        title="当前展示最新正式版本"
        description="创建工作草稿后再修改，正式版本不会被覆盖"
      >
        <template #action>
          <el-button v-permission="'trade-discipline:rule-manage'" link type="primary" size="small" :loading="command === 'open'" @click="beginEdit">编辑规则</el-button>
        </template>
      </AppStatusNotice>

      <div class="rule-state-track" aria-label="规则双状态">
        <div><span>当前有效</span><strong>{{ effectiveText() }}</strong></div>
        <div><span>管理动作</span><strong>{{ managementText() }}</strong></div>
        <div><span>编辑现场</span><strong>{{ hasSavedDraft ? `草稿 r${draftRevision}` : '无工作草稿' }}</strong></div>
      </div>

      <AppForm class="rule-editor__form" label-position="top" :disabled="!canEditDetails">
        <div class="rule-editor__base">
          <el-form-item label="规则名称" :required="editing && canManage">
            <el-input v-model="form.name" data-testid="rule-name-input" maxlength="80" placeholder="例如：趋势突破纪律" />
          </el-form-item>
          <el-form-item label="总本金（元）" :required="editing && canManage">
            <FixedDecimalInput v-model="form.capital" grouped data-testid="rule-capital-input" />
          </el-form-item>
          <el-form-item label="最大同时持仓数">
            <el-input-number :model-value="form.max_positions ?? undefined" :min="1" :max="2147483647" :precision="0" :step="1" :controls="false" placeholder="不限" data-testid="rule-max-positions" @update:model-value="form.max_positions = $event ?? null" />
            <AppFormHelp>本套规则同时持有的不同股票数量上限，留空不限。</AppFormHelp>
          </el-form-item>
          <el-form-item label="资金分配">
            <div class="capital-meter" :class="{ danger: capitalExceeded }">
              <span>启用规则已分配 {{ allocatedCapitalText }}</span>
              <strong>剩余 {{ remainingCapitalText }}</strong>
            </div>
          </el-form-item>
        </div>

        <section class="detail-group">
          <header><div><h4 class="app-section-title">选股规则</h4><p>仅启用项参与发布校验和资金汇总</p></div><el-button v-if="canEditDetails" v-permission="'trade-discipline:rule-manage'" :icon="Plus" @click="addStockRule">添加选股规则</el-button></header>
          <AppStateBlock v-if="!form.stock_rules.length" state="empty" size="tiny" title="尚未添加选股规则" />
          <AppReorderList
            v-else
            :items="form.stock_rules"
            :item-key="ruleKey"
            :item-label="item => cardTitle(item, '未命名选股规则')"
            label="选股规则排序"
            :disabled="!canEditDetails || !!command"
            @reorder="reorderStock"
          >
            <template #default="{ item, index }">
              <RuleSummaryCard
                :panel-id="`stock-rule-panel-${index}`"
                :index-label="cardIndex(index)"
                :title="cardTitle(item, `未命名选股规则 ${index + 1}`)"
                :meta="stockCapitalMeta(item)"
                :content="[stockConditionSummary(item), item.content].filter(Boolean).join(' · ')"
                :enabled="item.enabled"
                :expanded="isRuleExpanded('stock', item)"
                :editable="canEditDetails"
                data-testid="stock-rule-card"
                @toggle="toggleRule('stock', item)"
                @update:enabled="item.enabled = $event"
              >
                <template #actions>
                  <AppIconButton v-permission="'trade-discipline:rule-manage'" label="复制选股规则" size="sm" @click="copyStockRule(index)"><CopyDocument /></AppIconButton>
                  <AppIconButton v-permission="'trade-discipline:rule-manage'" label="删除选股规则" size="sm" tone="danger" @click="removeStock(index)"><Delete /></AppIconButton>
                </template>
                <div class="rule-card-form rule-card-form--stock">
                  <el-form-item label="规则名称" :required="editing && canManage"><el-input v-model="item.name" data-testid="stock-rule-name-input" maxlength="80" /></el-form-item>
                  <el-form-item label="资金上限（元）" :required="editing && canManage && item.enabled"><FixedDecimalInput v-model="item.max_capital" grouped data-testid="stock-rule-capital-input" /></el-form-item>
                  <StockRuleChecklistEditor :panel-defaults="conditionPanelDefaults" :ref="(component: unknown) => setStockChecklistRef(item, component)" class="rule-card-form__content" :model-value="item.checklist_items ?? []" :rule="item" :disabled="!canEditDetails"
                    :open-sections="stockSectionStates[stockStateKey(item)] ?? {}" @update:open-sections="stockSectionStates[stockStateKey(item)] = $event" @update:model-value="item.checklist_items = $event">
                    <template #basic>
                  <el-form-item label="股价下限（元）"><FixedDecimalInput :model-value="item.price_min ?? null" @update:model-value="item.price_min = $event" :scale="4" :integer-digits="16" placeholder="不限" data-testid="stock-price-min" /></el-form-item>
                  <el-form-item label="股价上限（元）"><FixedDecimalInput :model-value="item.price_max ?? null" @update:model-value="item.price_max = $event" :scale="4" :integer-digits="16" placeholder="不限" data-testid="stock-price-max" /></el-form-item>
                    </template>
                    <template #risk>
                  <el-form-item v-for="condition in stockConditionFields" :key="condition.key" :label="condition.label">
                    <AppSelect
                      v-model="item[condition.key]"
                      :data-testid="`stock-${condition.key}`"
                    ><el-option v-for="option in conditionFilterOptions" :key="option.value" :label="option.label" :value="option.value" /></AppSelect>
                  </el-form-item>
                    </template>
                    <template #notes>
                      <el-form-item><el-input v-model="item.content" aria-label="补充说明" type="textarea" :autosize="{ minRows: 3 }" resize="vertical" placeholder="补充解释、适用场景；需要逐项核对的条件请添加为检查项" /></el-form-item>
                    </template>
                  </StockRuleChecklistEditor>
                </div>
              </RuleSummaryCard>
            </template>
          </AppReorderList>
        </section>

        <TradeDisciplineSectionPanel
          class="detail-group"
          title="买卖规则"
          description="按方向分组，正式发布至少启用一条买入和一条卖出规则"
          data-testid="action-rules-section"
        >
          <TradeDirectionGroupGrid :groups="actionGroups">
            <template #actions="{ group }">
              <el-button v-if="canEditDetails" v-permission="'trade-discipline:rule-manage'" :icon="Plus" @click="addActionRule(group.value)">添加</el-button>
            </template>
            <template #default="{ group }">
              <AppStateBlock v-if="!groupedActionRules(group.value).length" state="empty" size="tiny" :title="`尚未添加${group.label}`" />
              <AppReorderList
                v-else
                :items="groupedActionRules(group.value)"
                :item-key="ruleKey"
                :item-label="item => cardTitle(item, `未命名${group.label}`)"
                :label="`${group.label}排序`"
                :disabled="!canEditDetails || !!command"
                @reorder="reorderActions(group.value, $event)"
              >
                <template #default="{ item, index: groupIndex }">
                  <RuleSummaryCard
                    :panel-id="`${group.value}-rule-panel-${groupIndex}`"
                    :index-label="cardIndex(groupIndex)"
                    :title="cardTitle(item, `未命名${group.label} ${groupIndex + 1}`)"
                    :meta="`类型 · ${subtypeLabel(item)}`"
                    :content="item.content"
                    :enabled="item.enabled"
                    :expanded="isRuleExpanded('action', item)"
                    :editable="canEditDetails"
                    data-testid="action-rule-card"
                    @toggle="toggleRule('action', item)"
                    @update:enabled="item.enabled = $event"
                  >
                    <template #actions>
                      <AppIconButton v-permission="'trade-discipline:rule-manage'" label="复制买卖规则" size="sm" @click="copyActionRule(form.action_rules.indexOf(item))"><CopyDocument /></AppIconButton>
                      <AppIconButton v-permission="'trade-discipline:rule-manage'" label="删除买卖规则" size="sm" tone="danger" @click="removeAction(form.action_rules.indexOf(item))"><Delete /></AppIconButton>
                    </template>
                    <div class="rule-card-form rule-card-form--action">
                      <el-form-item label="规则名称" :required="editing && canManage"><el-input v-model="item.name" data-testid="action-rule-name-input" maxlength="80" /></el-form-item>
                      <el-form-item :required="editing && canManage">
                        <template #label>
                          类型
                          <HelpTip title="类型说明" :width="360" test-id="action-rule-type-help">
                            <HelpTipItem question="类型如何维护">
                              <ul>
                                <li>买入与卖出类型分别在系统数据字典维护，支持新增、排序和停用；旧规则保留原类型。</li>
                              </ul>
                            </HelpTipItem>
                          </HelpTip>
                        </template>
                        <AppSelect
                          :model-value="item.action_subtype"
                          @update:model-value="item.action_subtype = $event; item.action_subtype_label = null"
                          filterable
                          default-first-option
                          placeholder="选择类型"
                          data-testid="action-rule-type-select"
                          popper-class="app-option-popper trade-rule-subtype-popper"
                        >
                          <el-option
                            v-if="subtypeIsMissing(item, group.value)"
                            :label="missingSubtypeLabel(item)"
                            :value="item.action_subtype"
                            disabled
                          />
                          <el-option v-for="option in subtypeOptions(group.value)" :key="option.name" :label="option.label || option.name" :value="option.name" />
                        </AppSelect>
                      </el-form-item>
                      <el-form-item class="rule-card-form__content" label="规则内容" :required="editing && canManage"><el-input v-model="item.content" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" resize="vertical" /></el-form-item>
                    </div>
                  </RuleSummaryCard>
                </template>
              </AppReorderList>
            </template>
          </TradeDirectionGroupGrid>
        </TradeDisciplineSectionPanel>
      </AppForm>

      <footer v-if="canManage && editing" class="rule-editor__footer">
        <span v-if="dirty" class="dirty-copy">有未保存修改</span>
        <el-button v-permission="'trade-discipline:rule-manage'" :disabled="!dirty" @click="restoreBaseline">还原修改</el-button>
        <el-button v-if="hasSavedDraft && !isUnpublished" v-permission="'trade-discipline:rule-manage'" type="danger" plain :loading="command === 'discard'" @click="discardSavedDraft">放弃草稿</el-button>
        <el-button v-permission="'trade-discipline:rule-manage'" :disabled="!dirty" :loading="command === 'save'" @click="saveDraft()">保存草稿</el-button>
        <el-button v-permission="'trade-discipline:rule-manage'" type="primary" :disabled="!dirty" :loading="command === 'publish'" @click="publish">保存并启用</el-button>
      </footer>

    </template>
  </AppScrollArea>
</template>

<style scoped>
.rule-editor { min-width: 0; min-height: 0; --app-scroll-padding-top: var(--app-space-5); --app-scroll-padding-right: var(--app-space-5); --app-scroll-padding-bottom: var(--app-space-5); --app-scroll-padding-left: var(--app-space-5); border: 1px solid var(--el-border-color); border-radius: var(--layout-card-radius); background: var(--el-bg-color); }
.rule-editor__head, .rule-editor__commands, .detail-group > header, .rule-editor__footer { display: flex; align-items: center; }
.rule-editor__head { justify-content: space-between; gap: var(--app-space-3); }
.rule-editor__head .app-section-title { margin: var(--app-space-1) 0 0; }
.rule-editor__commands { gap: var(--app-space-1); }
.rule-state-track { margin: var(--app-space-4) 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--el-border-color-lighter); border-radius: var(--layout-control-radius); overflow: hidden; }
.rule-state-track > div { padding: var(--app-space-3); background: transparent; }
.rule-state-track > div + div { border-left: 1px solid var(--el-border-color-lighter); }
.rule-state-track span { display: block; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.rule-state-track strong { display: block; margin-top: var(--app-space-1); color: var(--el-text-color-primary); font-size: var(--app-font-size-table); }
.readonly-notice { margin: var(--app-space-4) 0; }
.rule-editor__base { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-3); align-items: start; }
.rule-editor__base :deep(.el-input), .rule-editor__base :deep(.el-input-number) { width: 100%; }
.capital-meter { box-sizing: border-box; width: 100%; min-height: var(--app-density-control-height, var(--app-control-height-md)); padding: 0 var(--app-space-3); border: 1px solid var(--app-border-success); border-radius: var(--layout-control-radius); background: transparent; color: var(--el-color-success); display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-2); font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); }
.capital-meter.danger { border-color: var(--app-border-danger); background: transparent; color: var(--el-color-danger); }
.detail-group { margin-top: var(--app-space-5); }
.detail-group > header { justify-content: space-between; gap: var(--app-space-3); margin-bottom: var(--app-space-2); }

.detail-group p { margin: var(--app-space-1) 0 0; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.rule-card-form { display: grid; row-gap: 0; column-gap: var(--app-space-3); }
.rule-card-form--stock { grid-template-columns: minmax(180px, 1fr) minmax(180px, 0.7fr); }
.rule-card-form--action { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
.rule-card-form__content { grid-column: 1 / -1; }
.rule-card-form :deep(.el-select), .rule-card-form :deep(.el-input) { width: 100%; }
.rule-editor__footer { position: sticky; bottom: 0; z-index: 2; justify-content: flex-end; flex-wrap: wrap; gap: var(--app-space-2); margin: var(--app-space-5) calc(var(--app-space-5) * -1) calc(var(--app-space-5) * -1); padding: var(--app-space-3) var(--app-space-5); border-top: 1px solid var(--el-border-color); background: var(--el-bg-color); }
.dirty-copy { margin-right: auto; color: var(--el-color-warning); font-size: var(--app-font-size-caption); }
@container app-viewport (max-width: 1100px) {
  .rule-editor { }
  .rule-state-track, .rule-editor__base { grid-template-columns: 1fr; }
  .rule-state-track > div + div { border-left: 0; border-top: 1px solid var(--el-border-color-lighter); }
}
@container app-viewport (max-width: 760px) {
  .rule-editor__head, .detail-group > header { align-items: stretch; flex-direction: column; }
  .rule-editor__commands { flex-wrap: wrap; }
  .rule-card-form--stock, .rule-card-form--action { grid-template-columns: 1fr; }
  .rule-card-form__content { grid-column: auto; }
}
</style>

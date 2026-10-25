<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import type { TableSortChange } from '@/composables/useTableSort'
import AppControlRow from '@/components/AppControlRow.vue'
import AppWorkspacePane from '@/components/AppWorkspacePane.vue'
import AppControlItem from '@/components/AppControlItem.vue'
import AppForm from '@/components/AppForm.vue'
import AppFormHelp from '@/components/AppFormHelp.vue'
import HelpHint from '@/components/HelpHint.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import TradeDisciplineSectionPanel from '@/components/trade-discipline/TradeDisciplineSectionPanel.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppDatePicker from '@/components/AppDatePicker.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppAdvancedSearch from '@/components/AppAdvancedSearch.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import AppDetailDrawer from '@/components/AppDetailDrawer.vue'
import { formatMoney } from '@/utils/money'
import { marketValueClass } from '@/utils/marketValue'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import { getErrorMessage } from '@/utils/error'
import { hasPermission } from '@/utils/permission'
import { useAuthStore } from '@/stores/auth'
import { useStockSet } from '@/stores/stockSet'
import { checkinAssessmentLabel, checkinAssessmentTagType } from '@/utils/tradeDisciplineAssessment'
import { decimalToMinorUnits, formatMinorUnits, multiplyToMinorUnits } from '@/utils/fixedDecimal'
import { manualConditionDefaults, checklistDefaults } from '@/utils/tradeDisciplineConditions'
import type { CheckinAssessment, CheckinOperation, RuleVersionDetail, StockOption, TradeDisciplineRule } from '@/api/tradeDiscipline'
import { getLedgerContext, initializeLedger, ledgerEventPayload, submitLedger, previewLedger,
  withdrawLedger, getLedgerHistory, getLedgerRevision,
  type LedgerContext, type LedgerEvent, type LedgerOmission, type LedgerSnapshot, type LedgerHistoryRow } from '@/api/tradeLedger'
import type { StockConditionPanelDefaults } from '@/layout/configPanel'
import FixedDecimalInput from './FixedDecimalInput.vue'
import StockOptionSelect from './StockOptionSelect.vue'
import TradeOperationEditor from './TradeOperationEditor.vue'

const props = withDefaults(defineProps<{
  mode: 'checkin' | 'positions' | 'history'
  tradeDate: string
  canSubmit: boolean
  pageSize?: number
  tableBorder?: boolean
  conditionPanelDefaults?: StockConditionPanelDefaults
  ruleOptions?: TradeDisciplineRule[]
  preferredRuleId?: string
  defaultSort?: Record<string, unknown>
  sortOrder?: 'asc' | 'desc'
  hiddenColumns?: string[]
}>(), { pageSize: 20, tableBorder: false })
const emit = defineEmits<{
  submitted: []
  'request-date-change': [date: string]
  'request-checkin': [date: string]
  'page-size-change': [size: number]
  'sort-change': [sort: TableSortChange]
}>()
const context = ref<LedgerContext | null>(null)
const loading = ref(false)
const error = ref('')
const busy = ref(false)
const editing = ref(false)
const events = ref<LedgerEvent[]>([])
const omissions = ref<LedgerOmission[]>([])
const reviewNote = ref('')
const baseline = ref('')
const preview = ref<LedgerSnapshot | null>(null)
const previewError = ref('')
const previewBusy = ref(false)
const selectedRule = ref('')
const entryRules = ref<string[]>([])
const operationEditors = new Map<string, InstanceType<typeof TradeOperationEditor>>()
function setOperationEditor(ruleId: string, editor: unknown) {
  if (editor) operationEditors.set(ruleId, editor as InstanceType<typeof TradeOperationEditor>)
  else operationEditors.delete(ruleId)
}
const linkedTradeId = ref('')
const openingRows = ref<{ key: string; stock: StockOption | null; quantity: string | null; cost_price: string | null; group: string }[]>([])
const openingCash = ref<string | null>(null)
const initialConfirmed = ref(false)
const history = ref<LedgerHistoryRow[]>([])
const total = ref(0)
const page = ref(1)
const historyBusy = ref(false)
const historyError = ref('')
const historyAssessment = ref('')
const historyStock = ref<StockOption | null>(null)
const historyRule = ref('')
const includeWithdrawn = ref(false)
const historyDates = ref<[string, string] | null>(null)
const assessmentOptions = ['complied', 'partial', 'breached', 'pending'].map(value => ({
  value, label: value === 'pending' ? '待核对' : checkinAssessmentLabel(value as CheckinAssessment),
}))
const filterRuleOptions = computed(() => (props.ruleOptions?.length ? props.ruleOptions : rules.value.map(rule => ({ id: rule.rule_id, name: rule.name })))
  .map(rule => ({ value: rule.id, label: rule.name || '未命名规则' })))
function columnVisible(key: string) { return !props.hiddenColumns?.includes(key) }
const detailOpen = ref(false)
const detail = ref<LedgerHistoryRow | null>(null)
const revisionNo = ref(1)
const detailSnapshot = ref<LedgerSnapshot | null>(null)
const detailBusy = ref(false)
const detailError = ref('')
const detailRuleIds = ref<string[]>([])
const withdrawConfirm = ref(false)
let loadSeq = 0
let previewSeq = 0
let historySeq = 0
let detailSeq = 0
let timer: ReturnType<typeof setTimeout> | undefined
let requestId = crypto.randomUUID()
const initialized = computed(() => !!context.value?.initialized_on)
const disabled = computed(() => !props.canSubmit || !context.value?.can_edit || (!!context.value.snapshot && !editing.value) || busy.value)
const showEntryControls = computed(() => props.mode === 'checkin' && !loading.value && initialized.value
  && !!context.value?.initialized_on && props.tradeDate >= context.value.initialized_on
  && props.canSubmit && context.value.can_edit && (!context.value.snapshot || editing.value))
const shown = computed(() => preview.value ?? context.value?.snapshot ?? null)
const positions = computed(() => props.mode === 'positions' ? context.value?.positions ?? [] : shown.value?.positions ?? context.value?.opening_positions ?? [])
const positionCount = computed(() => new Set(positions.value.map(p => p.stock_code)).size)
const auth = useAuthStore()
const stockSet = useStockSet()
const canViewStockDetail = computed(() => hasPermission(auth.role, auth.permissions, 'stocks:view'))
function rememberPositionStocks() {
  if (!canViewStockDetail.value) return
  // 同股可能分属多套规则，详情集合按股票去重，并保留持仓查看日期作为返回上下文。
  const stocks = new Map(positions.value.filter(item => item.stock_code).map(item => [
    item.stock_code, { code: item.stock_code, name: item.stock_name },
  ]))
  stockSet.setResultSet([...stocks.values()], '交易纪律持仓',
    `/trade-discipline?tab=positions&trade_date=${encodeURIComponent(props.tradeDate)}`)
}
const trades = computed(() => events.value.filter(e => e.kind === 'trade'))
const adjustments = computed(() => events.value.filter(e => e.kind !== 'trade'))
const rules = computed(() => context.value?.rules ?? [])
const hasStockGroups = computed(() => rules.value.some(rule => rule.stock_rules.some(group => group.enabled)))
const unplannedRule: RuleVersionDetail = {
  rule_id: '', version_no: 1, name: '未按任何已设规则操作', capital: '0',
  stock_rules: [{ detail_id: 'unplanned', name: '未按选股规则', max_capital: null, content: null, enabled: true, display_order: 1 }],
  action_rules: ['buy', 'sell'].map((side, i) => ({ detail_id: side, name: '未按买卖规则', action_type: side as 'buy' | 'sell', action_subtype: null, content: null, enabled: true, display_order: i + 1 })),
}
const activeEntryRules = computed(() => entryRules.value.map(id => rules.value.find(r => r.rule_id === id) ?? unplannedRule))
const linkableTrades = computed(() => trades.value.filter(event => selectedRule.value
  && event.stock_code?.trim()
  && event.rule_id !== selectedRule.value
  && !event.rule_checks?.some(check => check.rule_id === selectedRule.value)))
// 关联只追加规则核对；空白草稿不作为候选，候选删除或规则切换后不能留下失效选择。
watch(linkableTrades, candidates => {
  if (!candidates.some(event => event.event_id === linkedTradeId.value)) {
    linkedTradeId.value = candidates.length === 1 ? candidates[0].event_id : ''
  }
})
const dirty = () => busy.value || baseline.value !== snapshot()
async function requestLeave(): Promise<boolean> {
  if (busy.value) { ElMessage.warning('正在保存账户记录，请完成后再离开'); return false }
  if (!dirty()) return true
  try {
    await ElMessageBox.confirm('当前记录尚未提交，离开会丢失本次修改。', '放弃未提交修改？', {
      confirmButtonType: 'danger', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑',
      type: 'warning', closeOnClickModal: false, closeOnPressEscape: false, showClose: false,
    })
    await load()
    return true
  } catch { return false }
}
function snapshot() { return JSON.stringify({ events: events.value, omissions: omissions.value, note: reviewNote.value,
  opening: openingRows.value, cash: openingCash.value, confirmed: initialConfirmed.value }) }
function label(value: CheckinAssessment | null | undefined) { return value ? checkinAssessmentLabel(value) : '待核对' }
function ruleName(id: string | null) { return rules.value.find(r => r.rule_id === id)?.name ?? '未分配规则' }
function stockOption(code: string, name?: string): StockOption | null {
  return code ? { code, name: name || code, board: null, industry: null } : null
}
function payload() {
  if (!context.value) throw new Error('请先加载账户')
  return { trade_date: props.tradeDate, request_id: requestId,
    expected_account_revision: context.value.account_revision, expected_revision: context.value.current_revision_no,
    events: events.value.map(ledgerEventPayload),
    omissions: omissions.value.map(({ kind, stock_code, rule_id }) => ({ kind, stock_code, rule_id })),
    review_note: reviewNote.value || null }
}
async function load() {
  if (!props.tradeDate) return
  const seq = ++loadSeq
  ++previewSeq
  if (timer) clearTimeout(timer)
  loading.value = true
  error.value = ''
  try {
    const value = await getLedgerContext(props.tradeDate)
    if (seq !== loadSeq) return
    context.value = value
    events.value = (value.snapshot?.events ?? []).map(e => ({ ...e, client_key: e.event_id,
      operated_at: e.operated_at?.slice(0, 19) ?? null }))
    omissions.value = value.snapshot?.omissions.map(o => ({ ...o })) ?? []
    reviewNote.value = value.snapshot?.review_note ?? ''
    editing.value = !value.snapshot
    preview.value = null
    previewError.value = ''
    selectedRule.value = value.rules.some(rule => rule.rule_id === props.preferredRuleId)
      ? props.preferredRuleId! : value.rules[0]?.rule_id ?? ''
    entryRules.value = [...new Set([...trades.value.flatMap(e => [e.rule_id || '', ...(e.rule_checks ?? []).map(c => c.rule_id)]), selectedRule.value])]
    openingRows.value = []
    openingCash.value = null
    initialConfirmed.value = false
    requestId = crypto.randomUUID()
    baseline.value = snapshot()
  } catch (err) {
    if (seq === loadSeq) { error.value = getErrorMessage(err, '交易账户加载失败'); context.value = null }
  } finally { if (seq === loadSeq) loading.value = false }
}
function updateGroup(ruleId: string, operations: CheckinOperation[]) {
  const key = (operation: CheckinOperation) => operation.event_id || operation.client_key || operation.id || ''
  const incoming = new Map(operations.map(operation => [key(operation), operation]))
  let order = Math.max(0, ...events.value.map(e => e.display_order))
  const next: LedgerEvent[] = []
  for (const event of events.value) {
    if (event.kind !== 'trade') { next.push(event); continue }
    const operation = incoming.get(event.event_id)
    if ((event.rule_id || '') === ruleId) {
      if (operation) next.push({ ...event, ...operation, rule_checks: event.rule_checks })
    } else {
      const checks = (event.rule_checks ?? []).filter(check => check.rule_id !== ruleId)
      if (operation) checks.push({ rule_id: ruleId, stock_rule_id: operation.stock_rule_id,
        action_rule_id: operation.action_rule_id, action_matches: operation.action_matches ?? true,
        stock_matches: operation.stock_matches ?? true,
        checklist_results: operation.checklist_results, loss_status: operation.loss_status,
        st_risk_status: operation.st_risk_status })
      next.push({ ...event, rule_checks: checks })
    }
    incoming.delete(event.event_id)
  }
  for (const operation of incoming.values()) {
    next.push({ ...operation, kind: 'trade', rule_id: ruleId || null,
      event_id: key(operation) || crypto.randomUUID(), display_order: ++order })
  }
  events.value = next.sort((a, b) => a.display_order - b.display_order)
}
function linkExistingTrade() {
  const event = events.value.find(e => e.event_id === linkedTradeId.value)
  const rule = rules.value.find(r => r.rule_id === selectedRule.value)
  if (!event || !rule || !linkableTrades.value.includes(event)) return
  const stockRules = rule.stock_rules.filter(r => r.enabled)
  const stockRule = stockRules.length === 1 ? stockRules[0] : undefined
  const actions = rule.action_rules.filter(r => r.enabled && r.action_type === event.side)
  event.rule_checks = [...event.rule_checks ?? [], {
    rule_id: rule.rule_id, stock_rule_id: stockRule?.detail_id ?? '',
    action_rule_id: actions.length === 1 ? actions[0].detail_id! : '', action_matches: true,
    checklist_results: checklistDefaults(stockRule, event.side), ...manualConditionDefaults(stockRule, event.side),
  }]
  addRule()
  linkedTradeId.value = ''
}
function operationsForRule(allEvents: LedgerEvent[], ruleId: string) {
  return allEvents.filter(event => event.kind === 'trade').flatMap(event => {
    if ((event.rule_id || '') === ruleId) {
      return [event.rule_id ? event : { ...event, stock_rule_id: 'unplanned', action_rule_id: event.side }]
    }
    const check = event.rule_checks?.find(item => item.rule_id === ruleId)
    return check ? [{ ...event, ...check, linked: true, client_key: `${event.event_id}:${ruleId}` }] : []
  })
}
function groupOperations(ruleId: string) { return operationsForRule(trades.value, ruleId) }
function addRule() { if (!entryRules.value.includes(selectedRule.value)) entryRules.value.push(selectedRule.value) }
function addOmission() { omissions.value.push({ kind: 'missed_buy', stock_code: '', rule_id: rules.value[0]?.rule_id ?? '' }) }
function addOpeningRow() {
  openingRows.value.push({ key: crypto.randomUUID(), stock: null, quantity: null, cost_price: null, group: '' })
}
/** 同成交金额复用定点乘法，仅作展示；最终成本由服务端重算。 */
function costTotal(price: string | null | undefined, quantity: string | null | undefined, legacyTotal?: string | null) {
  const total = multiplyToMinorUnits(price, quantity)
  return total === null ? legacyTotal == null ? '未录入' : `${formatMoney(legacyTotal)} 元` : `${formatMoney(formatMinorUnits(total))} 元`
}
function changePositionType(item: LedgerEvent) {
  if (item.adjustment_type === 'bonus' || item.adjustment_type === 'split') {
    item.amount = null
    item.cost_price = null
  }
  if (item.adjustment_type === 'bonus') item.side = 'buy'
}
function changeCashType(item: LedgerEvent) {
  item.direction = item.adjustment_type === 'withdrawal' ? 'out' : 'in'
  if (item.adjustment_type !== 'dividend') { item.stock_code = ''; item.stock_name_snapshot = '' }
}
function addAdjustment(kind: 'position' | 'cash') {
  const order = Math.max(0, ...events.value.map(e => e.display_order)) + 1
  events.value.push({ event_id: crypto.randomUUID(), kind, rule_id: null, stock_code: '', stock_name_snapshot: '',
    adjustment_type: kind === 'cash' ? 'deposit' : 'transfer',
    side: 'buy', direction: 'in', stock_rule_id: '', action_rule_id: '', price: null, quantity: null,
    amount: null, fee: null, operated_at: `${props.tradeDate}T09:00:00`, note: '', display_order: order })
}
async function runPreview() {
  if (disabled.value || !initialized.value) return
  const seq = ++previewSeq
  previewBusy.value = true
  previewError.value = ''
  try {
    const value = await previewLedger(payload())
    if (seq === previewSeq) preview.value = value
  } catch (err) {
    if (seq === previewSeq) { preview.value = null; previewError.value = getErrorMessage(err, '请补齐成交后核对') }
  } finally { if (seq === previewSeq) previewBusy.value = false }
}
async function save() {
  if (disabled.value || busy.value) return
  for (const rule of activeEntryRules.value) {
    const invalid = operationEditors.get(rule.rule_id)?.validate?.()
    if (invalid) { previewError.value = `${rule.name}：${invalid}`; return }
  }
  busy.value = true
  try {
    await submitLedger(payload())
    await load()
    emit('submitted')
    ElMessage.success('记录已保存，持仓与履约结果已更新')
  } catch (err) { previewError.value = getErrorMessage(err, '保存失败，填写内容已保留') }
  finally { busy.value = false }
}
async function initialize() {
  if (!props.canSubmit || !context.value || busy.value) return
  if (!initialConfirmed.value) { ElMessage.warning('请确认期初持仓已完整录入；空仓也需要确认'); return }
  busy.value = true
  try {
    await initializeLedger({ trade_date: props.tradeDate, expected_revision: context.value.account_revision,
      positions: openingRows.value.map(row => ({ stock_code: row.stock?.code ?? '', quantity: row.quantity, cost_price: row.cost_price,
        ...(row.group ? { rule_id: JSON.parse(row.group)[0], stock_rule_id: JSON.parse(row.group)[1] } : {}) })),
      cash: openingCash.value })
    await load()
    emit('submitted')
    ElMessage.success('期初持仓已建立')
  } catch (err) { error.value = getErrorMessage(err, '初始化失败') }
  finally { busy.value = false }
}
async function withdraw() {
  if (!context.value || !props.canSubmit || !context.value.can_edit || busy.value || withdrawConfirm.value) return
  const tradeDate = props.tradeDate
  const accountRevision = context.value.account_revision
  const contextSeq = loadSeq
  withdrawConfirm.value = true
  try {
    await ElMessageBox.confirm(
      `撤回 ${tradeDate} 的日结后，持仓恢复到前一日结，当日规则评价退出统计，历史修订仍保留。之后可重新填报。`,
      '撤回最新日结',
      { type: 'warning', confirmButtonType: 'danger', confirmButtonText: '确认撤回',
        cancelButtonText: '取消', closeOnClickModal: false, closeOnPressEscape: false, showClose: false },
    )
  } catch { return }
  finally { withdrawConfirm.value = false }
  // 确认只对打开时的交易日与账户版本有效，避免现场变化后撤回另一条日结。
  if (contextSeq !== loadSeq || props.tradeDate !== tradeDate || context.value?.account_revision !== accountRevision
    || !props.canSubmit || !context.value.can_edit || busy.value) return
  busy.value = true
  previewError.value = ''
  try {
    await withdrawLedger(tradeDate, accountRevision)
    await load()
    emit('submitted')
  } catch (err) { previewError.value = getErrorMessage(err, '撤回失败') }
  finally { busy.value = false }
}
async function loadHistory() {
  const seq = ++historySeq
  historyBusy.value = true
  historyError.value = ''
  try {
    const value = await getLedgerHistory(page.value, props.pageSize, {
      assessment: historyAssessment.value || undefined, stock_code: historyStock.value?.code,
      rule_id: historyRule.value || undefined, date_from: historyDates.value?.[0], date_to: historyDates.value?.[1],
      sort_order: props.sortOrder ?? 'desc',
      include_withdrawn: includeWithdrawn.value,
    })
    if (seq === historySeq) { history.value = value.list; total.value = value.total }
  } catch (err) { if (seq === historySeq) historyError.value = getErrorMessage(err, '历史加载失败') }
  finally { if (seq === historySeq) historyBusy.value = false }
}
function openDetail(row: LedgerHistoryRow) {
  detail.value = row
  revisionNo.value = row.current_revision_no
  detailSnapshot.value = row.snapshot
  detailError.value = ''
  detailOpen.value = true
  void loadRevision()
}
async function loadRevision() {
  if (!detail.value) return
  const seq = ++detailSeq
  detailBusy.value = true
  detailError.value = ''
  try {
    const value = await getLedgerRevision(detail.value.trade_date, revisionNo.value)
    if (seq === detailSeq) {
      detailSnapshot.value = value.snapshot
      detail.value.withdrawn = value.withdrawn
    }
  } catch (err) { if (seq === detailSeq) detailError.value = getErrorMessage(err, '修订加载失败') }
  finally { if (seq === detailSeq) detailBusy.value = false }
}
async function startAmend() {
  if (!props.canSubmit || !context.value?.can_edit || !context.value.snapshot) return false
  editing.value = true
  return true
}
function confirmReadiness() {
  const positive = (value: string | null, scale = 2) => (decimalToMinorUnits(value, scale) ?? 0n) > 0n
  return events.value.every(event => {
    if (!event.operated_at) return false
    if (event.kind === 'cash') return positive(event.amount) && !!event.note?.trim()
      && (event.adjustment_type !== 'dividend' || !!event.stock_code)
    if (event.kind === 'position') return !!event.stock_code && positive(event.quantity, 4) && !!event.note?.trim()
    return !!event.stock_code && positive(event.price, 4) && positive(event.quantity, 4)
      && event.fee != null && (decimalToMinorUnits(event.fee) ?? -1n) >= 0n
      && (!event.rule_id || (!!event.stock_rule_id && !!event.action_rule_id))
      && (event.amount_mode !== 'manual' || positive(event.amount))
      && (event.rule_checks ?? []).every(check => check.rule_id && check.stock_rule_id && check.action_rule_id)
  }) && omissions.value.every(o => o.stock_code && o.rule_id)
}
watch(() => [events.value, omissions.value, reviewNote.value], () => {
  requestId = crypto.randomUUID()
  preview.value = null
  previewError.value = ''
  ++previewSeq
  previewBusy.value = false
  if (timer) clearTimeout(timer)
  if (props.mode === 'checkin' && initialized.value && !disabled.value && dirty() && confirmReadiness()) {
    timer = setTimeout(() => { void runPreview() }, 700)
  }
}, { deep: true })
watch(() => props.tradeDate, () => { void load() }, { immediate: true })
watch(() => props.preferredRuleId, (id) => {
  if (id && rules.value.some(rule => rule.rule_id === id)) { selectedRule.value = id; addRule() }
})
watch(() => [props.mode, props.pageSize], () => { page.value = 1; if (props.mode === 'history') void loadHistory() }, { immediate: true })
watch(() => props.sortOrder, () => { page.value = 1; void loadHistory() })
watch([historyAssessment, historyStock, historyRule, historyDates, includeWithdrawn], () => { page.value = 1; void loadHistory() })
onBeforeUnmount(() => { ++loadSeq; ++previewSeq; ++historySeq; ++detailSeq; if (timer) clearTimeout(timer) })
defineExpose({ isDirty: dirty, requestLeave, load, startAmend, reload: loadHistory })
</script>

<template>
  <AppWorkspacePane class="ledger-workspace" data-testid="trade-ledger-workspace" :title="mode === 'checkin' ? '今日打卡' : mode === 'positions' ? '现有持仓' : '历史记录'" :header-visible="false" padding="standard" :scroll="mode === 'history' ? 'delegated' : 'body'" fill>
    <template v-if="mode !== 'history'" #toolbar>
      <AppControlItem :label="mode === 'positions' ? '查看日期' : '交易日'">
        <TradeDatePicker :model-value="tradeDate" :disabled="busy" @update:model-value="$event && emit('request-date-change', $event)" />
      </AppControlItem>
      <AppControlRow v-if="!loading && initialized && context?.initialized_on && tradeDate >= context.initialized_on" class="ledger-summary" aria-live="polite">
        <strong>{{ mode === 'positions' ? '已提交持仓' : preview ? '填写后预计持仓' : context?.snapshot ? '当日收盘持仓' : '期初持仓' }} {{ positionCount }} 只</strong>
        <span v-if="mode === 'checkin' && shown">当日峰值 {{ shown.peak_positions }} 只</span>
        <span v-if="mode === 'checkin' && shown">买入 {{ formatMoney(shown.buy_amount) }} · 卖出 {{ formatMoney(shown.sell_amount) }} · 费用 {{ formatMoney(shown.fee) }}</span>
        <el-tag v-if="mode === 'checkin' && shown" :type="shown.assessment ? checkinAssessmentTagType(shown.assessment) : 'info'">{{ label(shown.assessment) }}</el-tag>
      </AppControlRow>
      <template v-if="mode === 'checkin' && context?.snapshot">
        <span class="app-caption-text">r{{ context.current_revision_no }}</span>
        <el-button v-if="!editing && canSubmit && context.can_edit" v-permission="'trade-discipline:checkin-submit'" @click="startAmend">修正最新记录</el-button>
        <el-button v-if="editing && context.can_edit" :disabled="busy" type="danger" plain @click="load">取消修正</el-button>
        <el-button v-if="canSubmit && context.can_edit && !editing" v-permission="'trade-discipline:checkin-submit'" type="danger" plain :disabled="busy" :loading="busy" @click="withdraw">撤回最新日结</el-button>
      </template>
    </template>
    <AppStateBlock v-if="loading" state="loading" title="正在加载交易账本…" />
    <AppStateBlock v-else-if="error && !context" state="error" title="交易账户加载失败" :description="error" retry @retry="load" />
    <template v-else-if="mode !== 'history'">
      <AppStatusNotice v-if="error" tone="warning" :title="error" />
      <section v-if="!initialized" class="ledger-opening" data-testid="ledger-initialize">
        <header class="ledger-opening-head">
          <h3 class="app-section-title">建立期初持仓</h3>
          <p class="app-caption-text">只需建立一次。请填写 {{ tradeDate }} 开始前的真实持仓，后续由成交和调整记录自动延续。</p>
        </header>
        <AppForm label-position="top" :disabled="!canSubmit || busy">
          <div class="ledger-opening-layout">
            <TradeDisciplineSectionPanel title="期初股票" description="有持仓请逐只录入；空仓无需添加股票。">
              <AppControlRow justify="between" class="ledger-opening-toolbar">
                <span class="app-caption-text">已添加 {{ openingRows.length }} 条持仓</span>
                <el-button v-if="canSubmit" v-permission="'trade-discipline:checkin-submit'" :icon="Plus" @click="addOpeningRow">添加期初股票</el-button>
              </AppControlRow>
              <div v-if="!openingRows.length" class="ledger-opening-empty">
                <strong class="app-body-text">尚未添加期初股票</strong>
                <span class="app-caption-text">当前为空仓，可在下方确认后开始打卡。</span>
              </div>
              <article v-for="(row, index) in openingRows" :key="row.key" class="ledger-opening-position">
                <AppControlRow justify="between">
                  <strong class="app-body-text">持仓 {{ index + 1 }}{{ row.stock ? ` · ${row.stock.name}` : '' }}</strong>
                  <AppIconButton :label="`删除期初持仓 ${index + 1}`" tone="danger" :disabled="!canSubmit || busy" @click="openingRows = openingRows.filter(r => r.key !== row.key)"><Delete /></AppIconButton>
                </AppControlRow>
                <div class="ledger-opening-fields">
                  <el-form-item label="股票" required><StockOptionSelect v-model="row.stock" :trade-date="tradeDate" :disabled="!canSubmit || busy" /></el-form-item>
                  <el-form-item label="期初数量（股）" required><FixedDecimalInput v-model="row.quantity" :scale="4" :integer-digits="16" clearable /></el-form-item>
                  <el-form-item label="持仓成本价（元/股，选填）"><FixedDecimalInput v-model="row.cost_price" :scale="4" :integer-digits="16" clearable /><AppFormHelp>总成本：{{ costTotal(row.cost_price, row.quantity) }}，按成本价 × 数量计算。不填成本价时，暂不计算该持仓盈亏。</AppFormHelp></el-form-item>
                  <el-form-item v-if="hasStockGroups" label="所属规则分组（选填）"><AppSelect v-model="row.group" clearable placeholder="暂不分配"><el-option-group v-for="rule in rules" :key="rule.rule_id" :label="rule.name"><el-option v-for="group in rule.stock_rules.filter(r => r.enabled)" :key="group.detail_id!" :label="`${rule.name} · ${group.name}`" :value="JSON.stringify([rule.rule_id, group.detail_id])" /></el-option-group></AppSelect></el-form-item>
                </div>
              </article>
            </TradeDisciplineSectionPanel>
            <TradeDisciplineSectionPanel title="可用资金" description="开始记账前，证券账户里还没用于买股票的资金。">
              <el-form-item label="金额（元，选填）"><FixedDecimalInput v-model="openingCash" class="app-control-width-long" grouped clearable /></el-form-item>
              <AppFormHelp>填写后，余额会随买卖、手续费、入金出金和分红自动更新。</AppFormHelp>
              <p class="app-caption-text ledger-opening-note">不填也能进行交易纪律打卡，只是不计算现金余额；未填写不代表余额为零。</p>
            </TradeDisciplineSectionPanel>
          </div>
          <AppControlRow justify="between" class="ledger-opening-confirm">
            <el-checkbox v-model="initialConfirmed">已完整录入真实期初持仓（没有股票即为空仓）</el-checkbox>
            <el-button v-if="canSubmit" v-permission="'trade-discipline:checkin-submit'" type="primary" :disabled="!initialConfirmed" :loading="busy" @click="initialize">确认期初持仓</el-button>
            <span v-else class="app-caption-text">当前账号没有填报权限，暂不能初始化。</span>
          </AppControlRow>
        </AppForm>
      </section>
      <AppStatusNotice v-else-if="context?.initialized_on && tradeDate < context.initialized_on" tone="info" :title="`该日期早于账本起算日 ${context.initialized_on}，没有可查询的持仓记录。`" />
      <template v-else>
        <template v-if="mode === 'positions'">
          <AppDataTable :data="positions" :border="tableBorder" embedded empty-text="当前为空仓">
            <AppTableColumn prop="stock_code" label="代码">
              <template #default="{ row }">
                <RouterLink v-if="canViewStockDetail && row.stock_code" :to="{ name: 'stock-detail', params: { code: row.stock_code } }" class="app-table-field-link app-interaction-link app-interaction-link--primary" @click.stop="rememberPositionStocks">{{ row.stock_code }}</RouterLink>
                <span v-else>{{ row.stock_code }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn prop="stock_name" label="股票">
              <template #default="{ row }">
                <RouterLink v-if="canViewStockDetail && row.stock_code" :to="{ name: 'stock-detail', params: { code: row.stock_code } }" class="app-table-field-link app-interaction-link app-interaction-link--primary" @click.stop="rememberPositionStocks">{{ row.stock_name || row.stock_code }}</RouterLink>
                <span v-else>{{ row.stock_name || row.stock_code }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn prop="quantity" label="数量" />
            <AppTableColumn prop="available_quantity" label="可卖数量" />
            <AppTableColumn label="总成本" header-meta="元" role="number"><template #default="{ row }">{{ row.cost == null ? '未录入' : formatMoney(row.cost) }}</template></AppTableColumn>
            <AppTableColumn label="市值" header-meta="元" role="number"><template #default="{ row }">{{ row.market_value == null ? '暂无行情' : formatMoney(row.market_value) }}</template></AppTableColumn>
            <AppTableColumn label="浮动盈亏" header-meta="元" role="number"><template #default="{ row }"><span :class="marketValueClass(row.unrealized_pnl == null ? null : Number(row.unrealized_pnl))">{{ row.unrealized_pnl == null ? '数据不完整' : formatMoney(row.unrealized_pnl, { forceSign: true }) }}</span></template></AppTableColumn>
            <AppTableColumn prop="quote_date" label="估值日期" />
            <AppTableColumn label="所属规则" role="name"><template #default="{ row }">{{ ruleName(row.rule_id) }}</template></AppTableColumn>
          </AppDataTable>
          <p class="app-caption-text">最近日结：{{ context?.latest_trade_date || '尚未提交' }} · 现金：{{ context?.cash == null ? '未录入' : formatMoney(context.cash) }}</p>
          <el-button @click="emit('request-checkin', context?.latest_trade_date || tradeDate)">前往打卡记录成交或调整</el-button>
        </template>
        <template v-else>
          <AppStatusNotice v-if="!context?.can_edit" tone="info" title="历史记录只读。需要纠正较早记录时，请先从最新日结逐日撤回。" />
          <AppForm label-position="top" :disabled="disabled" class="ledger-checkin-form">
            <div class="ledger-entry-context">
              <AppControlRow v-if="showEntryControls">
                <AppControlItem>
                  <template #label>
                    <span class="app-body-text">操作适用规则</span>
                    <HelpHint text="一笔实际成交只记一次，履约结果由系统核对。" label="操作适用规则说明" />
                  </template>
                  <AppSelect v-model="selectedRule" aria-label="操作适用规则" :disabled="disabled" :empty-values="[null, undefined]" class="app-control-width-medium" @change="addRule">
                    <el-option v-for="rule in rules" :key="rule.rule_id" :label="rule.name" :value="rule.rule_id" />
                    <el-option label="未按任何已设规则操作" value="" />
                  </AppSelect>
                </AppControlItem>
              </AppControlRow>
              <AppControlRow v-if="showEntryControls && linkableTrades.length" data-testid="ledger-link-trade-row">
                <AppControlItem>
                  <template #label>
                    <span class="app-body-text">关联已有成交</span>
                    <HelpHint text="将其他规则下的已录成交添加到当前选择的规则，只新增规则核对，不重复记账。" label="关联已有成交说明" />
                  </template>
                  <AppSelect v-model="linkedTradeId" aria-label="选择要关联的成交" width="wide" placeholder="选择已录入股票的成交" :disabled="disabled">
                    <el-option v-for="event in linkableTrades" :key="event.event_id" :label="`${event.stock_name_snapshot || event.stock_code} · ${event.side === 'buy' ? '买入' : '卖出'}${event.operated_at ? ` · ${event.operated_at.slice(11, 19)}` : ''}`" :value="event.event_id" />
                  </AppSelect>
                </AppControlItem>
                <el-button :disabled="disabled || !linkedTradeId" @click="linkExistingTrade">添加到当前规则</el-button>
              </AppControlRow>
            </div>
            <div class="ledger-checkin-layout">
            <div class="ledger-primary">
            <section v-for="rule in activeEntryRules" :key="rule.rule_id" class="ledger-section">
              <TradeOperationEditor border-placement="panel" :section-title="rule.name" :ref="editor => setOperationEditor(rule.rule_id, editor)" :model-value="groupOperations(rule.rule_id)" :version="rule" :trade-date="tradeDate" :disabled="disabled" automatic :condition-panel-defaults="conditionPanelDefaults" @update:model-value="updateGroup(rule.rule_id, $event)" />
            </section>
            </div>
            <aside class="ledger-supplements" aria-label="遗漏与账户调整">
            <TradeDisciplineSectionPanel :show-body="omissions.length > 0" class="ledger-section" border-placement="panel" title="漏买漏卖" description="只记录应买未买、应卖未卖；实际成交违规由系统归集。">
              <template #actions><el-button v-if="!disabled && rules.length" v-permission="'trade-discipline:checkin-submit'" @click="addOmission">添加遗漏事项</el-button></template>
              <AppControlRow v-for="(item, index) in omissions" :key="index" align="start" class="ledger-entry-grid" data-testid="ledger-omission-row">
                <el-form-item label="事项" required><AppSelect v-model="item.kind"><el-option label="应买未买" value="missed_buy" /><el-option label="应卖未卖" value="missed_sell" /></AppSelect></el-form-item>
                <el-form-item label="股票" required><StockOptionSelect :model-value="stockOption(item.stock_code, item.stock_name)" :trade-date="tradeDate" :disabled="disabled" @update:model-value="item.stock_code = $event?.code ?? ''; item.stock_name = $event?.name" /></el-form-item>
                <el-form-item label="对应规则" required><AppSelect v-model="item.rule_id"><el-option v-for="rule in rules" :key="rule.rule_id" :label="rule.name" :value="rule.rule_id" /></AppSelect></el-form-item>
                <el-form-item v-if="!disabled" label="操作" class="ledger-entry-action"><el-button type="danger" plain @click="omissions.splice(index, 1)">删除</el-button></el-form-item>
              </AppControlRow>
            </TradeDisciplineSectionPanel>
            <TradeDisciplineSectionPanel :show-body="adjustments.length > 0" class="ledger-section" border-placement="panel" title="持仓与资金调整" description="转入转出、送转股、分红等非买卖变动；普通买卖在成交中记录。">
              <template #actions><el-button v-if="!disabled" @click="addAdjustment('position')">记录持仓调整</el-button><el-button v-if="!disabled" @click="addAdjustment('cash')">记录资金变动</el-button></template>
              <section v-for="(item, index) in adjustments" :key="item.event_id" class="ledger-adjustment">
                <AppControlRow justify="between" class="ledger-adjustment-head"><strong class="app-body-text">{{ item.kind === 'position' ? '持仓调整' : '资金变动' }} {{ index + 1 }}</strong><AppIconButton v-if="!disabled" :label="`删除调整 ${index + 1}`" tone="danger" @click="events = events.filter(e => e.event_id !== item.event_id)"><Delete /></AppIconButton></AppControlRow>
              <AppControlRow align="start" class="ledger-entry-grid ledger-adjustment-fields" data-testid="ledger-adjustment-row">
                <el-form-item label="实际时间" required><AppDatePicker v-model="item.operated_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" :disabled="disabled" /></el-form-item>
                <template v-if="item.kind === 'position'">
                  <el-form-item label="调整类别" required><AppSelect v-model="item.adjustment_type" @change="changePositionType(item)"><el-option label="转入转出" value="transfer" /><el-option label="送股" value="bonus" /><el-option label="拆并股" value="split" /><el-option label="核对修正" value="correction" /></AppSelect></el-form-item>
                  <el-form-item label="股票" required><StockOptionSelect :model-value="stockOption(item.stock_code, item.stock_name_snapshot)" :trade-date="tradeDate" :disabled="disabled" @update:model-value="item.stock_code = $event?.code ?? ''; item.stock_name_snapshot = $event?.name ?? ''" /></el-form-item>
                  <el-form-item v-if="item.adjustment_type !== 'bonus'" label="变动" required><AppSelect v-model="item.side" @change="item.amount = null; item.cost_price = null"><el-option label="增加" value="buy" /><el-option label="减少" value="sell" /></AppSelect></el-form-item>
                  <el-form-item label="数量" required><FixedDecimalInput v-model="item.quantity" :scale="4" :integer-digits="16" /></el-form-item>
                  <el-form-item v-if="item.side === 'buy' && !['split', 'bonus'].includes(item.adjustment_type || '')" label="成本价（元/股，选填）"><FixedDecimalInput :model-value="item.cost_price ?? null" :scale="4" :integer-digits="16" clearable @update:model-value="item.cost_price = $event; item.amount = null" /><AppFormHelp>增加总成本：{{ costTotal(item.cost_price, item.quantity, item.amount) }}。</AppFormHelp></el-form-item>
                  <el-form-item v-if="hasStockGroups" label="所属规则分组"><AppSelect :model-value="item.rule_id ? JSON.stringify([item.rule_id, item.stock_rule_id]) : ''" clearable placeholder="暂不分配" @update:model-value="item.rule_id = $event ? JSON.parse($event)[0] : null; item.stock_rule_id = $event ? JSON.parse($event)[1] : ''"><el-option-group v-for="rule in rules" :key="rule.rule_id" :label="rule.name"><el-option v-for="group in rule.stock_rules.filter(r => r.enabled)" :key="group.detail_id!" :label="`${rule.name} · ${group.name}`" :value="JSON.stringify([rule.rule_id, group.detail_id])" /></el-option-group></AppSelect></el-form-item>
                </template>
                <template v-else>
                  <el-form-item label="变动类别" required><AppSelect v-model="item.adjustment_type" @change="changeCashType(item)"><el-option label="入金" value="deposit" /><el-option label="出金" value="withdrawal" /><el-option label="分红" value="dividend" /><el-option label="其他调整" value="other" /></AppSelect></el-form-item>
                  <el-form-item v-if="item.adjustment_type === 'other'" label="方向" required><AppSelect v-model="item.direction"><el-option label="流入" value="in" /><el-option label="流出" value="out" /></AppSelect></el-form-item>
                  <el-form-item label="金额" required><FixedDecimalInput v-model="item.amount" /></el-form-item>
                  <el-form-item v-if="item.adjustment_type === 'dividend'" label="分红股票" required><StockOptionSelect :model-value="stockOption(item.stock_code, item.stock_name_snapshot)" :trade-date="tradeDate" :disabled="disabled" @update:model-value="item.stock_code = $event?.code ?? ''; item.stock_name_snapshot = $event?.name ?? ''" /></el-form-item>
                </template>
                <el-form-item label="原因" required class="ledger-entry-note"><el-input v-model="item.note" maxlength="8000" /></el-form-item>
              </AppControlRow>
                  <AppFormHelp v-if="item.adjustment_type === 'bonus'">填写增加的股数，送股不增加总成本。</AppFormHelp>
                  <AppFormHelp v-if="item.adjustment_type === 'split'">拆并股保持总成本不变，按增加或减少的股数填报；未选分组时按同股原数量分摊。</AppFormHelp>
              </section>
            </TradeDisciplineSectionPanel>
            <TradeDisciplineSectionPanel border-placement="panel" title="复盘备注" description="选填，可记录当日复盘想法。">
              <el-input v-model="reviewNote" aria-label="复盘备注（选填）" type="textarea" :rows="2" maxlength="8000" />
            </TradeDisciplineSectionPanel>
            </aside>
            </div>
          </AppForm>
          <TradeDisciplineSectionPanel v-if="shown" class="ledger-section" border-placement="panel" title="核对结果" aria-live="polite">
            <AppControlRow v-for="result in shown.evaluations" :key="result.rule_id"><strong>{{ result.rule_name }}</strong><span>{{ label(result.assessment) }}</span><span v-for="issue in [...result.issues, ...result.warnings]" :key="issue" class="app-caption-text">{{ issue }}</span></AppControlRow>
            <p v-for="item in shown.events.filter(e => e.issues?.length || e.warnings?.length)" :key="item.event_id" class="app-caption-text">{{ item.stock_name_snapshot }}：{{ [...(item.issues ?? []), ...(item.warnings ?? [])].join('；') }}</p>
          </TradeDisciplineSectionPanel>
          <AppStatusNotice v-if="previewError" tone="warning" :title="previewError" />

        </template>
      </template>
    </template>
    <template v-else>
      <el-card shadow="never" class="filter-card ledger-filter-card">
        <AppAdvancedSearch group="history" :states="{
          date: { range: true, value: historyDates, clear: () => historyDates = null,
            error: historyDates && historyDates[0] > historyDates[1] ? '开始日期不能晚于结束日期' : '' },
          rule: { value: historyRule, options: filterRuleOptions, clear: () => historyRule = '' },
          assessment: { value: historyAssessment, options: assessmentOptions, clear: () => historyAssessment = '' },
          stock: { value: historyStock?.code, summary: historyStock?.name, clear: () => historyStock = null },
          withdrawn: { value: includeWithdrawn, summary: '包含已撤回', clear: () => includeWithdrawn = false }
        }">
          <template #date><AppDatePicker v-model="historyDates" class="app-control-width-wide" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" /></template>
          <template #rule><AppFilterSelect :model-value="historyRule" class="app-control-width-medium" :options="filterRuleOptions" :multiple="false" placeholder="全部规则" @change="historyRule = String($event || '')" /></template>
          <template #assessment><AppFilterSelect :model-value="historyAssessment" class="app-control-width-short" :options="assessmentOptions" :multiple="false" placeholder="全部结果" @change="historyAssessment = String($event || '')" /></template>
          <template #stock><StockOptionSelect v-model="historyStock" class="app-control-width-long" clearable /></template>
          <template #withdrawn><el-checkbox v-model="includeWithdrawn">显示已撤回</el-checkbox></template>
          <template #commands><el-button :disabled="!historyAssessment && !historyStock && !historyRule && !historyDates && !includeWithdrawn" @click="historyAssessment = ''; historyStock = null; historyRule = ''; historyDates = null; includeWithdrawn = false">重置筛选</el-button></template>
        </AppAdvancedSearch>
      </el-card>
      <AppStateBlock v-if="historyError" state="error" title="历史加载失败" :description="historyError" retry @retry="loadHistory" />
      <AppDataTable v-else :data="history" :loading="historyBusy" :border="tableBorder" :default-sort="defaultSort" empty-text="尚无交易日记录" @sort-change="emit('sort-change', $event)">
        <AppTableColumn v-if="columnVisible('trade_date')" prop="trade_date" label="交易日" sortable="custom"><template #default="{ row }"><el-button data-button-kind="navigation" link type="primary" class="app-table-field-link" @click="openDetail(row)">{{ row.trade_date }}</el-button></template></AppTableColumn>
        <AppTableColumn v-if="columnVisible('assessment')" label="履约结果" role="status"><template #default="{ row }">{{ row.withdrawn ? '已撤回' : label(row.snapshot.assessment) }}</template></AppTableColumn>
        <AppTableColumn v-if="columnVisible('operation_count')" label="操作数" role="number"><template #default="{ row }">{{ row.snapshot.operation_count ?? row.snapshot.events.filter((e: LedgerEvent) => e.kind === 'trade').length }}</template></AppTableColumn>
        <AppTableColumn v-if="columnVisible('buy_amount')" label="买入额" role="number"><template #default="{ row }">{{ formatMoney(row.snapshot.buy_amount) }}</template></AppTableColumn>
        <AppTableColumn v-if="columnVisible('sell_amount')" label="卖出额" role="number"><template #default="{ row }">{{ formatMoney(row.snapshot.sell_amount) }}</template></AppTableColumn>
        <AppTableColumn v-if="columnVisible('peak_positions')" label="持仓峰值" role="number"><template #default="{ row }">{{ row.snapshot.peak_positions }}</template></AppTableColumn>
        <AppTableColumn v-if="columnVisible('current_revision_no')" prop="current_revision_no" label="修订" role="number" />
      </AppDataTable>

    </template>
    <template v-if="mode === 'history' || showEntryControls" #footer>
      <AppPagination v-if="mode === 'history'" :current-page="page" :page-size="pageSize" :total="total" @current-change="page = $event; loadHistory()" @size-change="page = 1; emit('page-size-change', $event)" />
      <template v-else>
        <el-button v-permission="'trade-discipline:checkin-submit'" type="primary" :loading="busy" :disabled="previewBusy || (!!context?.snapshot && !dirty())" @click="save">{{ context?.snapshot ? '提交修正' : '提交当日记录' }}</el-button>
      </template>
    </template>
    <AppDetailDrawer v-model="detailOpen" title="交易日记录" size="xxl" :subtitle="detail?.trade_date" :state="detailBusy ? 'loading' : detailError ? 'error' : 'ready'" :state-description="detailError" retry @retry="loadRevision">
      <AppStatusNotice v-if="detail?.withdrawn" tone="info" title="该日结已撤回，仅供追溯，不参与持仓及统计。" />
      <AppControlRow><span>{{ label(detailSnapshot?.assessment) }}</span><AppSelect v-model="revisionNo" class="app-control-width-short" @change="loadRevision"><el-option v-for="n in detail?.current_revision_no ?? 0" :key="n" :label="`r${n}`" :value="n" /></AppSelect><el-button v-if="canSubmit && !detail?.withdrawn && detail?.trade_date === context?.latest_trade_date && revisionNo === detail?.current_revision_no" @click="detailOpen = false; emit('request-checkin', detail!.trade_date)">前往修正最新记录</el-button></AppControlRow>
      <AppDataTable :data="detailSnapshot?.events ?? []" embedded>
        <AppTableColumn label="实际时间"><template #default="{ row }">{{ formatDateTimeSeconds(row.operated_at) }}</template></AppTableColumn>
        <AppTableColumn prop="stock_name_snapshot" label="股票" />
        <AppTableColumn label="变动类型" role="status"><template #default="{ row }">{{ row.kind === 'cash' ? row.direction === 'in' ? '资金流入' : '资金流出' : `${row.kind === 'position' ? '持仓调整·' : ''}${row.side === 'buy' ? '买入' : '卖出'}` }}</template></AppTableColumn>
        <AppTableColumn prop="quantity" label="数量" />
        <AppTableColumn prop="amount" label="金额" />
        <AppTableColumn prop="fee" label="费用" role="number" />
        <AppTableColumn label="核对依据" role="description"><template #default="{ row }">{{ [...(row.issues ?? []), ...(row.warnings ?? [])].join('；') || '无偏差' }}</template></AppTableColumn>
      </AppDataTable>
      <p v-for="(item, index) in detailSnapshot?.omissions ?? []" :key="index">{{ item.kind === 'missed_buy' ? '应买未买' : '应卖未卖' }}：{{ item.stock_name || item.stock_code }}</p>
      <p>{{ detailSnapshot?.review_note }}</p>
      <el-collapse v-model="detailRuleIds">
        <el-collapse-item v-for="rule in detailSnapshot?.rules ?? []" :key="rule.rule_id" :name="rule.rule_id">
          <template #title><span>{{ rule.name }} · v{{ rule.version_no }}</span></template>
          <p>资金预算 {{ formatMoney(rule.capital) }} · 持股上限 {{ rule.max_positions ?? '不限' }}</p>
          <p v-for="stockRule in rule.stock_rules" :key="stockRule.detail_id!">{{ stockRule.name }}：{{ stockRule.content }} {{ stockRule.checklist_items?.map(i => i.text).join('；') }}</p>
          <p v-for="actionRule in rule.action_rules" :key="actionRule.detail_id!">{{ actionRule.name }}：{{ actionRule.content }}</p>
          <TradeOperationEditor v-if="detailRuleIds.includes(rule.rule_id) && detailSnapshot" :model-value="operationsForRule(detailSnapshot.events, rule.rule_id)" :version="rule" :trade-date="detailSnapshot.trade_date" :condition-panel-defaults="conditionPanelDefaults" automatic disabled />
        </el-collapse-item>
      </el-collapse>
    </AppDetailDrawer>
  </AppWorkspacePane>
</template>

<style scoped>
.ledger-workspace { min-width: 0; }
.ledger-summary { flex: none; }
.ledger-filter-card { flex: none; }
.ledger-section { display: grid; gap: var(--app-space-3); }
.ledger-entry-grid { margin-bottom: var(--app-space-3); }
.ledger-checkin-form { display: grid; gap: var(--app-space-4); width: 100%; min-width: 0; }
.ledger-checkin-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--app-space-5); align-items: start; }
.ledger-primary, .ledger-supplements { display: flex; flex-direction: column; min-width: 0; gap: var(--app-space-4); }
.ledger-supplements { container: ledger-supplements / inline-size; }
.ledger-entry-context { display: grid; gap: var(--app-space-2); }
.ledger-checkin-form .ledger-section { margin-bottom: 0; }
.ledger-entry-grid > :deep(.el-form-item) { margin-bottom: 0; }
.ledger-adjustment + .ledger-adjustment { border-top: 1px solid var(--el-border-color-lighter); margin-top: var(--app-space-4); padding-top: var(--app-space-4); }
.ledger-adjustment-head { margin-bottom: var(--app-space-3); }
.ledger-entry-grid.ledger-adjustment-fields > :deep(.el-form-item:not(.ledger-entry-action)) { flex-basis: calc((100% - var(--app-space-2) * 2) / 3); }
.ledger-entry-grid.ledger-adjustment-fields > :deep(.el-form-item.ledger-entry-note) { flex-basis: 100%; }
.ledger-entry-grid > :deep(.el-form-item:not(.ledger-entry-action)) { flex: 1 1 180px; min-width: 0; }
.ledger-entry-grid > :deep(.el-form-item .el-select), .ledger-entry-grid > :deep(.el-form-item .el-date-editor), .ledger-entry-grid > :deep(.el-form-item .el-input-number) { width: 100%; }
.ledger-summary { min-width: 0; }
.ledger-opening { max-width: calc(var(--app-control-width-wide) * 4); }
.ledger-opening-head { margin-bottom: var(--app-space-5); }
.ledger-opening-head h3 { margin: 0 0 var(--app-space-2); }
.ledger-opening-head p { margin: 0; }
.ledger-opening-layout { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: var(--app-space-5); align-items: start; }
.ledger-opening-toolbar { margin-bottom: var(--app-space-3); }
.ledger-opening-empty { display: flex; flex-direction: column; align-items: center; gap: var(--app-space-2); padding: var(--app-space-5) var(--app-space-3); text-align: center; }
.ledger-opening-position + .ledger-opening-position { border-top: 1px solid var(--el-border-color-lighter); margin-top: var(--app-space-3); padding-top: var(--app-space-3); }
.ledger-opening-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: var(--app-space-4); }
.ledger-opening-fields :deep(.el-form-item) { min-width: 0; }
.ledger-opening-note { margin: var(--app-space-4) 0 0; }
.ledger-opening-confirm { margin-top: var(--app-space-5); padding-top: var(--app-space-4); border-top: 1px solid var(--el-border-color-lighter); }
.ledger-opening-confirm :deep(.el-checkbox__label) { white-space: normal; }
@container app-viewport (min-width: 1600px) {
  .ledger-checkin-layout { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
}
@container ledger-supplements (max-width: 760px) {
  .ledger-entry-grid.ledger-adjustment-fields > :deep(.el-form-item:not(.ledger-entry-action)) { flex-basis: calc((100% - var(--app-space-2)) / 2); }
  .ledger-entry-grid.ledger-adjustment-fields > :deep(.el-form-item.ledger-entry-note) { flex-basis: 100%; }
}
@container ledger-supplements (max-width: 480px) {
  .ledger-entry-grid > :deep(.el-form-item:not(.ledger-entry-action)) { flex-basis: 100%; }
}
@container app-viewport (max-width: 1180px) {
  .ledger-opening-layout { grid-template-columns: minmax(0, 1fr); }
  .ledger-entry-grid.ledger-adjustment-fields > :deep(.el-form-item:not(.ledger-entry-action)) { flex-basis: calc((100% - var(--app-space-2)) / 2); }
  .ledger-entry-grid.ledger-adjustment-fields > :deep(.el-form-item.ledger-entry-note) { flex-basis: 100%; }
}
@container app-viewport (max-width: 760px) {
  .ledger-opening-fields { grid-template-columns: minmax(0, 1fr); }
  .ledger-entry-grid.ledger-adjustment-fields > :deep(.el-form-item:not(.ledger-entry-action)) { flex-basis: 100%; }
}
</style>

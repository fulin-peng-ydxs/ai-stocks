<script setup lang="ts">
import type { StockConditionPanelDefaults } from '@/layout/configPanel'
import HelpHint from '@/components/HelpHint.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppSelect from '@/components/AppSelect.vue'
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import AppDatePicker from '@/components/AppDatePicker.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'
import BuiltinOptionRow from '@/components/BuiltinOptionRow.vue'
import TradeDisciplineSectionPanel from '@/components/trade-discipline/TradeDisciplineSectionPanel.vue'
import {
  decimalToMinorUnits,
  formatMinorUnits,
  multiplyToMinorUnits,
} from '@/utils/fixedDecimal'
import { formatMoney } from '@/utils/money'
import { operationFinancialFields, missingOperationFinancialField } from '@/utils/tradeDisciplineOperations'
import { formatDateTimeMinutes } from '@/utils/dateTime'
import { actionSubtypeLabel } from '@/utils/tradeDisciplineRuleTypes'
import {
  checkinAssessmentLabel,
  checkinAssessmentTagType,
} from '@/utils/tradeDisciplineAssessment'
import StockRuleConditionChecklist from '@/components/trade-discipline/StockRuleConditionChecklist.vue'
import FixedDecimalInput from './FixedDecimalInput.vue'
import StockOptionSelect from './StockOptionSelect.vue'
import TradeDirectionGroupGrid, {
  type TradeDirectionGroup,
} from '@/components/trade-discipline/TradeDirectionGroupGrid.vue'
import type {
  CheckinOperation,
  RuleVersionDetail,
  StockOption,
} from '@/api/tradeDiscipline'

import {
  conditionFactOptions, manualConditionFields, manualConditionDefaults, checklistDefaults, checklistMissing, checklistMissingItem, checklistCategory, type ConditionSection, type ConditionSectionsState,
  stockConditionSummary, stockConditionWarnings, stockConditionViolations, conditionFactLabel,
} from '@/utils/tradeDisciplineConditions'

const props = defineProps<{
  sectionTitle?: string
  borderPlacement?: 'body' | 'panel'
  conditionPanelDefaults?: StockConditionPanelDefaults
  modelValue: CheckinOperation[]
  version: RuleVersionDetail
  tradeDate: string
  showCompliance?: boolean
  automatic?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: CheckinOperation[]] }>()
const conditionSections = reactive<Record<string, ConditionSectionsState>>({})
watch(() => props.conditionPanelDefaults?.resetKey, () => {
  Object.keys(conditionSections).forEach(key => delete conditionSections[key])
})
const conditionRefs = new Map<string, InstanceType<typeof StockRuleConditionChecklist>>()
function conditionKey(operation: CheckinOperation, index: number) { return `${itemKey(operation, index)}:${operation.stock_rule_id}` }
function setConditionRef(operation: CheckinOperation, index: number, component: unknown) {
  const key = conditionKey(operation, index)
  if (component) conditionRefs.set(key, component as InstanceType<typeof StockRuleConditionChecklist>)
  else conditionRefs.delete(key)
}
let operationKey = 0
// 单一展开 key 保证多笔成交仍保持紧凑；新增和校验失败会主动切换到目标卡片。
const expandedOperationKey = ref<string | null>(null)
const operationGroupDefinitions: TradeDirectionGroup[] = [
  { value: 'buy', label: '买入操作', hint: '建仓与加仓成交事实', testId: 'buy-operation-group' },
  { value: 'sell', label: '卖出操作', hint: '减仓与清仓成交事实', testId: 'sell-operation-group' },
]
const operationGroups = computed(() => operationGroupDefinitions.map(group => ({
  ...group,
  hint: `${props.modelValue.filter(operation => operation.side === group.value).length} 笔 · ${group.hint}`,
})))

const stockRules = computed(() => props.version.stock_rules.filter((item) => item.enabled && item.detail_id))
function actionRules(side: 'buy' | 'sell') {
  return props.version.action_rules.filter(
    (item) => item.enabled && item.detail_id && item.action_type === side,
  )
}

function defaultOperatedAt(tradeDate: string, now = new Date()): string {
  const clock = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((value) => String(value).padStart(2, '0'))
    .join(':')
  return `${tradeDate}T${clock}`
}

function emptyOperation(order: number, side: 'buy' | 'sell'): CheckinOperation {
  const stockRule = stockRules.value.length === 1 ? stockRules.value[0] : undefined
  return {
    event_id: props.automatic ? crypto.randomUUID() : undefined,
    client_key: `operation-${Date.now()}-${++operationKey}`,
    stock_code: '', stock_name_snapshot: '', side,
    stock_rule_id: stockRule?.detail_id ?? '',
    action_rule_id: actionRules(side).length === 1 ? actionRules(side)[0].detail_id! : '',
    price: null, quantity: null, amount: null, fee: null,
    operated_at: defaultOperatedAt(props.tradeDate), note: null,
    checklist_results: checklistDefaults(stockRule, side),
    amount_mode: 'auto', action_matches: true, stock_matches: true,
    compliance_status: props.showCompliance ? 'complied' : null, ...manualConditionDefaults(stockRule, side), display_order: order,
  }
}

function itemKey(operation: CheckinOperation, index: number): string {
  return operation.client_key || operation.id || `loaded-${index}`
}

function groupedOperations(side: 'buy' | 'sell') {
  return props.modelValue
    .map((operation, index) => ({ operation, index }))
    .filter(({ operation }) => operation.side === side)
}

function cardIndex(index: number): string {
  return String(index + 1).padStart(2, '0')
}

function cardTitle(operation: CheckinOperation): string {
  return operation.stock_name_snapshot && operation.stock_code
    ? `${operation.stock_name_snapshot} ${operation.stock_code}`
    : '未选择股票'
}

function ruleName(operation: CheckinOperation, kind: 'stock' | 'action'): string {
  const rules = kind === 'stock' ? props.version.stock_rules : props.version.action_rules
  const id = kind === 'stock' ? operation.stock_rule_id : operation.action_rule_id
  const snapshot = kind === 'stock' ? operation.stock_rule_name : operation.action_rule_name
  return snapshot?.trim()
    || rules.find((rule) => rule.detail_id === id)?.name?.trim()
    || (kind === 'stock' ? '未选择选股规则' : '未选择买卖规则')
}

function selectedStockRule(operation: CheckinOperation) {
  return props.version.stock_rules.find((rule) => rule.detail_id === operation.stock_rule_id)
}

function operationActionSubtypeLabel(operation: CheckinOperation): string {
  const rule = props.version.action_rules.find((item) => item.detail_id === operation.action_rule_id)
  return actionSubtypeLabel(rule ?? {
    action_type: operation.side, action_subtype: operation.action_subtype ?? null,
  })
}

function requiredFactFields(operation: CheckinOperation) {
  const rule = selectedStockRule(operation)
  return manualConditionFields.filter((field) => rule?.[field.filter] && rule[field.filter] !== 'any')
}

function cardMeta(operation: CheckinOperation): string {
  return operation.amount === null || operation.amount === ''
    ? '成交金额未填写'
    : `成交金额 · ${formatMoney(operation.amount)}`
}

function cardPreview(operation: CheckinOperation): string {
  const operatedAt = formatDateTimeMinutes(operation.operated_at, '时间未填写')
  return `${ruleName(operation, 'stock')} · ${ruleName(operation, 'action')} · ${operatedAt}${operation.side === 'buy' && stockConditionWarnings(selectedStockRule(operation), operation).length ? ' · 条件需核对' : ''}`
}

function operationIssue(operation: CheckinOperation): string | null {
  if (!operation.stock_code || !operation.stock_name_snapshot
    || !operation.stock_rule_id || !operation.action_rule_id) return '信息未完整'
  if (checklistMissing(selectedStockRule(operation), operation)) return '选股条件待核对'
  if (operation.side === 'buy' && requiredFactFields(operation).some(field => !operation[field.key])) return '亏损/ST风险待核对'
  if (props.showCompliance && !operation.compliance_status) return '履约状态未选择'
  if (props.automatic && !operation.operated_at) return '操作时间未填写'
  const missingFinancial = missingOperationFinancialField(operation)
  if (missingFinancial) return `${missingFinancial.label}未填写`
  if (operation.operated_at && operation.operated_at.slice(0, 10) !== props.tradeDate) {
    return '日期需检查'
  }
  for (const { key, scale } of operationFinancialFields) {
    const value = operation[key]
    const units = decimalToMinorUnits(value, scale)
    if (units === null || units < 0n || (props.automatic && key !== 'fee' && units === 0n)) return '数值需检查'
  }
  return amountMismatch(operation) ? '金额不一致' : null
}

function toggle(operation: CheckinOperation, index: number): void {
  const key = itemKey(operation, index)
  expandedOperationKey.value = expandedOperationKey.value === key ? null : key
}

function expandOperation(index: number, section?: ConditionSection, itemId?: string): void {
  const operation = props.modelValue[index]
  if (!operation) return
  expandedOperationKey.value = itemKey(operation, index)
  if (section) {
    const key = conditionKey(operation, index)
    conditionSections[key] = { ...conditionSections[key], [section]: true }
    void nextTick(() => conditionRefs.get(key)?.reveal(section, itemId))
  }
}

/** 提交校验与摘要使用同一判断，主动展开出错成交；交割单金额修正只提示差异。 */
function validate(): string | null {
  for (const [index, operation] of props.modelValue.entries()) {
    const issue = operationIssue(operation)
    if (!issue || issue === '金额不一致') continue
    const missing = checklistMissingItem(selectedStockRule(operation), operation)
    expandOperation(index, missing ? checklistCategory(missing.category)
      : issue === '亏损/ST风险待核对' ? 'risk' : undefined, missing?.item_id)
    return `操作 ${index + 1}：${issue}`
  }
  return null
}

function guardCompliance(operation: CheckinOperation): CheckinOperation {
  return operation.compliance_status === 'complied'
    && stockConditionViolations(selectedStockRule(operation), operation).length
    ? { ...operation, compliance_status: 'breached' }
    : operation
}

function update(index: number, patch: Partial<CheckinOperation>): void {
  emit('update:modelValue', props.modelValue.map((item, position) => {
    if (position !== index) return item
    const next = { ...item, ...patch }
    if (props.automatic) {
      if ('amount' in patch) next.amount_mode = 'manual'
      if (next.amount_mode !== 'manual') {
        const value = multiplyToMinorUnits(next.price, next.quantity)
        next.amount = value === null ? null : formatMinorUnits(value)
      }
    }
    return guardCompliance(next)
  }))
}

function restoreAutoAmount(index: number): void {
  update(index, { amount_mode: 'auto' })
}

function updateCompliance(index: number, value: unknown): void {
  const operation = props.modelValue[index]
  if (value === 'complied' && operation && stockConditionViolations(selectedStockRule(operation), operation).length) return
  update(index, {
    compliance_status: value === 'complied' || value === 'breached' ? value : null,
  })
}

function add(side: 'buy' | 'sell'): void {
  const operation = emptyOperation(props.modelValue.length + 1, side)
  expandedOperationKey.value = itemKey(operation, props.modelValue.length)
  emit('update:modelValue', [...props.modelValue, operation])
}

function remove(index: number): void {
  const removedKey = itemKey(props.modelValue[index], index)
  if (expandedOperationKey.value === removedKey) expandedOperationKey.value = null
  emit('update:modelValue', props.modelValue
    .filter((_, position) => position !== index)
    .map((item, position) => props.automatic ? item : ({ ...item, display_order: position + 1 })))
}

function selectStock(index: number, stock: StockOption | null): void {
  const operation = props.modelValue[index]
  if (!operation || props.disabled || operation.linked) return
  if (operation.stock_code === (stock?.code ?? '')) {
    update(index, { stock_name_snapshot: stock?.name ?? '' })
    return
  }
  update(index, {
    stock_code: stock?.code ?? '',
    stock_name_snapshot: stock?.name ?? '',
    ...manualConditionDefaults(selectedStockRule(operation), operation.side), selection_facts: null,
    checklist_results: checklistDefaults(selectedStockRule(operation), operation.side),
    is_st: stock?.is_st ?? null,
    st_as_of_date: stock?.st_as_of_date ?? null,
  })
}

function selectStockRule(index: number, stockRuleId: string): void {
  const operation = props.modelValue[index]
  if (!operation || props.disabled || operation.stock_rule_id === stockRuleId) return
  update(index, withStockRule(operation, stockRuleId))
}

function withStockRule(operation: CheckinOperation, stockRuleId: string): CheckinOperation {
  const rule = props.version.stock_rules.find((item) => item.detail_id === stockRuleId)
  const defaults = manualConditionDefaults(rule, operation.side)
  // 切换规则只补未填写项，保留已确认的事实（包括“未知”），避免掩盖真实违规。
  return {
    ...operation, stock_rule_id: stockRuleId, checklist_results: checklistDefaults(rule, operation.side),
    loss_status: operation.loss_status ?? defaults.loss_status,
    st_risk_status: operation.st_risk_status ?? defaults.st_risk_status,
  }
}

function computedAmount(operation: CheckinOperation): string | null {
  const units = multiplyToMinorUnits(operation.price, operation.quantity)
  return units === null ? null : formatMoney(formatMinorUnits(units))
}

function amountMismatch(operation: CheckinOperation): boolean {
  const computed = multiplyToMinorUnits(operation.price, operation.quantity)
  const actual = decimalToMinorUnits(operation.amount)
  return computed !== null && actual !== null && computed !== actual
}

watch(() => props.version.version_no, () => {
  if (props.disabled) return
  const next = props.modelValue.map((item) => {
    const stocks = stockRules.value
    const actions = actionRules(item.side)
    const stockRuleId = stocks.some((rule) => rule.detail_id === item.stock_rule_id)
      ? item.stock_rule_id : (stocks.length === 1 ? stocks[0].detail_id! : '')
    return guardCompliance({
      ...(stockRuleId === item.stock_rule_id ? item : withStockRule(item, stockRuleId)),
      action_rule_id: actions.some((rule) => rule.detail_id === item.action_rule_id)
        ? item.action_rule_id : (actions.length === 1 ? actions[0].detail_id! : ''),
    })
  })
  emit('update:modelValue', next)
})

watch(() => props.modelValue.map(conditionKey), (keys) => {
  Object.keys(conditionSections).forEach(key => { if (!keys.includes(key)) delete conditionSections[key] })
})

watch(() => props.modelValue.map(itemKey), (keys) => {
  if (expandedOperationKey.value && !keys.includes(expandedOperationKey.value)) {
    expandedOperationKey.value = null
  }
})

defineExpose({ expandOperation, validate })
</script>

<template>
  <TradeDisciplineSectionPanel
    class="operation-editor"
    :title="sectionTitle || '操作事实'"
    :border-placement="borderPlacement"
    description="只填写实际成交；没有买卖时可直接提交。"
    data-testid="checkin-operation-section"
  >
    <TradeDirectionGroupGrid :groups="operationGroups" :columns="modelValue.length ? 1 : 2">
      <template #actions="{ group }">
        <el-button
          v-permission="'trade-discipline:checkin-submit'"
          :icon="Plus"
          size="small"
          :disabled="disabled"
          :aria-label="`添加${group.label}`"
          @click="add(group.value)"
        >添加</el-button>
      </template>
      <template #default="{ group }">
        <div v-if="groupedOperations(group.value).length" class="operation-card-list">
          <AppSummaryDisclosureCard
            v-for="({ operation, index }, groupIndex) in groupedOperations(group.value)"
            :key="itemKey(operation, index)"
            :panel-id="`operation-panel-${itemKey(operation, index)}`"
            :index-label="cardIndex(groupIndex)"
            :title="cardTitle(operation)"
            :toggle-label="`${expandedOperationKey === itemKey(operation, index) ? '收起' : '展开'}${group.label} ${groupIndex + 1}`"
            :meta="cardMeta(operation)"
            :preview="cardPreview(operation)"
            :expanded="expandedOperationKey === itemKey(operation, index)"
            toggle-test-id="operation-card-toggle"
            editor-test-id="operation-card-editor"
            data-testid="operation-card"
            @toggle="toggle(operation, index)"
          >
      <template #status>
        <div class="operation-card__status">
          <el-tag
            v-if="showCompliance && operation.compliance_status"
            :type="checkinAssessmentTagType(operation.compliance_status)"
            effect="plain"
            size="small"
          >{{ checkinAssessmentLabel(operation.compliance_status) }}</el-tag>
          <span v-if="operationIssue(operation)" class="operation-card__issue">
            {{ operationIssue(operation) }}
          </span>
        </div>
      </template>
      <template #tools>
        <div class="operation-card__tools">
          <AppIconButton
            v-permission="'trade-discipline:checkin-submit'"
            label="删除操作"
            tooltip="删除操作"
            size="sm"
            tone="danger"
            :disabled="disabled"
            @click="remove(index)"
          ><Delete /></AppIconButton>
        </div>
      </template>
      <div class="operation-form-sections">
        <section class="operation-form-section" aria-label="操作依据" data-testid="operation-context-section">
          <header>
            <h5 class="app-section-title">操作依据</h5>
            <HelpHint :text="operation.linked ? '引用同一笔已录成交，仅核对本套规则；成交数量和金额不会重复记账。' : '记录标的、执行时间及本次操作对应的纪律规则。'" label="操作依据说明" />
          </header>
          <div class="operation-grid">
            <el-form-item label="股票" required class="operation-field operation-field--stock">
              <StockOptionSelect
                :model-value="operation.stock_code ? { code: operation.stock_code, name: operation.stock_name_snapshot, board: null, industry: null, is_st: operation.is_st, st_as_of_date: operation.st_as_of_date } : null"
                :disabled="disabled || operation.linked"
                :trade-date="tradeDate"
                @update:model-value="selectStock(index, $event)"
              />
            </el-form-item>
            <el-form-item label="操作时间" :required="automatic" class="operation-field operation-field--time" :class="{ 'has-order': automatic }">
              <AppDatePicker :model-value="operation.operated_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm" :disabled="disabled || operation.linked" @update:model-value="update(index, { operated_at: $event })" />
            </el-form-item>
            <el-form-item v-if="automatic" label="同时间顺序" required class="operation-field operation-field--order">
              <el-input-number :model-value="operation.display_order" :min="1" :precision="0" :controls="false" :disabled="disabled || operation.linked" @update:model-value="update(index, { display_order: $event ?? 1 })" />
            </el-form-item>
            <el-form-item v-if="!automatic || version.rule_id" label="选股规则" required class="operation-field operation-field--rule">
              <AppSelect
                :model-value="operation.stock_rule_id"
                :disabled="disabled || !stockRules.length"
                :data-testid="`operation-stock-rule-${index}`"
                placeholder="选择规则"
                @update:model-value="selectStockRule(index, $event)"
              >
                <el-option v-for="rule in stockRules" :key="rule.detail_id!" :label="rule.name || '未命名规则'" :value="rule.detail_id!" />
              </AppSelect>
              <span v-if="!stockRules.length" class="app-body-text field-error">当前版本没有可用选股规则</span>
            </el-form-item>
            <el-form-item v-if="!automatic || version.rule_id" :label="operation.side === 'sell' ? '卖出规则' : '买入规则'" required class="operation-field operation-field--rule">
              <AppSelect
                :model-value="operation.action_rule_id"
                :disabled="disabled || !actionRules(operation.side).length"
                :data-testid="`operation-action-rule-${index}`"
                placeholder="选择规则"
                @update:model-value="update(index, { action_rule_id: $event })"
                popper-class="app-option-popper trade-operation-rule-popper"
              >
                <template #label>
                  <BuiltinOptionRow :label="ruleName(operation, 'action')" :builtin="false">
                    <el-tag type="info" size="small" effect="plain">{{ operationActionSubtypeLabel(operation) }}</el-tag>
                  </BuiltinOptionRow>
                </template>
                <el-option v-for="rule in actionRules(operation.side)" :key="rule.detail_id!" :label="rule.name || '未命名规则'" :value="rule.detail_id!">
                  <BuiltinOptionRow :label="rule.name || '未命名规则'" :builtin="false">
                    <el-tag type="info" size="small" effect="plain">{{ actionSubtypeLabel(rule) }}</el-tag>
                  </BuiltinOptionRow>
                </el-option>
              </AppSelect>
              <span v-if="!actionRules(operation.side).length" class="app-body-text field-error">当前方向没有可用买卖规则</span>
            </el-form-item>
            <el-form-item v-if="showCompliance" label="履约状态" required class="operation-field operation-field--compliance">
              <el-segmented
                :model-value="operation.compliance_status"
                :options="[{ label: '已履约', value: 'complied', disabled: stockConditionViolations(selectedStockRule(operation), operation).length > 0 }, { label: '未履约', value: 'breached' }]"
                :disabled="disabled"
                :data-testid="`operation-compliance-${index}`"
                @update:model-value="updateCompliance(index, $event)"
              />
            </el-form-item>
          </div>
        </section>

        <section v-if="automatic && version.rule_id" class="operation-form-section" aria-label="买卖规则核对" data-testid="operation-action-check-section">
          <header>
            <h5 class="app-section-title">买卖规则核对</h5>
            <HelpHint text="按实际执行情况核对所选买卖规则，默认符合。" label="买卖规则核对说明" />
          </header>
          <AppControlRow class="operation-rule-check" justify="between">
            <p class="app-body-text operation-rule-content">{{ version.action_rules.find(rule => rule.detail_id === operation.action_rule_id)?.content?.trim() || ruleName(operation, 'action') }}</p>
            <el-segmented aria-label="买卖规则核对结果" :model-value="operation.action_matches ?? true" :options="[{ label: '符合', value: true }, { label: '不符合', value: false }]" :disabled="disabled" @update:model-value="update(index, { action_matches: Boolean($event) })" />
          </AppControlRow>
        </section>

        <section v-if="operation.side === 'buy' && selectedStockRule(operation) && (!automatic || version.rule_id)" class="operation-form-section" aria-label="选股条件核对" data-testid="operation-conditions">
          <header><h5 class="app-section-title">选股条件核对</h5><HelpHint text="检查项默认符合，可按实际修改；股价按本笔成交价核对。ST按交易日逐日数据核对；亏损与ST风险按规则预填，可按实际修改。" label="选股条件核对说明" /></header>
          <StockRuleConditionChecklist :panel-defaults="conditionPanelDefaults" :ref="(component: unknown) => setConditionRef(operation, index, component)" :rule="selectedStockRule(operation)!" :operation="operation" :results="operation.checklist_results" checking :disabled="disabled"
            :open-sections="conditionSections[conditionKey(operation, index)] ?? {}" @update:open-sections="conditionSections[conditionKey(operation, index)] = $event" @update:results="update(index, { checklist_results: $event })">
            <template #risk>
          <div class="operation-grid">
            <el-form-item v-for="field in requiredFactFields(operation)" :key="field.key" :label="field.label" :required="!disabled" class="operation-field operation-field--rule">
              <AppSelect
                :model-value="operation[field.key]"
                :disabled="disabled"
                placeholder="选择事实状态"
                :data-testid="`operation-${field.key}-${index}`"
                @update:model-value="update(index, { [field.key]: $event })"
              >
                <template #label>{{ conditionFactLabel(operation[field.key]) }}</template>
                <el-option v-for="option in conditionFactOptions" :key="option.value" :label="option.label" :value="option.value" />
              </AppSelect>
              <span v-if="disabled && !operation[field.key]" class="app-body-text">{{ conditionFactLabel(operation[field.key]) }}</span>
            </el-form-item>
          </div>
            </template>
          </StockRuleConditionChecklist>
          <el-form-item v-if="automatic && selectedStockRule(operation)?.content?.trim()" label="补充选股条件核对">
            <AppControlRow class="operation-rule-check" justify="between">
              <p class="app-body-text operation-rule-content">{{ selectedStockRule(operation)?.content }}</p>
              <el-segmented aria-label="补充选股条件核对结果" :model-value="operation.stock_matches ?? true" :options="[{ label: '符合', value: true }, { label: '不符合', value: false }]" :disabled="disabled" @update:model-value="update(index, { stock_matches: Boolean($event) })" />
            </AppControlRow>
          </el-form-item>
          <ul v-if="stockConditionViolations(selectedStockRule(operation), operation).length" class="condition-warnings" role="status"><li v-for="warning in stockConditionViolations(selectedStockRule(operation), operation)" :key="warning">{{ warning }}</li></ul>
        </section>

        <section class="operation-form-section" aria-label="成交明细" data-testid="operation-trade-section">
          <header>
            <h5 class="app-section-title">成交明细</h5>
            <HelpHint :text="automatic ? '金额按价格×数量自动计算，可按交割单修正；费用可填0。' : '成交价、数量、成交金额和费用均须填写；费用可填0，系统不会覆盖手工填写值。'" label="成交明细说明" />
          </header>
          <div class="operation-grid">
            <el-form-item label="成交价" :required="!disabled" class="operation-field operation-field--amount"><FixedDecimalInput :model-value="operation.price" :scale="4" :integer-digits="16" :disabled="disabled || operation.linked" placeholder="0.0000" @update:model-value="update(index, { price: $event })" /></el-form-item>
            <el-form-item label="数量" :required="!disabled" class="operation-field operation-field--amount"><FixedDecimalInput :model-value="operation.quantity" :scale="4" :integer-digits="16" :disabled="disabled || operation.linked" placeholder="0.0000" @update:model-value="update(index, { quantity: $event })" /></el-form-item>
            <el-form-item label="成交金额" :required="!disabled" class="operation-field operation-field--amount">
              <FixedDecimalInput :model-value="operation.amount" grouped :disabled="disabled || operation.linked" @update:model-value="update(index, { amount: $event })" />
              <el-button v-if="automatic && operation.amount_mode === 'manual' && !disabled && !operation.linked" text size="small" @click="restoreAutoAmount(index)">恢复自动计算</el-button>
              <span v-if="computedAmount(operation) !== null" class="app-body-text operation-calculation" :class="{ 'field-error': amountMismatch(operation) }">
                价 × 量 = {{ computedAmount(operation) }}{{ amountMismatch(operation) ? '，与填写金额不一致' : '' }}
              </span>
            </el-form-item>
            <el-form-item label="费用" :required="!disabled" class="operation-field operation-field--amount"><FixedDecimalInput :model-value="operation.fee" grouped :disabled="disabled || operation.linked" @update:model-value="update(index, { fee: $event })" /></el-form-item>
          </div>
        </section>

        <section class="operation-form-section" aria-label="操作说明" data-testid="operation-note-section">
          <header>
            <h5 class="app-section-title">操作说明</h5>
          </header>
          <el-form-item label="补充说明" class="operation-note"><el-input :model-value="operation.note" :disabled="disabled" maxlength="500" @update:model-value="update(index, { note: $event })" /></el-form-item>
        </section>
      </div>
          </AppSummaryDisclosureCard>
        </div>
      </template>
    </TradeDirectionGroupGrid>
  </TradeDisciplineSectionPanel>
</template>

<style scoped>
.operation-editor { container: trade-operation / inline-size; }
.condition-warnings { margin: var(--app-space-2) 0; padding-left: var(--app-space-4); color: var(--el-color-warning); font-size: var(--app-font-size-body); }
.operation-card-list { display: grid; gap: var(--app-space-2); }
.operation-card__issue {
  flex: none;
  color: var(--app-warning-text);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
}
.operation-card__status { display: flex; align-items: center; gap: var(--app-space-2); }
.operation-card__tools { display: flex; justify-content: flex-end; width: 100%; }
.operation-form-sections { display: grid; }
.operation-form-section + .operation-form-section {
  margin-top: var(--app-space-4);
  padding-top: var(--app-space-4);
  border-top: 1px solid var(--el-border-color-lighter);
}
.operation-form-section > header {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-3);
}
.operation-rule-check { width: 100%; }
.operation-rule-check > .el-segmented { flex: none; }
.operation-rule-content {
  flex: 1 1 260px;
  min-width: 0;
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.operation-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  column-gap: var(--app-space-3);
}
.operation-field--stock { grid-column: span 6; }
.operation-field--rule { grid-column: span 6; }
.operation-field--amount { grid-column: span 3; }
.operation-field--time { grid-column: span 6; }
.operation-field--time.has-order { grid-column: span 4; }
.operation-field--order { grid-column: span 2; }
.operation-field--compliance { grid-column: span 6; }
.operation-grid :deep(.el-select), .operation-grid :deep(.el-input), .operation-grid :deep(.el-date-editor) { width: 100%; }
.operation-grid :deep(.el-form-item__content) { display: block; }
.operation-calculation { display: block; width: 100%; margin-top: var(--app-space-1); }
.operation-note { margin-bottom: 0; }
.field-error { display: block; margin-top: var(--app-space-1); color: var(--el-color-danger); }
@container trade-operation (max-width: 1180px) {
  .operation-field--stock, .operation-field--time { grid-column: span 12; }
  .operation-field--time.has-order, .operation-field--order { grid-column: span 6; }
  .operation-field--rule, .operation-field--amount { grid-column: span 6; }
}
@container trade-operation (max-width: 760px) {
  .operation-grid { grid-template-columns: 1fr; }
  .operation-field, .operation-note { grid-column: auto; }
  .operation-field--time.has-order, .operation-field--order { grid-column: auto; }
}
</style>

<script setup lang="ts">
import AppFormHelp from '@/components/AppFormHelp.vue'
import AppSelect from '@/components/AppSelect.vue'
import { computed, ref, watch } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import AppDatePicker from '@/components/AppDatePicker.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppSummaryDisclosureCard from '@/components/AppSummaryDisclosureCard.vue'
import BuiltinOptionRow from '@/components/BuiltinOptionRow.vue'
import TradeDisciplineSectionPanel from '@/components/trade-discipline/TradeDisciplineSectionPanel.vue'
import {
  decimalToMinorUnits,
  formatMinorUnits,
  multiplyToMinorUnits,
} from '@/utils/fixedDecimal'
import { formatMoney } from '@/utils/money'
import { formatDateTimeMinutes } from '@/utils/dateTime'
import { actionSubtypeLabel } from '@/utils/tradeDisciplineRuleTypes'
import {
  checkinAssessmentLabel,
  checkinAssessmentTagType,
} from '@/utils/tradeDisciplineAssessment'
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
  conditionFactOptions, manualConditionFields, manualConditionDefaults,
  stockConditionSummary, stockConditionWarnings, stockConditionViolations, conditionFactLabel,
} from '@/utils/tradeDisciplineConditions'

const props = defineProps<{
  modelValue: CheckinOperation[]
  version: RuleVersionDetail
  tradeDate: string
  showCompliance?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: CheckinOperation[]] }>()
let operationKey = 0
// 单一展开 key 保证多笔成交仍保持紧凑；新增和校验失败会主动切换到目标卡片。
const expandedOperationKey = ref<string | null>(null)
const operationGroups: TradeDirectionGroup[] = [
  { value: 'buy', label: '买入操作', hint: '建仓与加仓成交事实', testId: 'buy-operation-group' },
  { value: 'sell', label: '卖出操作', hint: '减仓与清仓成交事实', testId: 'sell-operation-group' },
]

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
    client_key: `operation-${Date.now()}-${++operationKey}`,
    stock_code: '', stock_name_snapshot: '', side,
    stock_rule_id: stockRule?.detail_id ?? '',
    action_rule_id: actionRules(side).length === 1 ? actionRules(side)[0].detail_id! : '',
    price: null, quantity: null, amount: null, fee: null,
    operated_at: defaultOperatedAt(props.tradeDate), note: null,
    compliance_status: null, ...manualConditionDefaults(stockRule, side), display_order: order,
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
  if (props.showCompliance && !operation.compliance_status) return '履约状态未选择'
  if (operation.operated_at && operation.operated_at.slice(0, 10) !== props.tradeDate) {
    return '日期需检查'
  }
  for (const field of ['price', 'quantity', 'amount', 'fee'] as const) {
    const value = operation[field]
    if (value === null || value === '') continue
    const units = decimalToMinorUnits(value, field === 'price' || field === 'quantity' ? 4 : 2)
    if (units === null || units < 0n) return '数值需检查'
  }
  return amountMismatch(operation) ? '金额不一致' : null
}

function toggle(operation: CheckinOperation, index: number): void {
  const key = itemKey(operation, index)
  expandedOperationKey.value = expandedOperationKey.value === key ? null : key
}

function expandOperation(index: number): void {
  const operation = props.modelValue[index]
  if (operation) expandedOperationKey.value = itemKey(operation, index)
}

function update(index: number, patch: Partial<CheckinOperation>): void {
  const next = props.modelValue.map((item, position) => position === index ? { ...item, ...patch } : item)
  emit('update:modelValue', next)
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
    .map((item, position) => ({ ...item, display_order: position + 1 })))
}

function selectStock(index: number, stock: StockOption | null): void {
  const operation = props.modelValue[index]
  if (!operation || props.disabled) return
  if (operation.stock_code === (stock?.code ?? '')) {
    update(index, { stock_name_snapshot: stock?.name ?? '' })
    return
  }
  update(index, {
    stock_code: stock?.code ?? '',
    stock_name_snapshot: stock?.name ?? '',
    ...manualConditionDefaults(selectedStockRule(operation), operation.side), selection_facts: null,
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
    ...operation, stock_rule_id: stockRuleId,
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
    return {
      ...(stockRuleId === item.stock_rule_id ? item : withStockRule(item, stockRuleId)),
      action_rule_id: actions.some((rule) => rule.detail_id === item.action_rule_id)
        ? item.action_rule_id : (actions.length === 1 ? actions[0].detail_id! : ''),
    }
  })
  emit('update:modelValue', next)
})

watch(() => props.modelValue.map(itemKey), (keys) => {
  if (expandedOperationKey.value && !keys.includes(expandedOperationKey.value)) {
    expandedOperationKey.value = null
  }
})

defineExpose({ expandOperation })
</script>

<template>
  <TradeDisciplineSectionPanel
    class="operation-editor"
    title="操作事实"
    description="按方向分组记录成交；规则关联以本次打卡绑定的版本为准。"
    data-testid="checkin-operation-section"
  >
    <TradeDirectionGroupGrid :groups="operationGroups">
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
        <AppStateBlock
          v-if="!groupedOperations(group.value).length"
          state="empty"
          size="tiny"
          :title="`尚未添加${group.label}`"
        />
        <div v-else class="operation-card-list">
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
            <p>记录标的、执行时间及本次操作对应的纪律规则。</p>
          </header>
          <div class="operation-grid">
            <el-form-item label="股票" required class="operation-field operation-field--stock">
              <StockOptionSelect
                :model-value="operation.stock_code ? { code: operation.stock_code, name: operation.stock_name_snapshot, board: null, industry: null, is_st: operation.is_st, st_as_of_date: operation.st_as_of_date } : null"
                :disabled="disabled"
                :trade-date="tradeDate"
                @update:model-value="selectStock(index, $event)"
              />
            </el-form-item>
            <el-form-item label="操作时间" class="operation-field operation-field--time">
              <AppDatePicker :model-value="operation.operated_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm" :disabled="disabled" @update:model-value="update(index, { operated_at: $event })" />
            </el-form-item>
            <el-form-item label="选股规则" required class="operation-field operation-field--rule">
              <AppSelect
                :model-value="operation.stock_rule_id"
                :disabled="disabled || !stockRules.length"
                :data-testid="`operation-stock-rule-${index}`"
                placeholder="选择规则"
                @update:model-value="selectStockRule(index, $event)"
              >
                <el-option v-for="rule in stockRules" :key="rule.detail_id!" :label="rule.name || '未命名规则'" :value="rule.detail_id!" />
              </AppSelect>
              <small v-if="!stockRules.length" class="field-error">当前版本没有可用选股规则</small>
            </el-form-item>
            <el-form-item :label="operation.side === 'sell' ? '卖出规则' : '买入规则'" required class="operation-field operation-field--rule">
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
              <small v-if="!actionRules(operation.side).length" class="field-error">当前方向没有可用买卖规则</small>
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

        <section v-if="operation.side === 'buy' && selectedStockRule(operation)" class="operation-form-section" aria-label="选股条件核对" data-testid="operation-conditions">
          <header><h5 class="app-section-title">选股条件核对</h5><p>{{ stockConditionSummary(selectedStockRule(operation)) }}；股价按本笔成交价核对。</p></header>
          <div class="operation-grid">
            <el-form-item v-for="field in requiredFactFields(operation)" :key="field.key" :label="field.label" :required="!disabled" class="operation-field operation-field--rule">
              <AppSelect
                :model-value="operation[field.key]"
                :disabled="disabled"
                placeholder="选择事实状态"
                :data-testid="`operation-${field.key}-${index}`"
                @update:model-value="update(index, { [field.key]: $event })"
              >
                <el-option v-for="option in conditionFactOptions" :key="option.value" :label="option.label" :value="option.value" />
              </AppSelect>
              <small v-if="disabled && !operation[field.key]" class="app-caption-text">{{ conditionFactLabel(operation[field.key]) }}</small>
            </el-form-item>
          </div>
          <AppFormHelp>ST按交易日逐日数据核对；亏损与ST风险按规则预填，可按实际修改，未查明选未知。</AppFormHelp>
          <ul v-if="stockConditionWarnings(selectedStockRule(operation), operation).length" class="condition-warnings" role="status"><li v-for="warning in stockConditionWarnings(selectedStockRule(operation), operation)" :key="warning">{{ warning }}</li></ul>
        </section>

        <section class="operation-form-section" aria-label="成交明细" data-testid="operation-trade-section">
          <header>
            <h5 class="app-section-title">成交明细</h5>
            <p>价格、数量、金额和费用均为可选事实，系统不会覆盖手工填写值。</p>
          </header>
          <div class="operation-grid">
            <el-form-item label="成交价" class="operation-field operation-field--amount"><FixedDecimalInput :model-value="operation.price" :scale="4" :integer-digits="16" :disabled="disabled" placeholder="0.0000" @update:model-value="update(index, { price: $event })" /></el-form-item>
            <el-form-item label="数量" class="operation-field operation-field--amount"><FixedDecimalInput :model-value="operation.quantity" :scale="4" :integer-digits="16" :disabled="disabled" placeholder="0.0000" @update:model-value="update(index, { quantity: $event })" /></el-form-item>
            <el-form-item label="成交金额" class="operation-field operation-field--amount">
              <FixedDecimalInput :model-value="operation.amount" grouped :disabled="disabled" @update:model-value="update(index, { amount: $event })" />
              <small v-if="computedAmount(operation) !== null" :class="{ 'field-error': amountMismatch(operation) }">
                价 × 量 = {{ computedAmount(operation) }}{{ amountMismatch(operation) ? '，与填写金额不一致' : '' }}
              </small>
            </el-form-item>
            <el-form-item label="费用" class="operation-field operation-field--amount"><FixedDecimalInput :model-value="operation.fee" grouped :disabled="disabled" @update:model-value="update(index, { fee: $event })" /></el-form-item>
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
.condition-warnings { margin: var(--app-space-2) 0; padding-left: var(--app-space-4); color: var(--el-color-warning); font-size: var(--app-font-size-caption); }
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
.operation-form-section > header { margin-bottom: var(--app-space-3); }

.operation-form-section p {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
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
.operation-field--compliance { grid-column: span 6; }
.operation-grid :deep(.el-select), .operation-grid :deep(.el-input), .operation-grid :deep(.el-date-editor) { width: 100%; }
.operation-grid :deep(.el-form-item__content) { display: block; }
.operation-note { margin-bottom: 0; }
.field-error { display: block; margin-top: var(--app-space-1); color: var(--el-color-danger); }
@container app-viewport (max-width: 1180px) {
  .operation-field--stock, .operation-field--time { grid-column: span 12; }
  .operation-field--rule, .operation-field--amount { grid-column: span 6; }
}
@container app-viewport (max-width: 760px) {
  .operation-grid { grid-template-columns: 1fr; }
  .operation-field, .operation-note { grid-column: auto; }
}
</style>

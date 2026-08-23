<script setup lang="ts">
import { computed, watch } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import { decimalToMinorUnits, formatMinorUnits, multiplyToMinorUnits } from '@/utils/fixedDecimal'
import FixedDecimalInput from './FixedDecimalInput.vue'
import StockOptionSelect from './StockOptionSelect.vue'
import type {
  CheckinOperation,
  RuleVersionDetail,
  StockOption,
} from '@/api/tradeDiscipline'

const props = defineProps<{
  modelValue: CheckinOperation[]
  version: RuleVersionDetail
  tradeDate: string
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: CheckinOperation[]] }>()
let operationKey = 0

const stockRules = computed(() => props.version.stock_rules.filter((item) => item.enabled && item.detail_id))
function actionRules(side: 'buy' | 'sell') {
  return props.version.action_rules.filter(
    (item) => item.enabled && item.detail_id && item.action_type === side,
  )
}

function emptyOperation(order: number): CheckinOperation {
  return {
    client_key: `operation-${Date.now()}-${++operationKey}`,
    stock_code: '', stock_name_snapshot: '', side: 'buy',
    stock_rule_id: stockRules.value.length === 1 ? stockRules.value[0].detail_id! : '',
    action_rule_id: actionRules('buy').length === 1 ? actionRules('buy')[0].detail_id! : '',
    price: null, quantity: null, amount: null, fee: null,
    operated_at: null, note: null, display_order: order,
  }
}

function update(index: number, patch: Partial<CheckinOperation>): void {
  const next = props.modelValue.map((item, position) => position === index ? { ...item, ...patch } : item)
  emit('update:modelValue', next)
}

function add(): void {
  emit('update:modelValue', [...props.modelValue, emptyOperation(props.modelValue.length + 1)])
}

function remove(index: number): void {
  emit('update:modelValue', props.modelValue
    .filter((_, position) => position !== index)
    .map((item, position) => ({ ...item, display_order: position + 1 })))
}

function selectStock(index: number, stock: StockOption | null): void {
  update(index, {
    stock_code: stock?.code ?? '',
    stock_name_snapshot: stock?.name ?? '',
  })
}

function changeSide(index: number, side: 'buy' | 'sell'): void {
  const candidates = actionRules(side)
  update(index, {
    side,
    action_rule_id: candidates.length === 1 ? candidates[0].detail_id! : '',
  })
}

function computedAmount(operation: CheckinOperation): string | null {
  const units = multiplyToMinorUnits(operation.price, operation.quantity)
  return units === null ? null : formatMinorUnits(units)
}

function amountMismatch(operation: CheckinOperation): boolean {
  const computed = multiplyToMinorUnits(operation.price, operation.quantity)
  const actual = decimalToMinorUnits(operation.amount)
  return computed !== null && actual !== null && computed !== actual
}

watch(() => props.version.version_no, () => {
  const next = props.modelValue.map((item) => {
    const stocks = stockRules.value
    const actions = actionRules(item.side)
    return {
      ...item,
      stock_rule_id: stocks.some((rule) => rule.detail_id === item.stock_rule_id)
        ? item.stock_rule_id : (stocks.length === 1 ? stocks[0].detail_id! : ''),
      action_rule_id: actions.some((rule) => rule.detail_id === item.action_rule_id)
        ? item.action_rule_id : (actions.length === 1 ? actions[0].detail_id! : ''),
    }
  })
  emit('update:modelValue', next)
})
</script>

<template>
  <div class="operation-editor">
    <div class="operation-editor__head">
      <div>
        <h4>操作事实</h4>
        <p class="app-caption-text">同一股票可记录多笔；规则关联以本次打卡绑定的版本为准。</p>
      </div>
      <el-button
        v-permission="'trade-discipline:checkin-submit'"
        :icon="Plus"
        :disabled="disabled"
        @click="add"
      >添加操作</el-button>
    </div>

    <div v-if="!modelValue.length" class="operation-empty app-caption-text">
      添加至少一条操作，或在上方选择“今日无操作”。
    </div>
    <article v-for="(operation, index) in modelValue" :key="operation.client_key || operation.id || `loaded-${index}`" class="operation-card">
      <div class="operation-card__head">
        <strong>操作 {{ index + 1 }}</strong>
        <AppIconButton
          v-permission="'trade-discipline:checkin-submit'"
          label="删除操作"
          :disabled="disabled"
          @click="remove(index)"
        ><Delete /></AppIconButton>
      </div>
      <div class="operation-grid">
        <el-form-item label="股票" required>
          <StockOptionSelect
            :model-value="operation.stock_code ? { code: operation.stock_code, name: operation.stock_name_snapshot, board: null, industry: null } : null"
            :disabled="disabled"
            @update:model-value="selectStock(index, $event)"
          />
        </el-form-item>
        <el-form-item label="方向" required>
          <el-segmented
            :model-value="operation.side"
            :options="[{ label: '买入', value: 'buy' }, { label: '卖出', value: 'sell' }]"
            :disabled="disabled"
            @update:model-value="changeSide(index, $event as 'buy' | 'sell')"
          />
        </el-form-item>
        <el-form-item label="选股规则" required>
          <el-select :model-value="operation.stock_rule_id" :disabled="disabled || !stockRules.length" placeholder="选择规则" @update:model-value="update(index, { stock_rule_id: $event })">
            <el-option v-for="rule in stockRules" :key="rule.detail_id!" :label="rule.name || '未命名规则'" :value="rule.detail_id!" />
          </el-select>
          <small v-if="!stockRules.length" class="field-error">当前版本没有可用选股规则</small>
        </el-form-item>
        <el-form-item label="买卖规则" required>
          <el-select :model-value="operation.action_rule_id" :disabled="disabled || !actionRules(operation.side).length" placeholder="选择规则" @update:model-value="update(index, { action_rule_id: $event })">
            <el-option v-for="rule in actionRules(operation.side)" :key="rule.detail_id!" :label="rule.name || '未命名规则'" :value="rule.detail_id!" />
          </el-select>
          <small v-if="!actionRules(operation.side).length" class="field-error">当前方向没有可用买卖规则</small>
        </el-form-item>
        <el-form-item label="成交价"><FixedDecimalInput :model-value="operation.price" :scale="4" :integer-digits="16" :disabled="disabled" placeholder="0.0000" @update:model-value="update(index, { price: $event })" /></el-form-item>
        <el-form-item label="数量"><FixedDecimalInput :model-value="operation.quantity" :scale="4" :integer-digits="16" :disabled="disabled" placeholder="0.0000" @update:model-value="update(index, { quantity: $event })" /></el-form-item>
        <el-form-item label="成交金额">
          <FixedDecimalInput :model-value="operation.amount" :disabled="disabled" @update:model-value="update(index, { amount: $event })" />
          <small v-if="computedAmount(operation) !== null" :class="{ 'field-error': amountMismatch(operation) }">
            价 × 量 = {{ computedAmount(operation) }}{{ amountMismatch(operation) ? '，与填写金额不一致' : '' }}
          </small>
        </el-form-item>
        <el-form-item label="费用"><FixedDecimalInput :model-value="operation.fee" :disabled="disabled" @update:model-value="update(index, { fee: $event })" /></el-form-item>
        <el-form-item label="操作时间">
          <el-date-picker :model-value="operation.operated_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm" :disabled="disabled" @update:model-value="update(index, { operated_at: $event })" />
        </el-form-item>
        <el-form-item label="操作说明" class="operation-note"><el-input :model-value="operation.note" :disabled="disabled" maxlength="500" @update:model-value="update(index, { note: $event })" /></el-form-item>
      </div>
    </article>
  </div>
</template>

<style scoped>
.operation-editor { display: grid; gap: var(--app-space-3); }
.operation-editor__head, .operation-card__head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--app-space-3); }
.operation-editor h4, .operation-editor p { margin: 0; }
.operation-empty { padding: var(--app-space-4); border: 1px dashed var(--el-border-color); border-radius: 8px; text-align: center; }
.operation-card { padding: var(--app-space-4); border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-blank); }
.operation-grid { margin-top: var(--app-space-3); display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); column-gap: var(--app-space-4); }
.operation-grid :deep(.el-select), .operation-grid :deep(.el-input), .operation-grid :deep(.el-date-editor) { width: 100%; }
.operation-grid :deep(.el-form-item__content) { display: block; }
.operation-note { grid-column: 1 / -1; }
.field-error { display: block; margin-top: var(--app-space-1); color: var(--el-color-danger); }
@media (max-width: 760px) { .operation-grid { grid-template-columns: 1fr; } .operation-note { grid-column: auto; } }
</style>

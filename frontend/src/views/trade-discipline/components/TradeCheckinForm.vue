<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppStateBlock from '@/components/AppStateBlock.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { getErrorMessage } from '@/utils/error'
import { decimalToMinorUnits, multiplyToMinorUnits } from '@/utils/fixedDecimal'
import TradeOperationEditor from './TradeOperationEditor.vue'
import ViolationReasonCombobox, { type ReasonValue } from './ViolationReasonCombobox.vue'
import {
  amendTradeDisciplineCheckin,
  getTradeDisciplineCheckinContext,
  submitTradeDisciplineCheckin,
  type CheckinContentPayload,
  type CheckinOperation,
  type CheckinContext,
  type CheckinAssessment,
} from '@/api/tradeDiscipline'

const props = defineProps<{
  ruleId: string
  tradeDate: string
  canSubmit: boolean
}>()
const emit = defineEmits<{
  'request-date-change': [tradeDate: string]
  submitted: []
}>()

interface CheckinFormState {
  assessment: CheckinAssessment
  no_operation: boolean
  reason: ReasonValue | null
  violation_detail: string
  review_note: string
  operations: CheckinOperation[]
}

const loading = ref(false)
const submitting = ref(false)
const loadError = ref('')
const context = ref<CheckinContext | null>(null)
const editing = ref(false)
const baseline = ref('')
const operationEditor = ref<InstanceType<typeof TradeOperationEditor> | null>(null)
let loadSeq = 0
const form = reactive<CheckinFormState>({
  assessment: 'complied', no_operation: false, reason: null,
  violation_detail: '', review_note: '', operations: [],
})

const existing = computed(() => context.value?.checkin ?? null)
const readonly = computed(() => !props.canSubmit || (!!existing.value && !editing.value))
const statusText = computed(() => existing.value
  ? `${existing.value.checkin_status === 'amended' ? '已修正' : '已提交'} · r${existing.value.current_revision_no}`
  : '尚未提交')
const amendmentUnchanged = computed(() => !!existing.value && editing.value && !isDirty())

function reasonFromContext(value: CheckinContext['checkin']): ReasonValue | null {
  if (!value?.reason_name_snapshot) return null
  if (value.reason_code) return { kind: 'builtin', code: value.reason_code, name: value.reason_name_snapshot }
  if (value.reason_id) return { kind: 'custom', id: value.reason_id, name: value.reason_name_snapshot }
  return { kind: 'text', name: value.reason_name_snapshot }
}

function snapshot(): string {
  return JSON.stringify({
    assessment: form.assessment,
    no_operation: form.no_operation,
    reason: form.reason,
    violation_detail: form.violation_detail,
    review_note: form.review_note,
    operations: form.operations,
  })
}

function applyContext(value: CheckinContext): void {
  const checkin = value.checkin
  form.assessment = checkin?.assessment ?? 'complied'
  form.no_operation = checkin?.no_operation ?? false
  form.reason = reasonFromContext(checkin)
  form.violation_detail = checkin?.violation_detail ?? ''
  form.review_note = checkin?.review_note ?? ''
  form.operations = (checkin?.operations ?? []).map((item, index) => ({
    ...item,
    client_key: `loaded-${checkin?.checkin_id}-${checkin?.current_revision_no}-${index}`,
    display_order: index + 1,
    operated_at: item.operated_at ? item.operated_at.slice(0, 19) : null,
  }))
  editing.value = !checkin && props.canSubmit
  baseline.value = snapshot()
}

async function load(): Promise<void> {
  if (!props.ruleId || !props.tradeDate) return
  const seq = ++loadSeq
  loading.value = true
  loadError.value = ''
  try {
    const result = await getTradeDisciplineCheckinContext(props.ruleId, props.tradeDate)
    if (seq !== loadSeq) return
    context.value = result
    applyContext(result)
  } catch (error) {
    if (seq !== loadSeq) return
    context.value = null
    loadError.value = getErrorMessage(error, '打卡上下文加载失败')
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

async function toggleNoOperation(value: boolean): Promise<void> {
  if (value && form.operations.length) {
    try {
      await ElMessageBox.confirm('选择“今日无操作”会清空已填写的操作记录。', '清空操作记录？', {
        confirmButtonText: '清空并继续', cancelButtonText: '取消', type: 'warning',
      })
    } catch { return }
    form.operations = []
  }
  form.no_operation = value
}

function validate(): string | null {
  if (!form.no_operation && !form.operations.length) return '请添加至少一条操作，或选择“今日无操作”'
  if (form.assessment === 'breached' && !form.reason) return '未履约时必须选择或输入一个原因'
  if (form.assessment === 'breached' && !form.violation_detail.trim()) return '未履约时必须填写详细说明'
  for (const [index, operation] of form.operations.entries()) {
    const prefix = `操作 ${index + 1}`
    const operationError = (message: string) => {
      operationEditor.value?.expandOperation(index)
      return `${prefix}：${message}`
    }
    if (!operation.stock_code || !operation.stock_name_snapshot) return operationError('请选择股票')
    if (!operation.stock_rule_id) return operationError('请选择选股规则')
    if (!operation.action_rule_id) return operationError('请选择买卖规则')
    if (operation.operated_at && operation.operated_at.slice(0, 10) !== props.tradeDate) {
      return operationError('操作时间必须属于当前交易日')
    }
    for (const field of ['price', 'quantity', 'amount', 'fee'] as const) {
      const value = operation[field]
      if (value === null || value === '') continue
      const units = decimalToMinorUnits(value, field === 'price' || field === 'quantity' ? 4 : 2)
      if (units === null) return operationError('金额与数量格式不正确')
      if (units < 0n) return operationError('金额与数量不能为负数')
    }
  }
  return null
}

function amountMismatchRows(): number[] {
  return form.operations.flatMap((operation, index) => {
    if (operation.price === null || operation.quantity === null || operation.amount === null) return []
    const calculated = multiplyToMinorUnits(operation.price, operation.quantity)
    const actual = decimalToMinorUnits(operation.amount)
    return calculated !== null && actual !== null && calculated !== actual ? [index + 1] : []
  })
}

function payload(): CheckinContentPayload {
  const breached = form.assessment === 'breached'
  return {
    assessment: form.assessment,
    no_operation: form.no_operation,
    reason_code: breached && form.reason?.kind === 'builtin' ? form.reason.code ?? null : null,
    reason_id: breached && form.reason?.kind === 'custom' ? form.reason.id ?? null : null,
    reason_text: breached && form.reason?.kind === 'text' ? form.reason.name.trim() : null,
    violation_detail: breached ? form.violation_detail.trim() : null,
    review_note: form.review_note.trim() || null,
    operations: form.operations.map((item, index) => ({
      // 操作属于修订快照，不能复用上一修订的全局主键；null 交由服务端生成新 ID。
      id: null,
      stock_code: item.stock_code,
      stock_name_snapshot: item.stock_name_snapshot,
      side: item.side,
      stock_rule_id: item.stock_rule_id,
      action_rule_id: item.action_rule_id,
      price: item.price,
      quantity: item.quantity,
      amount: item.amount,
      fee: item.fee,
      operated_at: item.operated_at,
      note: item.note,
      display_order: index + 1,
    })),
  }
}

async function submit(): Promise<void> {
  if (!props.canSubmit || readonly.value || submitting.value) return
  if (existing.value && !isDirty()) return
  const invalid = validate()
  if (invalid) {
    ElMessage.warning(invalid)
    return
  }
  const mismatches = amountMismatchRows()
  if (mismatches.length) {
    try {
      await ElMessageBox.confirm(
        `操作 ${mismatches.join('、')} 的成交金额与“成交价 × 数量”不一致，仍要提交吗？`,
        '确认成交金额',
        { confirmButtonText: '仍然提交', cancelButtonText: '返回检查', type: 'warning' },
      )
    } catch { return }
  }
  submitting.value = true
  try {
    const content = payload()
    if (existing.value) {
      await amendTradeDisciplineCheckin(existing.value.checkin_id, {
        ...content, expected_revision: existing.value.current_revision_no,
      })
      ElMessage.success('打卡已修正')
    } else {
      await submitTradeDisciplineCheckin({ ...content, rule_id: props.ruleId, trade_date: props.tradeDate })
      ElMessage.success('打卡已提交')
    }
    await load()
    emit('submitted')
  } catch { /* 统一请求层已反馈，表单保留 */ }
  finally { submitting.value = false }
}

async function startAmend(): Promise<boolean> {
  if (!props.canSubmit) return false
  // 历史页跳转时组件可能刚挂载；等待最新上下文，避免加载完成后覆盖编辑态。
  await load()
  if (!existing.value) return false
  editing.value = true
  return true
}

function enterEditing(): void {
  if (props.canSubmit && existing.value) editing.value = true
}

function cancelAmend(): void {
  if (!existing.value || !context.value) return
  applyContext(context.value)
}

function isDirty(): boolean {
  return editing.value && snapshot() !== baseline.value
}

async function requestLeave(): Promise<boolean> {
  if (!isDirty()) return true
  try {
    await ElMessageBox.confirm('当前打卡尚未提交，离开会丢失本次修改。', '放弃未提交修改？', {
      confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning',
      closeOnClickModal: false, closeOnPressEscape: false, showClose: false,
    })
    if (context.value) applyContext(context.value)
    return true
  } catch { return false }
}

function requestDateChange(value: string | null): void {
  if (value && value !== props.tradeDate) emit('request-date-change', value)
}

watch(() => [props.ruleId, props.tradeDate] as const, load, { immediate: true })
defineExpose({ isDirty, requestLeave, load, startAmend })
</script>

<template>
  <div class="checkin-detail panel-detail" data-testid="checkin-form">
    <AppStateBlock v-if="loading" state="loading" title="正在加载打卡上下文…" />
    <AppStateBlock v-else-if="loadError" state="error" title="打卡上下文不可用" :description="loadError" retry @retry="load" />
    <template v-else-if="context">
      <div class="checkin-head">
        <div>
          <div class="detail-kicker" data-testid="checkin-version-kicker">
            履约版本 v{{ context.version.version_no }}
          </div>
          <h3 class="app-section-title">{{ context.version.name }}</h3>
        </div>
        <div class="checkin-head__facts">
          <TradeDatePicker :model-value="tradeDate" @update:model-value="requestDateChange" />
          <el-tag :type="existing ? 'success' : 'info'" effect="plain">{{ statusText }}</el-tag>
        </div>
      </div>

      <div v-if="!canSubmit" class="permission-note">当前账号仅可查看，不能提交或修正打卡。</div>
      <el-form label-position="top" class="checkin-form">
        <section class="checkin-section">
          <div class="assessment-row">
            <el-form-item label="履约自评" required>
              <el-segmented
                data-testid="checkin-assessment"
                v-model="form.assessment"
                :disabled="readonly"
                :options="[{ label: '已履约', value: 'complied' }, { label: '未履约', value: 'breached' }]"
              />
            </el-form-item>
            <el-checkbox data-testid="checkin-no-operation" :model-value="form.no_operation" :disabled="readonly" @change="toggleNoOperation(Boolean($event))">今日无操作</el-checkbox>
          </div>
          <div v-if="form.assessment === 'breached'" class="breach-grid">
            <el-form-item label="未履约原因" required>
              <ViolationReasonCombobox v-model="form.reason" data-testid="checkin-reason" :disabled="readonly" />
            </el-form-item>
            <el-form-item label="详细说明" required>
              <el-input v-model="form.violation_detail" data-testid="checkin-violation-detail" type="textarea" :rows="3" maxlength="1000" show-word-limit :disabled="readonly" />
            </el-form-item>
          </div>
          <el-form-item label="复盘说明">
            <el-input v-model="form.review_note" data-testid="checkin-review-note" type="textarea" :rows="2" maxlength="1000" show-word-limit :disabled="readonly" />
          </el-form-item>
        </section>

        <TradeOperationEditor
          v-if="!form.no_operation"
          ref="operationEditor"
          v-model="form.operations"
          :version="context.version"
          :trade-date="tradeDate"
          :disabled="readonly"
        />

        <div class="checkin-actions">
          <el-button
            v-if="existing && !editing && canSubmit"
            v-permission="'trade-discipline:checkin-submit'"
            @click="enterEditing"
          >修正打卡</el-button>
          <template v-else-if="canSubmit">
            <span
              v-if="amendmentUnchanged"
              id="checkin-amend-unchanged-hint"
              class="checkin-actions__hint"
              role="status"
            >当前内容与最新修订一致；修改后才可提交</span>
            <el-button
              v-if="existing"
              v-permission="'trade-discipline:checkin-submit'"
              :disabled="submitting"
              @click="cancelAmend"
            >取消修正</el-button>
            <el-button
              v-permission="'trade-discipline:checkin-submit'"
              type="primary"
              :loading="submitting"
              :disabled="amendmentUnchanged"
              :aria-describedby="amendmentUnchanged ? 'checkin-amend-unchanged-hint' : undefined"
              @click="submit"
            >{{ existing ? '提交修正' : '提交打卡' }}</el-button>
          </template>
        </div>
      </el-form>
    </template>
  </div>
</template>

<style scoped>
.checkin-detail { display: block; }
.checkin-head, .checkin-head__facts, .assessment-row, .checkin-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); }
.checkin-head { align-items: flex-start; padding-bottom: var(--app-space-3); border-bottom: 1px solid var(--el-border-color-lighter); }
.checkin-head .app-section-title { margin: var(--app-space-1) 0 0; }
.checkin-form { margin-top: var(--app-space-4); display: grid; gap: var(--app-space-4); }
.checkin-section { padding: var(--app-space-4); border: 1px solid var(--el-border-color-lighter); border-radius: var(--layout-card-radius); }
.assessment-row { align-items: flex-start; }
.breach-grid { display: grid; grid-template-columns: minmax(220px, 0.7fr) minmax(320px, 1.3fr); gap: var(--app-space-4); }
.permission-note {
  margin-top: var(--app-space-3);
  padding: var(--app-space-2) var(--app-space-3);
  border-left: 3px solid var(--el-color-primary);
  background: transparent;
  color: var(--el-text-color-secondary);
}
.checkin-actions { justify-content: flex-end; position: sticky; bottom: 0; padding: var(--app-space-3) 0 0; background: var(--el-bg-color); }
.checkin-actions__hint { margin-right: auto; color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
@media (max-width: 760px) {
  .checkin-head, .checkin-head__facts, .assessment-row { align-items: stretch; flex-direction: column; }
  .breach-grid { grid-template-columns: 1fr; }
}
</style>

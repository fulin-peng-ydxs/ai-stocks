<script setup lang="ts">
import { formatNumber } from '@/utils/numberFormat'
import AppControlRow from '@/components/AppControlRow.vue'
import AppForm from '@/components/AppForm.vue'
import type { StockConditionPanelDefaults } from '@/layout/configPanel'
import AppFormHelp from '@/components/AppFormHelp.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppScrollArea from '@/components/AppScrollArea.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import TradeDisciplineSectionPanel from '@/components/trade-discipline/TradeDisciplineSectionPanel.vue'
import { getErrorMessage } from '@/utils/error'
import { holdingCountWarning, manualConditionFields, stockConditionViolations, checklistMissingItem, checklistCategory, conditionViolationTarget, type ConditionSection } from '@/utils/tradeDisciplineConditions'
import { decimalToMinorUnits, multiplyToMinorUnits } from '@/utils/fixedDecimal'
import { operationFinancialFields, missingOperationFinancialField } from '@/utils/tradeDisciplineOperations'
import {
  checkinAssessmentOptions,
  checkinAssessmentGuides,
  partialAssessmentIssue,
  checkinViolationItemOptions,
  checkinViolationItemsText,
  hasCheckinViolation,
} from '@/utils/tradeDisciplineAssessment'
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
  type CheckinViolationItem,
} from '@/api/tradeDiscipline'

const props = defineProps<{
  conditionPanelDefaults?: StockConditionPanelDefaults
  ruleId: string
  tradeDate: string
  canSubmit: boolean
}>()
const emit = defineEmits<{
  'request-date-change': [tradeDate: string]
  submitted: []
}>()

interface CheckinFormState {
  violation_items: CheckinViolationItem[] | null
  peak_positions: number | null
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
  violation_items: null, peak_positions: null, assessment: 'complied', no_operation: false, reason: null,
  violation_detail: '', review_note: '', operations: [],
})

const selectedViolationItems = computed(() => checkinViolationItemOptions
  .filter(option => form.violation_items?.includes(option.value)).map(option => option.value))
const existing = computed(() => context.value?.checkin ?? null)
const readonly = computed(() => !props.canSubmit || (!!existing.value && !editing.value))
const amendmentUnchanged = computed(() => !!existing.value && editing.value && !isDirty())
const knownViolations = computed(() => {
  const version = context.value?.version
  if (!version) return []
  const issues: string[] = []
  if (version.max_positions != null && form.peak_positions != null && form.peak_positions > version.max_positions) {
    issues.push(holdingCountWarning(version.max_positions, form.peak_positions))
  }
  form.operations.forEach((operation, index) => {
    const rule = version.stock_rules.find((item) => item.detail_id === operation.stock_rule_id)
    issues.push(...stockConditionViolations(rule, operation).map((issue) => `操作 ${index + 1}：${issue}`))
  })
  return issues
})
const partialIssue = computed(() => partialAssessmentIssue(
  form.operations, selectedViolationItems.value, knownViolations.value.length > 0,
))
const assessmentOptions = computed(() => checkinAssessmentOptions.map((option) => ({
  ...option, disabled: option.value === 'complied' && knownViolations.value.length > 0,
})))

function reasonFromContext(value: CheckinContext['checkin']): ReasonValue | null {
  if (!value?.reason_name_snapshot) return null
  if (value.reason_code) return { kind: 'builtin', code: value.reason_code, name: value.reason_name_snapshot }
  if (value.reason_id) return { kind: 'custom', id: value.reason_id, name: value.reason_name_snapshot }
  return { kind: 'text', name: value.reason_name_snapshot }
}

function snapshot(): string {
  return JSON.stringify({
    peak_positions: form.peak_positions,
    assessment: form.assessment,
    no_operation: form.no_operation,
    violation_items: form.violation_items == null ? null : selectedViolationItems.value,
    reason: form.reason,
    violation_detail: form.violation_detail,
    review_note: form.review_note,
    operations: form.operations,
  })
}

function applyContext(value: CheckinContext): void {
  const checkin = value.checkin
  // 仅首次填报默认取规则上限；历史修订的 0 或未记录状态均按原快照保留。
  form.peak_positions = checkin
    ? checkin.peak_positions ?? null
    : value.version.max_positions ?? null
  form.assessment = checkin?.assessment ?? 'complied'
  form.no_operation = checkin?.no_operation ?? false
  form.violation_items = checkin?.violation_items ? [...checkin.violation_items] : null
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
  if (form.assessment === 'partial' && value) return
  if (value && form.operations.length) {
    try {
      await ElMessageBox.confirm('选择“今日无操作”会清空已填写的操作记录。', '清空操作记录？', {
        confirmButtonType: 'danger',
        confirmButtonText: '清空并继续', cancelButtonText: '取消', type: 'warning',
      })
    } catch { return }
    form.operations = []
  }
  form.no_operation = value
}

function validate(): string | null {
  if (form.assessment === 'complied' && knownViolations.value.length) {
    form.operations.some((operation, index) => {
      const rule = context.value?.version.stock_rules.find(item => item.detail_id === operation.stock_rule_id)
      const target = conditionViolationTarget(rule, operation)
      if (target) operationEditor.value?.expandOperation(index, target.section, target.itemId)
      return !!target
    })
    return '存在规则违规，不能选择已履约'
  }
  if (context.value?.version.max_positions != null && form.peak_positions === null) return '请填写当日最大同时持仓数'
  if (form.peak_positions !== null && (!Number.isInteger(form.peak_positions) || form.peak_positions < 0 || form.peak_positions > 2147483647)) return '当日最大同时持仓数必须为非负整数'
  if (form.assessment === 'partial' && !form.operations.length) return '部分履约至少需要一条操作'
  if (!form.no_operation && !form.operations.length) return '请添加至少一条操作，或选择“今日无操作”'
  if (hasCheckinViolation(form.assessment) && form.no_operation && !form.violation_items?.length) return '未履约且今日无操作时必须选择未履约事项'
  if (hasCheckinViolation(form.assessment) && !form.reason) return '部分履约或未履约时必须选择或输入一个原因'
  if (hasCheckinViolation(form.assessment) && !form.violation_detail.trim()) return '部分履约或未履约时必须填写详细说明'
  for (const [index, operation] of form.operations.entries()) {
    const prefix = `操作 ${index + 1}`
    const operationError = (message: string, section?: ConditionSection, itemId?: string) => {
      operationEditor.value?.expandOperation(index, section, itemId)
      return `${prefix}：${message}`
    }
    if (!operation.stock_code || !operation.stock_name_snapshot) return operationError('请选择股票')
    if (!operation.stock_rule_id) return operationError('请选择选股规则')
    if (!operation.action_rule_id) return operationError('请选择买卖规则')
    const stockRule = context.value?.version.stock_rules.find((rule) => rule.detail_id === operation.stock_rule_id)
    const missing = checklistMissingItem(stockRule, operation)
    if (missing) return operationError('请逐项选择符合或不符合', checklistCategory(missing.category), missing.item_id)
    if (operation.compliance_status === 'complied' && stockConditionViolations(stockRule, operation).length) {
      const target = conditionViolationTarget(stockRule, operation)
      return operationError('存在规则违规，不能选择已履约', target?.section, target?.itemId)
    }
    if (operation.side === 'buy') {
      for (const field of manualConditionFields) {
        if (stockRule?.[field.filter] && stockRule[field.filter] !== 'any' && !operation[field.key]) return operationError(`请选择${field.label}`, 'risk')
      }
    }
    if (form.assessment === 'partial' && !operation.compliance_status) {
      return operationError('请选择履约状态')
    }
    if (operation.operated_at && operation.operated_at.slice(0, 10) !== props.tradeDate) {
      return operationError('操作时间必须属于当前交易日')
    }
    const missingFinancial = missingOperationFinancialField(operation)
    if (missingFinancial) return operationError(`请填写${missingFinancial.label}`)
    for (const { key, scale } of operationFinancialFields) {
      const value = operation[key]
      const units = decimalToMinorUnits(value, scale)
      if (units === null) return operationError('金额与数量格式不正确')
      if (units < 0n) return operationError('金额与数量不能为负数')
    }
  }
  if (form.assessment === 'partial' && partialIssue.value) return partialIssue.value
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
  const hasViolation = hasCheckinViolation(form.assessment)
  return {
    peak_positions: form.peak_positions,
    assessment: form.assessment,
    no_operation: form.no_operation,
    violation_items: hasViolation ? selectedViolationItems.value : [],
    reason_code: hasViolation && form.reason?.kind === 'builtin' ? form.reason.code ?? null : null,
    reason_id: hasViolation && form.reason?.kind === 'custom' ? form.reason.id ?? null : null,
    reason_text: hasViolation && form.reason?.kind === 'text' ? form.reason.name.trim() : null,
    violation_detail: hasViolation ? form.violation_detail.trim() : null,
    review_note: form.review_note.trim() || null,
    operations: form.operations.map((item, index) => ({
      // 操作属于修订快照，不能复用上一修订的全局主键；null 交由服务端生成新 ID。
      id: null,
      stock_code: item.stock_code,
      stock_name_snapshot: item.stock_name_snapshot,
      side: item.side,
      stock_rule_id: item.stock_rule_id,
      action_rule_id: item.action_rule_id,
      checklist_results: item.checklist_results ?? null,
      loss_status: item.loss_status ?? null,
      st_risk_status: item.st_risk_status ?? null,
      price: item.price,
      quantity: item.quantity,
      amount: item.amount,
      fee: item.fee,
      operated_at: item.operated_at,
      note: item.note,
      compliance_status: form.assessment === 'partial' ? item.compliance_status : null,
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
        { confirmButtonType: 'warning', confirmButtonText: '仍然提交', cancelButtonText: '返回检查', type: 'warning' },
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
      confirmButtonType: 'danger',
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

watch(() => form.assessment, (assessment, previous) => {
  if (assessment === 'partial') {
    form.no_operation = false
    if (!readonly.value) {
      form.operations = form.operations.map(operation => ({
        ...operation,
        compliance_status: operation.compliance_status ?? (stockConditionViolations(
          context.value?.version.stock_rules.find(rule => rule.detail_id === operation.stock_rule_id), operation,
        ).length ? 'breached' : 'complied'),
      }))
    }
    return
  }
  if (previous === 'partial') {
    form.operations = form.operations.map((operation) => ({
      ...operation,
      compliance_status: null,
    }))
  }
})
// 只调整编辑中的自评；历史只读快照保持原样，修正时再按事实校验。
watch([knownViolations, readonly], ([issues, isReadonly]) => {
  if (!isReadonly && issues.length && form.assessment === 'complied') form.assessment = 'breached'
})
watch(() => [props.ruleId, props.tradeDate] as const, load, { immediate: true })
defineExpose({ isDirty, requestLeave, load, startAmend })
</script>

<template>
  <AppScrollArea as="section" class="checkin-detail panel-detail" aria-label="打卡内容工作区" data-testid="checkin-form">
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
          <el-button
            v-if="existing && !editing && canSubmit"
            v-permission="'trade-discipline:checkin-submit'"
            type="primary"
            @click="enterEditing"
          >修正打卡</el-button>
          <div v-else-if="existing && editing && canSubmit" class="checkin-head__commands">
            <el-button
              v-permission="'trade-discipline:checkin-submit'"
              type="danger"
              plain
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
            >提交修正</el-button>
          </div>
        </div>
      </div>

      <div
        v-if="amendmentUnchanged"
        id="checkin-amend-unchanged-hint"
        class="checkin-amendment-hint"
        role="status"
      >当前内容与最新修订一致；修改后才可提交</div>

      <div v-if="!canSubmit" class="permission-note">当前账号仅可查看，不能提交或修正打卡。</div>
      <AppForm label-position="top" class="checkin-form">
        <TradeDisciplineSectionPanel
          class="checkin-section"
          title="履约判断"
          description="记录规则整体执行结果；部分履约或未履约需说明偏差，实际交易在下方单独记录。"
          data-testid="checkin-assessment-section"
        >
          <div class="assessment-row">
            <el-form-item label="履约自评" required>
              <template #label>
                履约自评
                <HelpTip title="履约自评操作说明" :width="420" test-id="checkin-assessment-help-tip">
                  <HelpTipItem v-for="option in checkinAssessmentOptions" :key="option.value" :question="option.label">
                    <ul>
                      <li>{{ checkinAssessmentGuides[option.value].summary }}</li>
                      <li v-for="detail in checkinAssessmentGuides[option.value].details" :key="detail">{{ detail }}</li>
                    </ul>
                  </HelpTipItem>
                </HelpTip>
              </template>
              <el-segmented
                data-testid="checkin-assessment"
                v-model="form.assessment"
                :disabled="readonly"
                :options="assessmentOptions"
                aria-describedby="checkin-assessment-help"
              />
              <AppFormHelp id="checkin-assessment-help">{{ checkinAssessmentGuides[form.assessment].summary }}</AppFormHelp>
            </el-form-item>
            <el-checkbox data-testid="checkin-no-operation" :model-value="form.no_operation" :disabled="readonly || form.assessment === 'partial'" @change="toggleNoOperation(Boolean($event))">今日无操作</el-checkbox>
          </div>
          <p v-if="form.assessment === 'partial' && partialIssue && !readonly" class="condition-warning" role="status" data-testid="checkin-partial-issue">{{ partialIssue }}</p>
          <p v-if="knownViolations.length && !readonly" class="condition-warning" role="status">已发现规则违规，不能选择“已履约”；请填写未履约情况或逐笔记录部分履约。</p>
          <div v-if="context.version.max_positions != null || form.peak_positions != null" class="holding-count" data-testid="checkin-holding-count">
            <el-form-item label="当日最大同时持仓数" :required="context.version.max_positions != null">
              <el-input-number v-model="form.peak_positions" :min="0" :max="2147483647" :step="1" :controls="false" :disabled="readonly" placeholder="填写实际数量" data-testid="checkin-peak-positions" />
              <AppFormHelp>本套规则上限 {{ formatNumber(context.version.max_positions, 'count', { empty: '不限' }) }} 只；填写当日峰值，包含此前持仓，同股多笔只算一只。无操作也可能仍有持仓。</AppFormHelp>
            </el-form-item>
            <p v-if="holdingCountWarning(context.version.max_positions, form.peak_positions)" class="condition-warning" role="status">{{ holdingCountWarning(context.version.max_positions, form.peak_positions) }}</p>
          </div>
          <el-form-item v-if="hasCheckinViolation(form.assessment)" label="未履约事项" :required="form.no_operation" data-testid="checkin-violation-items">
            <template v-if="readonly">{{ checkinViolationItemsText(form.violation_items) }}</template>
            <template v-else>
              <el-checkbox-group :model-value="form.violation_items ?? []" aria-label="未履约事项" @update:model-value="form.violation_items = $event as CheckinViolationItem[]">
                <el-checkbox v-for="option in checkinViolationItemOptions" :key="option.value" :value="option.value">{{ option.label }}</el-checkbox>
              </el-checkbox-group>
              <AppFormHelp>可多选；今日无操作时必填。有实际操作但仍有应买未买、应卖未卖，也可在此补充。</AppFormHelp>
              <AppFormHelp tone="warning" v-if="form.peak_positions === 0 && form.violation_items?.includes('missed_sell')" role="status">已选择应卖未卖，但当日最大同时持仓为 0，请核对持仓数量或在详细说明中解释。</AppFormHelp>
            </template>
          </el-form-item>
          <div v-if="hasCheckinViolation(form.assessment)" class="breach-grid">
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
        </TradeDisciplineSectionPanel>

        <TradeOperationEditor
          :condition-panel-defaults="conditionPanelDefaults"
          v-if="!form.no_operation"
          ref="operationEditor"
          v-model="form.operations"
          :version="context.version"
          :trade-date="tradeDate"
          :show-compliance="form.assessment === 'partial'"
          :disabled="readonly"
        />

        <AppControlRow v-if="canSubmit && !existing" class="checkin-actions">
          <el-button
            v-permission="'trade-discipline:checkin-submit'"
            type="primary"
            :loading="submitting"
            @click="submit"
          >提交打卡</el-button>
        </AppControlRow>
      </AppForm>
    </template>
  </AppScrollArea>
</template>

<style scoped>
.checkin-detail.panel-detail {
  padding: 0;
  --app-scroll-padding-top: var(--app-space-5);
  --app-scroll-padding-right: var(--app-space-5);
  --app-scroll-padding-bottom: var(--app-space-5);
  --app-scroll-padding-left: var(--app-space-5);
}
.condition-warning { color: var(--el-color-warning); font-size: var(--app-font-size-caption); }
.checkin-head, .checkin-head__facts, .checkin-head__commands, .assessment-row, .checkin-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); }
.checkin-head { align-items: flex-start; padding-bottom: var(--app-space-3); border-bottom: 1px solid var(--el-border-color-lighter); }
.checkin-head .app-section-title { margin: var(--app-space-1) 0 0; }
.checkin-form { margin-top: var(--app-space-4); display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--app-space-4); }
.assessment-row { align-items: flex-start; }
.breach-grid { display: grid; grid-template-columns: minmax(220px, 0.7fr) minmax(320px, 1.3fr); gap: var(--app-space-4); }
.permission-note {
  margin-top: var(--app-space-3);
  padding: var(--app-space-2) var(--app-space-3);
  border-left: 3px solid var(--el-color-primary);
  background: transparent;
  color: var(--el-text-color-secondary);
}
.checkin-amendment-hint {
  margin-top: var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  text-align: right;
}
.checkin-actions { justify-content: flex-end; }
@container app-viewport (max-width: 760px) {
  .checkin-head, .checkin-head__facts, .assessment-row { align-items: stretch; flex-direction: column; }
  .checkin-head__commands { justify-content: flex-end; }
  .checkin-amendment-hint { text-align: left; }
  .breach-grid { grid-template-columns: 1fr; }
}
</style>

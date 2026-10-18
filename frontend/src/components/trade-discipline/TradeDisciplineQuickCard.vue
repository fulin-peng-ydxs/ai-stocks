<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppDialog from '@/components/AppDialog.vue'
import { holdingCountWarning } from '@/utils/tradeDisciplineConditions'
import { quickNoOperationTradeDisciplineCheckin, type CheckinSummaryRule } from '@/api/tradeDiscipline'
import { useTradeDisciplineSummary } from '@/composables/useTradeDisciplineSummary'
import { getErrorMessage, getErrorStatus } from '@/utils/error'
import { checkinAssessmentLabel } from '@/utils/tradeDisciplineAssessment'

const props = defineProps<{ canSubmit: boolean; tradeDate: string }>()
const emit = defineEmits<{
  navigate: [payload: { tab: 'checkin' | 'rules'; ruleId?: string; tradeDate?: string }]
}>()

const {
  summary,
  status,
  errorMessage,
  refreshSummary,
  notifyTradeDisciplineChanged,
} = useTradeDisciplineSummary()
const submittingRuleId = ref('')
const actionErrorRuleId = ref('')
const actionErrorMessage = ref('')
const confirmationOpen = ref(false)
const pendingRule = ref<CheckinSummaryRule | null>(null)
const quickTradeDate = ref('')
const peakPositions = ref<number | null>(null)
const countError = computed(() => holdingCountWarning(pendingRule.value?.max_positions, peakPositions.value))

const completionText = computed(() => {
  if (!summary.value) return '—'
  return `${summary.value.completed}/${summary.value.total}`
})
const allCompleted = computed(() => Boolean(summary.value?.total && summary.value.pending === 0))

function ruleStatus(rule: NonNullable<typeof summary.value>['rules'][number]): string {
  if (!rule.checkin_id) return '待打卡'
  const result = checkinAssessmentLabel(rule.assessment!)
  return rule.status === 'amended' ? `${result} · 已修正` : result
}

function navigateToCheckin(ruleId?: string): void {
  emit('navigate', {
    tab: 'checkin',
    ruleId,
    tradeDate: summary.value?.trade_date,
  })
}

function openQuickConfirmation(ruleId: string): void {
  const rule = summary.value?.rules.find((item) => item.rule_id === ruleId)
  if (!props.canSubmit || !rule || !summary.value?.trade_date || submittingRuleId.value) return
  pendingRule.value = rule
  peakPositions.value = rule.max_positions ?? null
  quickTradeDate.value = summary.value.trade_date
  actionErrorRuleId.value = ''
  confirmationOpen.value = true
}

function openPendingCheckin(): void {
  confirmationOpen.value = false
  navigateToCheckin(pendingRule.value?.rule_id)
}

async function quickSubmit(): Promise<void> {
  const ruleId = pendingRule.value?.rule_id
  const tradeDate = quickTradeDate.value
  if (!props.canSubmit || !ruleId || !tradeDate || countError.value || submittingRuleId.value) return
  submittingRuleId.value = ruleId
  actionErrorRuleId.value = ''
  actionErrorMessage.value = ''
  try {
    const result = peakPositions.value == null
      ? await quickNoOperationTradeDisciplineCheckin(ruleId, tradeDate)
      : await quickNoOperationTradeDisciplineCheckin(ruleId, tradeDate, peakPositions.value)
    confirmationOpen.value = false
    notifyTradeDisciplineChanged({ ruleId, tradeDate, source: 'quick' })
    await refreshSummary(tradeDate)
    ElMessage.success(result.idempotent ? '该交易日已完成打卡' : '已记录无操作履约')
  } catch (error) {
    if (getErrorStatus(error) === 409) {
      confirmationOpen.value = false
      navigateToCheckin(ruleId)
      return
    }
    actionErrorRuleId.value = ruleId
    actionErrorMessage.value = getErrorMessage(error, '快捷打卡失败，请重试')
  } finally {
    submittingRuleId.value = ''
  }
}
</script>

<template>
  <section class="discipline-quick-card" data-testid="trade-discipline-quick-card">
    <header class="quick-head">
      <div>
        <span class="quick-kicker">今日交易纪律</span>
        <strong>{{ summary?.trade_date || tradeDate || '最新交易日' }}</strong>
      </div>
      <el-button
        v-if="status === 'ready' && summary?.total"
        class="quick-progress"
        :class="{ 'is-complete': allCompleted }"
        text
        aria-label="打开交易纪律工作台"
        @click="navigateToCheckin()"
      >
        <span class="quick-progress-label">{{ allCompleted ? '全部完成' : '已完成' }}</span>
        <strong class="quick-progress-value">{{ completionText }}</strong>
      </el-button>
    </header>

    <AppStateBlock
      v-if="status === 'idle' || status === 'loading'"
      state="loading"
      size="tiny"
      title="正在加载今日纪律…"
      :skeleton-rows="2"
    />
    <AppStateBlock
      v-else-if="status === 'error'"
      state="error"
      size="tiny"
      title="今日纪律加载失败"
      :description="errorMessage"
      retry
      @retry="refreshSummary(props.tradeDate)"
    />
    <AppStateBlock
      v-else-if="!summary?.total"
      state="empty"
      size="tiny"
      title="还没有生效的交易规则"
      description="先建立规则，下一交易日起即可开始打卡。"
    >
      <template #extra>
        <el-button size="small" type="primary" plain @click="emit('navigate', { tab: 'rules' })">
          创建第一套规则
        </el-button>
      </template>
    </AppStateBlock>
    <div v-else class="quick-rule-list">
      <article v-for="rule in summary.rules" :key="rule.rule_id" class="quick-rule-row">
        <div class="quick-rule-main">
          <span class="quick-rule-dot" :class="rule.checkin_id ? 'is-done' : 'is-pending'" />
          <div>
            <strong>{{ rule.rule_name }}</strong>
            <span>{{ ruleStatus(rule) }} · v{{ rule.version_no }}</span>
          </div>
        </div>
        <div class="quick-rule-actions">
          <el-button
            v-if="!rule.checkin_id && canSubmit"
            v-permission="'trade-discipline:checkin-submit'"
            size="small"
            type="primary"
            plain
            :loading="submittingRuleId === rule.rule_id"
            :disabled="Boolean(submittingRuleId)"
            @click="openQuickConfirmation(rule.rule_id)"
          >
            无操作履约
          </el-button>
          <el-button size="small" text @click="navigateToCheckin(rule.rule_id)">
            去打卡<el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
        <div v-if="actionErrorRuleId === rule.rule_id" class="quick-rule-error" role="alert">
          {{ actionErrorMessage }}
        </div>
      </article>
      <div class="quick-card-footer">
        <el-button size="small" text @click="emit('navigate', { tab: 'rules' })">管理规则</el-button>
      </div>
    </div>
    <AppDialog v-model="confirmationOpen" title="确认无操作履约" size="compact" boundary="app" :close-on-click-modal="false">
      <p>确认将“{{ pendingRule?.rule_name }}”在 {{ quickTradeDate }} 记录为“已履约 · 今日无操作”？</p>
      <el-form v-if="pendingRule?.max_positions != null" label-position="top">
        <el-form-item label="当日最大同时持仓数" required>
          <el-input-number v-model="peakPositions" :min="0" :max="2147483647" :precision="0" :controls="false" :disabled="Boolean(submittingRuleId)" data-testid="quick-peak-positions" />
        </el-form-item>
        <p class="app-caption-text">规则上限 {{ pendingRule.max_positions }} 只；无操作也可能仍有持仓，请按当日实际峰值确认。</p>
        <p v-if="countError" class="quick-rule-error" role="alert">{{ countError }}。请进入“去打卡”记录实际情况。</p>
      </el-form>
      <p v-if="actionErrorRuleId === pendingRule?.rule_id" class="quick-rule-error" role="alert">{{ actionErrorMessage }}</p>
      <template #footer>
        <el-button :disabled="Boolean(submittingRuleId)" @click="confirmationOpen = false">取消</el-button>
        <el-button v-if="countError" @click="openPendingCheckin">去打卡</el-button>
        <el-button v-permission="'trade-discipline:checkin-submit'" type="primary" :disabled="Boolean(countError)" :loading="Boolean(submittingRuleId)" data-testid="quick-confirm" @click="quickSubmit">确认打卡</el-button>
      </template>
    </AppDialog>
  </section>
</template>

<style scoped>
.discipline-quick-card {
  border: 1px solid var(--page-settings-section-border);
  border-radius: 12px;
  background: var(--page-settings-section-bg);
  overflow: hidden;
}
.quick-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--page-settings-divider);
}
.quick-head > div { display: flex; flex-direction: column; gap: var(--app-space-1); }
.quick-kicker { color: var(--page-settings-text-muted); font-size: var(--app-font-size-caption); }
.quick-head strong { color: var(--page-settings-text); font-size: var(--app-font-size-data); line-height: var(--app-line-height-data); font-weight: var(--app-font-weight-section); }
.quick-progress {
  min-width: 82px;
  padding: var(--app-space-control-gap) var(--app-space-2);
  border: 1px solid var(--app-border-warning);
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-color-warning) 8%, transparent);
  color: var(--page-settings-text);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.quick-progress-label { color: var(--page-settings-text-muted); font-size: var(--app-font-size-caption); }
.quick-progress-value { font-variant-numeric: tabular-nums; }
.quick-progress.is-complete { border-color: var(--app-border-success); background: color-mix(in srgb, var(--el-color-success) 8%, transparent); }
.quick-rule-list { padding: var(--app-space-1) var(--app-space-3) var(--app-space-2); }
.quick-rule-row { padding: var(--app-space-3) 0; border-bottom: 1px solid var(--page-settings-divider); }
.quick-rule-row:last-child { border-bottom: 0; }
.quick-card-footer { display: flex; justify-content: flex-end; padding-top: var(--app-space-1); }
.quick-rule-main { min-width: 0; display: flex; align-items: center; gap: var(--app-space-2); }
.quick-rule-main > div { min-width: 0; display: flex; flex-direction: column; gap: var(--app-space-1); }
.quick-rule-main strong { color: var(--page-settings-text); font-size: var(--app-font-size-table); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.quick-rule-main span { color: var(--page-settings-text-muted); font-size: var(--app-font-size-caption); }
.quick-rule-dot { width: var(--app-space-2); height: var(--app-space-2); border-radius: 50%; flex: none; }
.quick-rule-dot.is-pending { background: var(--el-color-warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-warning) 13%, transparent); }
.quick-rule-dot.is-done { background: var(--el-color-success); }
.quick-rule-actions { margin-top: var(--app-space-2); display: flex; justify-content: flex-end; gap: var(--app-space-1); }
.quick-rule-actions :deep(.el-button + .el-button) { margin-left: 0; }
.quick-rule-error { margin-top: var(--app-space-2); color: var(--el-color-danger); font-size: var(--app-font-size-caption); line-height: var(--app-line-height-caption); }
@container app-viewport (max-width: 520px) {
  .quick-head { align-items: flex-start; }
  .quick-rule-actions { justify-content: flex-start; flex-wrap: wrap; }
}
</style>

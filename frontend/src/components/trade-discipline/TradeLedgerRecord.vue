<script setup lang="ts">
import { computed } from 'vue'
import TradeDisciplineSectionPanel from '@/components/trade-discipline/TradeDisciplineSectionPanel.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppStatusNotice from '@/components/AppStatusNotice.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import StockStatusTag from '@/components/StockStatusTag.vue'
import type { StockOption } from '@/api/tradeDiscipline'
import type { LedgerSnapshot } from '@/api/tradeLedger'
import { checkinAssessmentLabel, checkinAssessmentTagType } from '@/utils/tradeDisciplineAssessment'
import { ledgerRuleRecords } from '@/utils/tradeLedgerRecord'
import { financialReportMonthRestrictionText } from '@/utils/tradeDisciplineConditions'
import TradeLedgerEventTable from './TradeLedgerEventTable.vue'

const props = withDefaults(defineProps<{
  snapshot: LedgerSnapshot
  stockOptions?: StockOption[]
  showAccountDetails?: boolean
  /** 已有核对结果面板承接外框时，内部规则分区使用 none。 */
  borderPlacement?: 'body' | 'panel' | 'none'
}>(), { showAccountDetails: true, borderPlacement: 'panel' })
const groups = computed(() => ledgerRuleRecords(props.snapshot))
const adjustments = computed(() => props.snapshot.events.filter(event => event.kind !== 'trade'))
const stocks = computed(() => new Map((props.stockOptions ?? []).map(stock => [stock.code, stock])))
</script>

<template>
  <div class="ledger-record" data-testid="ledger-record">
    <AppStateBlock v-if="!groups.length && !adjustments.length" state="empty" size="tiny" title="当日无买卖或调整记录" description="该交易日没有需要核对的有效规则。" />
    <TradeDisciplineSectionPanel v-for="group in groups" :key="group.ruleId" :title="group.name" :border-placement="borderPlacement" grouped data-testid="ledger-rule-record"
      :description="`${group.versionNo ? `v${group.versionNo} · ` : ''}实际成交 ${group.trades.filter(item => !item.linked).length} 笔${group.trades.some(item => item.linked) ? ` · 关联核对 ${group.trades.filter(item => item.linked).length} 笔` : ''} · 漏买漏卖 ${group.omissions.length} 项`">
      <template #actions><el-tag :type="!group.ruleId ? 'danger' : group.assessment ? checkinAssessmentTagType(group.assessment) : 'info'">{{ !group.ruleId ? '未按规则操作' : !group.confirmed ? '待打卡' : group.assessment ? checkinAssessmentLabel(group.assessment) : '待核对' }}</el-tag></template>
      <div class="ledger-record__content">
        <p v-if="group.ruleId" class="app-caption-text">财报月份交易限制：{{ group.restrictFinancialReportMonths ? financialReportMonthRestrictionText : '未启用' }}</p>
        <AppStatusNotice v-if="!group.confirmed" size="compact" title="本规则尚未确认打卡" description="没有买卖操作，也需要单独确认。" />
        <p v-for="issue in group.issues" :key="issue" class="app-body-text">{{ issue }}</p>
        <p v-for="warning in group.warnings" :key="warning" class="app-caption-text">待核对：{{ warning }}</p>
        <AppControlRow v-for="(item, index) in group.omissions" :key="index" class="ledger-record__omission">
          <el-tag type="warning" effect="plain">{{ item.kind === 'missed_buy' ? '应买未买' : '应卖未卖' }}</el-tag>
          <strong class="app-body-text">{{ item.stock_name || item.stock_code }}</strong><span v-if="item.stock_name" class="app-caption-text">{{ item.stock_code }}</span><StockStatusTag :is-st="stocks.get(item.stock_code)?.is_st" :as-of-date="snapshot.trade_date" />
        </AppControlRow>
        <TradeLedgerEventTable v-if="group.trades.length" :events="group.trades" />
        <p v-else class="app-caption-text">当日没有实际买卖{{ group.omissions.length ? '，以上遗漏事项计入本规则核对。' : '。' }}</p>
      </div>
    </TradeDisciplineSectionPanel>
    <TradeDisciplineSectionPanel v-if="showAccountDetails && adjustments.length" title="持仓与资金调整" :border-placement="borderPlacement" description="账户实际变动，独立于买卖成交，不重复记账。" data-testid="ledger-record-adjustments"><TradeLedgerEventTable :events="adjustments" :stock-options="stockOptions" adjustments /></TradeDisciplineSectionPanel>
    <TradeDisciplineSectionPanel v-if="showAccountDetails && snapshot.review_note" title="复盘备注" :border-placement="borderPlacement"><p class="ledger-record__note app-body-text">{{ snapshot.review_note }}</p></TradeDisciplineSectionPanel>
  </div>
</template>

<style scoped>
.ledger-record { display: grid; gap: var(--app-space-4); min-width: 0; }
.ledger-record__content { display: grid; gap: var(--app-space-3); min-width: 0; }
.ledger-record p { margin: 0; overflow-wrap: anywhere; }
.ledger-record__omission { min-width: 0; }
.ledger-record__omission strong { overflow-wrap: anywhere; }
.ledger-record__note { white-space: pre-wrap; }
</style>

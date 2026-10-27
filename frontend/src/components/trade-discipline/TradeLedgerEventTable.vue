<script setup lang="ts">
import AppDataTable from '@/components/AppDataTable.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import StockStatusTag from '@/components/StockStatusTag.vue'
import type { LedgerEvent } from '@/api/tradeLedger'
import type { StockOption } from '@/api/tradeDiscipline'
import { computed } from 'vue'
import { formatDateTimeSeconds } from '@/utils/dateTime'
import { formatDecimalString } from '@/utils/fixedDecimal'
import { formatMoney } from '@/utils/money'
import { operationSTStatus } from '@/utils/tradeDisciplineOperations'

const props = defineProps<{ events: LedgerEvent[]; adjustments?: boolean; stockOptions?: StockOption[] }>()
const stocks = computed(() => new Map((props.stockOptions ?? []).map(stock => [stock.code, stock])))

function changeLabel(event: LedgerEvent) {
  if (event.kind === 'cash') return event.direction === 'in' ? '资金流入' : '资金流出'
  return `${event.kind === 'position' ? '持仓调整·' : ''}${event.side === 'buy' ? '买入' : '卖出'}`
}
</script>

<template>
  <AppDataTable :data="events" embedded row-key="event_id">
    <AppTableColumn label="实际时间" role="datetime"><template #default="{ row }">{{ formatDateTimeSeconds(row.operated_at) }}</template></AppTableColumn>
    <AppTableColumn label="股票" role="entity"><template #default="{ row }">
      <span class="app-inline-info app-inline-info--nowrap"><span>{{ row.stock_name_snapshot || row.stock_code || '—' }}<span v-if="row.stock_name_snapshot && row.stock_code" class="app-caption-text"> · {{ row.stock_code }}</span></span><StockStatusTag v-if="row.stock_code" :is-st="row.kind === 'trade' ? operationSTStatus(row).is_st : stocks.get(row.stock_code)?.is_st" :as-of-date="row.kind === 'trade' ? operationSTStatus(row).st_as_of_date : stocks.get(row.stock_code)?.st_as_of_date" :show-unknown="row.kind === 'trade'" /></span>
      <span v-if="row.linked" class="app-caption-text">关联已有成交，不重复记账</span>
    </template></AppTableColumn>
    <AppTableColumn label="变动类型" role="status"><template #default="{ row }">{{ changeLabel(row) }}</template></AppTableColumn>
    <AppTableColumn v-if="!adjustments" label="成交价" header-meta="元" role="number"><template #default="{ row }">{{ formatDecimalString(row.price, 4) }}</template></AppTableColumn>
    <AppTableColumn label="数量" header-meta="股" role="number"><template #default="{ row }">{{ formatDecimalString(row.quantity, 4) }}</template></AppTableColumn>
    <AppTableColumn label="金额" header-meta="元" role="number"><template #default="{ row }">{{ formatMoney(row.amount) }}</template></AppTableColumn>
    <AppTableColumn v-if="!adjustments" label="费用" header-meta="元" role="number"><template #default="{ row }">{{ formatMoney(row.fee) }}</template></AppTableColumn>
    <AppTableColumn :label="adjustments ? '调整原因' : '核对依据'" role="description"><template #default="{ row }">{{ adjustments ? row.note || '—' : [...(row.issues ?? []), ...(row.warnings ?? [])].join('；') || '无偏差' }}</template></AppTableColumn>
  </AppDataTable>
</template>

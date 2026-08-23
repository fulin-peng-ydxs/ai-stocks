<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import {
  getTradeDisciplineCheckinRevision,
  type CheckinHistoryRow,
  type CheckinOperation,
  type TradeDisciplineCheckin,
} from '@/api/tradeDiscipline'
import { getErrorMessage } from '@/utils/error'
import { formatDecimalString } from '@/utils/fixedDecimal'

const props = defineProps<{
  modelValue: boolean
  row: CheckinHistoryRow | null
  canSubmit: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  amend: [value: { ruleId: string; tradeDate: string }]
}>()

const selectedRevision = ref(1)
const detail = ref<TradeDisciplineCheckin | null>(null)
const loading = ref(false)
const loadError = ref('')
let loadSeq = 0

const revisionOptions = computed(() => {
  const current = props.row?.current_revision_no ?? 1
  return Array.from({ length: current }, (_, index) => current - index).map((revision) => ({
    value: String(revision),
    label: revision === current ? `r${revision} · 当前` : `r${revision}`,
  }))
})
const isCurrent = computed(() => selectedRevision.value === props.row?.current_revision_no)
const ruleVersion = computed(() => detail.value?.rule_version)

function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  return value.replace('T', ' ').replace(/\.\d+/, '').replace(/\+.*$/, '').slice(0, 19)
}

function sideText(value: CheckinOperation['side']): string {
  return value === 'buy' ? '买入' : '卖出'
}

async function loadRevision(): Promise<void> {
  if (!props.modelValue || !props.row) return
  const seq = ++loadSeq
  loading.value = true
  loadError.value = ''
  detail.value = null
  try {
    const result = await getTradeDisciplineCheckinRevision(props.row.id, selectedRevision.value)
    if (seq !== loadSeq) return
    detail.value = result
  } catch (error) {
    if (seq !== loadSeq) return
    detail.value = null
    loadError.value = getErrorMessage(error, '修订详情读取失败')
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function changeRevision(value: string[] | string): void {
  selectedRevision.value = Number(Array.isArray(value) ? value[0] : value)
}

function startAmend(): void {
  if (!props.row || !props.canSubmit || !isCurrent.value) return
  emit('update:modelValue', false)
  emit('amend', { ruleId: props.row.rule_id, tradeDate: props.row.trade_date })
}

watch(
  () => [props.modelValue, props.row?.id, props.row?.current_revision_no] as const,
  ([open]) => {
    if (!open || !props.row) return
    selectedRevision.value = props.row.current_revision_no
  },
  { immediate: true },
)
watch(
  () => [props.modelValue, props.row?.id, selectedRevision.value] as const,
  ([open]) => { if (open && props.row) void loadRevision() },
  { immediate: true },
)
</script>

<template>
  <PageDrawer
    :model-value="modelValue"
    title="履约修订详情"
    size="xl"
    data-testid="checkin-revision-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <AppStateBlock v-if="loading" state="loading" title="正在读取修订快照…" />
    <AppStateBlock
      v-else-if="loadError"
      state="error"
      title="修订详情读取失败"
      :description="loadError"
      retry
      @retry="loadRevision"
    />
    <div v-else-if="detail" class="revision-detail">
      <section class="detail-hero">
        <div>
          <div class="detail-kicker">{{ detail.trade_date }} · r{{ detail.revision_no }}</div>
          <h3>{{ detail.rule_name }}</h3>
          <p>规则版本 v{{ detail.version_no }} · {{ detail.assessment === 'complied' ? '已履约' : '未履约' }}</p>
        </div>
        <div class="hero-facts">
          <el-tag :type="detail.revision_no === detail.current_revision_no ? 'success' : 'info'" effect="plain">
            {{ detail.revision_no === detail.current_revision_no ? '当前修订' : '历史修订 · 只读' }}
          </el-tag>
          <el-tag :type="detail.financial_complete ? 'success' : 'warning'" effect="plain">
            {{ detail.financial_complete ? '财务字段完整' : '财务字段不完整' }}
          </el-tag>
        </div>
      </section>

      <section class="detail-card revision-switcher">
        <div>
          <h4>修订版本</h4>
          <p>旧修订为不可变快照，切换查看不会改变当前记录。</p>
        </div>
        <AppFilterSelect
          data-testid="revision-selector"
          :model-value="String(selectedRevision)"
          :options="revisionOptions"
          :multiple="false"
          :clearable="false"
          :filterable="false"
          aria-label="修订版本"
          @change="changeRevision"
        />
      </section>

      <section class="detail-card">
        <h4>履约结论</h4>
        <dl class="fact-grid">
          <div><dt>用户自评</dt><dd>{{ detail.assessment === 'complied' ? '已履约' : '未履约' }}</dd></div>
          <div><dt>操作状态</dt><dd>{{ detail.no_operation ? '今日无操作' : `${detail.operations.length} 笔操作` }}</dd></div>
          <div><dt>未履约原因</dt><dd>{{ detail.reason_name_snapshot || '—' }}</dd></div>
          <div><dt>记录时间</dt><dd>{{ formatTime(detail.created_at || detail.amended_at || detail.submitted_at) }}</dd></div>
        </dl>
        <div v-if="detail.violation_detail" class="text-snapshot"><strong>详细说明</strong><p>{{ detail.violation_detail }}</p></div>
        <div class="text-snapshot"><strong>复盘说明</strong><p>{{ detail.review_note || '—' }}</p></div>
      </section>

      <section v-if="ruleVersion" class="detail-card">
        <h4>规则版本快照</h4>
        <dl class="fact-grid">
          <div><dt>规则名称</dt><dd>{{ ruleVersion.name }}</dd></div>
          <div><dt>规则资金</dt><dd>¥ {{ formatDecimalString(ruleVersion.capital) }}</dd></div>
        </dl>
        <div class="rule-grid">
          <div>
            <strong>选股规则</strong>
            <article v-for="rule in ruleVersion.stock_rules" :key="rule.detail_id || rule.display_order" class="rule-snapshot">
              <span>{{ rule.name || '未命名规则' }} · {{ rule.enabled ? '启用' : '停用' }}</span>
              <small>资金上限 ¥ {{ formatDecimalString(rule.max_capital) }}</small>
              <p>{{ rule.content || '—' }}</p>
            </article>
          </div>
          <div>
            <strong>买卖规则</strong>
            <article v-for="rule in ruleVersion.action_rules" :key="rule.detail_id || rule.display_order" class="rule-snapshot">
              <span>{{ rule.name || '未命名规则' }} · {{ rule.action_type === 'buy' ? '买入' : '卖出' }} · {{ rule.enabled ? '启用' : '停用' }}</span>
              <p>{{ rule.content || '—' }}</p>
            </article>
          </div>
        </div>
      </section>

      <section class="detail-card operation-section">
        <h4>操作快照</h4>
        <p v-if="detail.no_operation" class="empty-copy">该修订记录为“今日无操作”。</p>
        <AppDataTable
          v-else
          :data="detail.operations"
          embedded
          kind="wide-table"
          row-key="id"
          aria-label="修订操作快照"
        >
          <AppTableColumn label="股票" role="name">
            <template #default="{ row }">{{ row.stock_code }} · {{ row.stock_name_snapshot }}</template>
          </AppTableColumn>
          <AppTableColumn label="方向"><template #default="{ row }">{{ sideText(row.side) }}</template></AppTableColumn>
          <AppTableColumn label="规则关联" role="description">
            <template #default="{ row }">{{ row.stock_rule_name || '—' }} / {{ row.action_rule_name || '—' }}</template>
          </AppTableColumn>
          <AppTableColumn label="成交事实" role="description">
            <template #default="{ row }">价 {{ formatDecimalString(row.price, 4) }} · 量 {{ formatDecimalString(row.quantity, 4) }} · 额 {{ formatDecimalString(row.amount) }} · 费 {{ formatDecimalString(row.fee) }}</template>
          </AppTableColumn>
          <AppTableColumn label="操作时间"><template #default="{ row }">{{ formatTime(row.operated_at) }}</template></AppTableColumn>
          <AppTableColumn label="完整度">
            <template #default="{ row }"><el-tag :type="row.financial_complete ? 'success' : 'warning'" effect="plain">{{ row.financial_complete ? '完整' : '不完整' }}</el-tag></template>
          </AppTableColumn>
          <AppTableColumn prop="note" label="说明" role="description"><template #default="{ row }">{{ row.note || '—' }}</template></AppTableColumn>
        </AppDataTable>
      </section>
    </div>

    <template #footer>
      <div class="drawer-actions">
        <span v-if="detail && !isCurrent" class="app-caption-text">历史修订不可编辑，请切换到当前修订。</span>
        <el-button
          v-if="canSubmit"
          v-permission="'trade-discipline:checkin-submit'"
          type="primary"
          :disabled="!detail || !isCurrent"
          @click="startAmend"
        >发起修正</el-button>
        <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      </div>
    </template>
  </PageDrawer>
</template>

<style scoped>
.revision-detail { display: grid; gap: var(--app-space-4); }
.detail-hero, .hero-facts, .revision-switcher, .drawer-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); }
.detail-hero { align-items: flex-start; padding-bottom: var(--app-space-3); border-bottom: 1px solid var(--el-border-color-lighter); }
.detail-hero h3 { margin: var(--app-space-1) 0; }
.detail-hero p, .revision-switcher p { margin: 0; color: var(--el-text-color-secondary); }
.hero-facts { justify-content: flex-end; flex-wrap: wrap; }
.detail-card { padding: var(--app-space-4); border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-blank); }
.detail-card h4 { margin: 0 0 var(--app-space-3); }
.revision-switcher h4 { margin-bottom: var(--app-space-1); }
.revision-switcher :deep(.app-filter-select) { width: 180px; flex: none; }
.fact-grid { display: grid; grid-template-columns: repeat(2, minmax(180px, 1fr)); gap: var(--app-space-3); margin: 0; }
.fact-grid > div { padding-bottom: var(--app-space-2); border-bottom: 1px solid var(--el-border-color-lighter); }
.fact-grid dt { color: var(--el-text-color-secondary); font-size: var(--app-font-size-caption); }
.fact-grid dd { margin: var(--app-space-1) 0 0; font-weight: var(--app-font-weight-section); }
.text-snapshot { margin-top: var(--app-space-3); }
.text-snapshot p, .rule-snapshot p { margin: var(--app-space-1) 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.rule-grid { display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: var(--app-space-4); }
.rule-snapshot { margin-top: var(--app-space-2); padding: var(--app-space-3); border-radius: 6px; background: var(--el-fill-color-light); }
.rule-snapshot span, .rule-snapshot small { display: block; }
.rule-snapshot small, .empty-copy { color: var(--el-text-color-secondary); }
.operation-section { min-width: 0; }
.drawer-actions { justify-content: flex-end; }
.drawer-actions span { margin-right: auto; }
@media (max-width: 760px) {
  .detail-hero, .revision-switcher { align-items: stretch; flex-direction: column; }
  .hero-facts { justify-content: flex-start; }
  .revision-switcher :deep(.app-filter-select) { width: 100%; }
  .fact-grid, .rule-grid { grid-template-columns: 1fr; }
}
</style>

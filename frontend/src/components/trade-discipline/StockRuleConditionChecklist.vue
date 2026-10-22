<script setup lang="ts">
import { computed } from 'vue'
import ConfigPanelSection from '@/components/config/ConfigPanelSection.vue'
import type { StockConditionPanelDefaults } from '@/layout/configPanel'
import { useTradeConditionSections } from '@/composables/useTradeConditionSections'
import type { CheckinOperation, DraftStockRule, StockChecklistResult, ConditionFact } from '@/api/tradeDiscipline'
import { checklistCategories, checklistResultOptions, normalizeChecklist, conditionSectionSummary, type ConditionSectionsState } from '@/utils/tradeDisciplineConditions'

const props = defineProps<{
  rule: DraftStockRule
  operation?: CheckinOperation
  panelDefaults?: StockConditionPanelDefaults
  openSections?: ConditionSectionsState
  results?: StockChecklistResult[] | null
  checking?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:results': [results: StockChecklistResult[]]; 'update:openSections': [state: ConditionSectionsState] }>()
const { root, open, setOpen, reveal } = useTradeConditionSections(() => props.openSections, state => emit('update:openSections', state), () => props.panelDefaults)
const items = computed(() => normalizeChecklist(props.rule.checklist_items ?? []))
function status(itemId: string) {
  return props.results?.find(item => item.item_id === itemId)?.status
}
function choose(itemId: string, value: ConditionFact) {
  if (props.disabled) return
  const selected = new Map((props.results ?? []).map(item => [item.item_id, item.status]))
  selected.set(itemId, value)
  // 保持版本顺序，改回原值不会仅因点选顺序变化被当作实质修正。
  emit('update:results', (props.rule.checklist_items ?? []).flatMap(item => {
    const status = selected.get(item.item_id)
    return status ? [{ item_id: item.item_id, status }] : []
  }))
}
defineExpose({ reveal })
</script>

<template>
  <div ref="root" class="stock-condition-checklist" data-testid="stock-condition-checklist">
    <ConfigPanelSection v-for="category in checklistCategories" :key="category.value" class="stock-condition-checklist__group" :title="category.label" :aria-label="category.label"
      :level="2" :default-open="false" :model-value="!!open[category.value]" :data-condition-section="category.value"
      :summary="conditionSectionSummary(rule, category.value, checking || results !== undefined, results, operation)"
      @update:model-value="setOpen(category.value, $event)">
        <slot :name="category.value" />
        <div v-for="item in items.filter(entry => entry.category === category.value)" :key="item.item_id" class="stock-condition-checklist__row" :data-checklist-id="item.item_id">
          <span class="stock-condition-checklist__text">{{ item.text }}</span>
          <el-segmented v-if="checking && !disabled" :model-value="status(item.item_id)" :options="checklistResultOptions" :aria-label="`核对：${item.text}`" @update:model-value="choose(item.item_id, $event)" />
          <span v-else-if="checking || results !== undefined" class="stock-condition-checklist__result" :class="{ 'is-breached': status(item.item_id) === 'no' }">{{ checklistResultOptions.find(option => option.value === status(item.item_id))?.label ?? '未记录' }}</span>
        </div>
    </ConfigPanelSection>
    <ConfigPanelSection v-if="rule.content" title="补充说明" :level="2" :default-open="false" :model-value="!!open.notes" summary="已填写"
      data-condition-section="notes" @update:model-value="setOpen('notes', $event)">
      <p class="stock-condition-checklist__notes">{{ rule.content }}</p>
    </ConfigPanelSection>
  </div>
</template>

<style scoped>
.stock-condition-checklist { min-width: 0; }
.stock-condition-checklist__row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2) var(--app-space-3); padding: var(--app-space-2) 0; }
.stock-condition-checklist__text { flex: 1 1 260px; min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.stock-condition-checklist__row > .el-segmented { flex: none; }
.stock-condition-checklist__result { color: var(--el-text-color-secondary); }
.stock-condition-checklist__result.is-breached { color: var(--el-color-danger); }
.stock-condition-checklist__notes { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
</style>

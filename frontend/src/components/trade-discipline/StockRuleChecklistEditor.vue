<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import AppReorderList from '@/components/AppReorderList.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed, nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import type { InputInstance } from 'element-plus'
import ConfigPanelSection from '@/components/config/ConfigPanelSection.vue'
import { useTradeDisciplineCategories } from '@/composables/useTradeDisciplineCategories'
import type { StockConditionPanelDefaults } from '@/layout/configPanel'
import { useTradeConditionSections } from '@/composables/useTradeConditionSections'
import type { ChecklistCategory, DraftStockRule, StockChecklistItem } from '@/api/tradeDiscipline'
import { conditionCategories, checklistCategory, conditionSectionSummary, normalizeChecklist, type ConditionSectionsState } from '@/utils/tradeDisciplineConditions'

const props = defineProps<{ modelValue: StockChecklistItem[]; rule?: DraftStockRule; disabled?: boolean; panelDefaults?: StockConditionPanelDefaults; openSections?: ConditionSectionsState }>()
const emit = defineEmits<{ 'update:modelValue': [items: StockChecklistItem[]]; 'update:openSections': [state: ConditionSectionsState] }>()
const { root, open, setOpen, reveal } = useTradeConditionSections(() => props.openSections, state => emit('update:openSections', state), () => props.panelDefaults)
const options = useTradeDisciplineCategories()
const categories = computed(() => conditionCategories(props.modelValue, options.value))
const inputs = new Map<string, InputInstance>()
let observer: ResizeObserver | undefined
let previousWidth = 0
// 条件行随工作区宽度换行后重新测高，不重挂载输入框或丢失编辑状态。
onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !root.value) return
  observer = new ResizeObserver(([entry]) => {
    const width = entry?.contentRect.width ?? 0
    if (!width || width === previousWidth) return
    previousWidth = width
    void nextTick(() => inputs.forEach(input => input.resizeTextarea()))
  })
  observer.observe(root.value)
})
onBeforeUnmount(() => { observer?.disconnect(); inputs.clear() })
function setInput(id: string, input: InputInstance | null) {
  if (input) inputs.set(id, input)
  else inputs.delete(id)
}
function group(category: ChecklistCategory) {
  return normalizeChecklist(props.modelValue, categories.value).filter(item => item.category === category)
}
function save(items: StockChecklistItem[]) {
  if (!props.disabled) emit('update:modelValue', normalizeChecklist(items, categories.value))
}
function add() {
  const category = options.value.find(item => item.value === 'technical') ?? options.value.find(item => !item.disabled)
  if (!category) return
  const item: StockChecklistItem = { item_id: `tdci_${crypto.randomUUID()}`, category: category.value, text: '', display_order: props.modelValue.length + 1 }
  save([...props.modelValue, item])
  void reveal(category.value, item.item_id)
}
function update(item: StockChecklistItem, patch: Partial<StockChecklistItem>) {
  save(props.modelValue.map(entry => entry.item_id === item.item_id ? { ...entry, ...patch } : entry))
  if (patch.category) void reveal(checklistCategory(patch.category), item.item_id)
}
function reorder(category: ChecklistCategory, items: StockChecklistItem[]) {
  save([...props.modelValue.filter(item => checklistCategory(item.category) !== category), ...items])
}
watch(open, () => { void nextTick(() => inputs.forEach(input => input.resizeTextarea())) }, { deep: true })
defineExpose({ reveal })
</script>

<template>
  <div ref="root" class="stock-checklist-editor" data-testid="stock-checklist-editor">
    <div class="stock-checklist-editor__tools">
      <span class="app-caption-text">逐项填写可在今日打卡核对的条件</span>
      <el-button v-if="!disabled" :disabled="!options.some(item => !item.disabled)" :icon="Plus" size="small" data-testid="add-checklist-item" @click="add">添加检查项</el-button>
    </div>
    <ConfigPanelSection v-for="category in categories" :key="category.value" class="stock-checklist-editor__group" :aria-label="category.label"
      :title="category.label" :level="2" :default-open="false" :model-value="!!open[category.value]"
      :summary="conditionSectionSummary({ ...rule, checklist_items: modelValue } as DraftStockRule, category.value)"
      :data-condition-section="category.value" @update:model-value="setOpen(category.value, $event)">

      <div v-if="$slots[category.value]" class="stock-checklist-editor__fields"><slot :name="category.value" /></div>
      <AppReorderList
        :items="group(category.value)" :item-key="item => item.item_id" :item-label="item => item.text || '未填写条件'"
        :label="`${category.label}检查项排序`" :disabled="disabled" @reorder="reorder(category.value, $event)"
      >
        <template #default="{ item }">
          <div class="stock-checklist-editor__row" :data-checklist-id="item.item_id">
            <el-input :ref="(input: unknown) => setInput(item.item_id, input as InputInstance | null)" :model-value="item.text" :disabled="disabled" type="textarea" :autosize="{ minRows: 1 }" resize="none" :aria-label="`${category.label}条件内容`" placeholder="填写一条可核对的条件" @update:model-value="update(item, { text: $event })" />
            <AppSelect :model-value="item.category" :disabled="disabled" aria-label="检查项分类" @update:model-value="update(item, { category: $event })">
              <el-option v-for="option in categories" :key="option.value" :label="option.label" :value="option.value" :disabled="option.disabled" />
            </AppSelect>
            <AppIconButton v-if="!disabled" label="删除检查项" tooltip="删除检查项" size="sm" tone="danger" @click="save(modelValue.filter(entry => entry.item_id !== item.item_id))"><Delete /></AppIconButton>
          </div>
        </template>
      </AppReorderList>
      <p v-if="!group(category.value).length && !$slots[category.value]" class="app-caption-text">暂无检查项</p>
    </ConfigPanelSection>
    <ConfigPanelSection v-if="$slots.notes" title="补充说明" :level="2" :default-open="false" :model-value="!!open.notes"
      :summary="rule?.content?.trim() ? '已填写' : '未填写'" data-condition-section="notes" @update:model-value="setOpen('notes', $event)">
      <slot name="notes" />
    </ConfigPanelSection>
  </div>
</template>

<style scoped>
.stock-checklist-editor { min-width: 0; --app-reorder-handle-offset: var(--app-space-1); }
.stock-checklist-editor__tools { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: var(--app-space-2); margin-bottom: var(--app-space-3); }
.stock-checklist-editor__fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr)); gap: 0 var(--app-space-3); }
.stock-checklist-editor__row { display: flex; align-items: flex-start; flex-wrap: wrap; gap: var(--app-space-2); }
.stock-checklist-editor__row > .el-textarea { flex: 1 1 240px; min-width: 0; }
.stock-checklist-editor__row > :deep(.el-select) { flex: 0 1 140px; min-width: 0; }
</style>

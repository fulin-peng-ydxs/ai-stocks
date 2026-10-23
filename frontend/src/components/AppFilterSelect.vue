<script setup lang="ts">
import AppSelect from '@/components/AppSelect.vue'
import AppMultiSelect, { type AppMultiSelectOption } from '@/components/AppMultiSelect.vue'
import { computed } from 'vue'

export type AppFilterSelectOption = AppMultiSelectOption

export type AppFilterSelectDisplayMode = 'tags' | 'count'

const props = withDefaults(defineProps<{
  modelValue?: string[] | string | null
  options: AppFilterSelectOption[]
  placeholder?: string
  multiple?: boolean
  clearable?: boolean
  filterable?: boolean
  collapseTags?: boolean
  visibleTagCount?: number
  displayMode?: AppFilterSelectDisplayMode
  /** 全部候选项恰好被选中时的优先摘要；传空字符串可关闭。 */
  allSelectedLabel?: string
  allowCreate?: boolean
  defaultFirstOption?: boolean
  size?: 'large' | 'default' | 'small'
  disabled?: boolean
  ariaLabel?: string
}>(), {
  placeholder: '请选择',
  multiple: true,
  clearable: true,
  filterable: true,
  collapseTags: true,
  visibleTagCount: 1,
  displayMode: 'tags',
  allSelectedLabel: '全部选中',
  allowCreate: false,
  defaultFirstOption: false,
  size: 'default',
  disabled: false,
  ariaLabel: undefined,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[] | string): void
  (e: 'change', value: string[] | string): void
}>()

function toMulti(value: string[] | string | null | undefined): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  const text = String(value ?? '').trim()
  return text ? [text] : []
}

const normalizedVisibleTagCount = computed(() => {
  const value = Math.floor(Number(props.visibleTagCount))
  if (!Number.isFinite(value)) return 1
  return Math.min(3, Math.max(1, value))
})
const selectedCount = computed(() => toMulti(props.modelValue).length)
const isAllSelected = computed(() => {
  if (!props.multiple || !props.allSelectedLabel.trim() || props.options.length === 0) return false

  const optionValues = new Set(props.options.map(item => String(item.value)))
  const selectedValues = new Set(toMulti(props.modelValue))
  return optionValues.size === selectedValues.size
    && [...optionValues].every(value => selectedValues.has(value))
})

const selected = computed<string[] | string>({
  get() {
    if (props.multiple) return toMulti(props.modelValue)
    return Array.isArray(props.modelValue) ? props.modelValue[0] ?? '' : String(props.modelValue ?? '')
  },
  set(value) {
    emit('update:modelValue', props.multiple ? toMulti(value) : String(Array.isArray(value) ? value[0] ?? '' : value ?? ''))
  },
})
const hasSelection = computed(() => (
  props.multiple
    ? toMulti(props.modelValue).length > 0
    : String(
      Array.isArray(props.modelValue) ? props.modelValue[0] ?? '' : props.modelValue ?? '',
    ).trim() !== ''
))

function onChange(value: string[] | string) {
  emit('change', props.multiple ? toMulti(value) : String(Array.isArray(value) ? value[0] ?? '' : value ?? ''))
}

</script>

<template>
  <div
    class="app-filter-select"
    :class="{
      'app-filter-select--multiple': multiple,
      'app-filter-select--has-selection': multiple && hasSelection,
      'app-filter-select--count': multiple && displayMode === 'count',
      [`app-filter-select--visible-tags-${normalizedVisibleTagCount}`]: multiple && displayMode === 'tags',
      [`app-filter-select--${size}`]: true,
    }"
    :data-visible-tag-count="multiple ? normalizedVisibleTagCount : undefined"
    :data-display-mode="multiple ? displayMode : undefined"
    :data-all-selected="multiple ? isAllSelected : undefined"
  >
    <component
      :is="multiple ? AppMultiSelect : AppSelect"
      v-bind="multiple ? { options } : {}"
      v-model="selected"
      class="app-filter-select__control"
      :multiple="multiple"
      :clearable="clearable"
      :filterable="filterable"
      :allow-create="allowCreate"
      :default-first-option="defaultFirstOption"
      :collapse-tags="multiple && collapseTags"
      :collapse-tags-tooltip="multiple && collapseTags"
      :max-collapse-tags="normalizedVisibleTagCount"
      popper-class="app-filter-select-popper"
      :size="size"
      :disabled="disabled"
      :placeholder="placeholder"
      :aria-label="ariaLabel || placeholder"
      @change="onChange"
    >
      <template v-if="multiple && isAllSelected" #tag>
        <span class="app-filter-select__selection-summary">{{ allSelectedLabel }}</span>
      </template>
      <template v-else-if="multiple && displayMode === 'count' && hasSelection" #tag>
        <span class="app-filter-select__selection-summary">已选 {{ selectedCount }}</span>
      </template>
      <el-option
        v-for="item in multiple ? [] : options"
        :key="item.value"
        :label="item.label"
        :value="item.value"
      />
    </component>
  </div>
</template>

<style scoped>
.app-filter-select {
  width: var(--app-control-inline-width, 100%);
  max-width: 100%;
  min-width: 0;
}
.app-filter-select--visible-tags-1 {
  --app-control-inline-width: var(--app-control-width-medium);
}
.app-filter-select--visible-tags-2 {
  --app-control-inline-width: var(--app-control-width-long);
}
.app-filter-select--visible-tags-3 {
  --app-control-inline-width: var(--app-control-width-wide);
}
.app-filter-select--count {
  --app-control-inline-width: var(--app-control-width-short);
}
.app-filter-select__control {
  width: 100%;
}
.app-filter-select__control :deep(.el-select__wrapper),
.app-filter-select__control :deep(.el-select__selection) {
  flex-wrap: nowrap;
}
.app-filter-select__control :deep(.el-select__wrapper) {
  height: var(--app-control-height-md);
}
.app-filter-select--small .app-filter-select__control :deep(.el-select__wrapper) {
  height: var(--app-control-height-sm);
}
.app-filter-select--large .app-filter-select__control :deep(.el-select__wrapper) {
  height: var(--app-control-height-lg);
}
.app-filter-select--multiple.app-filter-select--has-selection .app-filter-select__control :deep(.el-select__wrapper) {
  overflow: hidden;
}
.app-filter-select__control :deep(.el-select__selection) {
  min-width: 0;
}
/* Element Plus 的空值可搜索多选会让 selection 高度归零；此时裁剪会隐藏负层级占位文案。 */
.app-filter-select--multiple.app-filter-select--has-selection .app-filter-select__control :deep(.el-select__selection) {
  overflow: hidden;
}
.app-filter-select__selection-summary {
  overflow: hidden;
  min-width: 0;
  padding: 0 var(--app-space-1);
  color: var(--el-text-color-regular);
  font-size: var(--app-font-size-body);
  line-height: var(--app-line-height-body);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

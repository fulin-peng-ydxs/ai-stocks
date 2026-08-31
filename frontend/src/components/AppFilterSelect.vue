<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

export interface AppFilterSelectOption {
  value: string
  label: string
}

const props = withDefaults(defineProps<{
  modelValue?: string[] | string | null
  options: AppFilterSelectOption[]
  placeholder?: string
  multiple?: boolean
  clearable?: boolean
  filterable?: boolean
  collapseTags?: boolean
  collapseOnOverflow?: boolean
  maxCollapseTags?: number
  disabled?: boolean
  ariaLabel?: string
}>(), {
  placeholder: '请选择',
  multiple: true,
  clearable: true,
  filterable: true,
  collapseTags: true,
  collapseOnOverflow: true,
  maxCollapseTags: 3,
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

const rootRef = ref<HTMLElement | null>(null)
const normalizedMaxCollapseTags = computed(() => {
  const value = Math.floor(Number(props.maxCollapseTags))
  return Number.isFinite(value) && value > 0 ? value : 1
})
const effectiveMaxCollapseTags = ref(normalizedMaxCollapseTags.value)
let resizeObserver: ResizeObserver | null = null
let recomputing = false
let recomputeAgain = false
let recomputeVersion = 0

const selected = computed<string[] | string>({
  get() {
    if (props.multiple) return toMulti(props.modelValue)
    return Array.isArray(props.modelValue) ? props.modelValue[0] ?? '' : String(props.modelValue ?? '')
  },
  set(value) {
    emit('update:modelValue', props.multiple ? toMulti(value) : String(Array.isArray(value) ? value[0] ?? '' : value ?? ''))
  },
})

function onChange(value: string[] | string) {
  emit('change', props.multiple ? toMulti(value) : String(Array.isArray(value) ? value[0] ?? '' : value ?? ''))
}

function hasSelectionOverflow(): boolean {
  const root = rootRef.value
  if (!root) return false
  const selection = root.querySelector<HTMLElement>('.el-select__selection')
  const wrapper = root.querySelector<HTMLElement>('.el-select__wrapper')
  const target = selection ?? wrapper
  if (!target) return false
  const horizontalOverflow = target.scrollWidth > target.clientWidth + 1
  const verticalOverflow = !!wrapper && !!selection && selection.scrollHeight > wrapper.clientHeight + 2
  return horizontalOverflow || verticalOverflow
}

async function recomputeCollapseTags() {
  if (recomputing) {
    recomputeAgain = true
    recomputeVersion += 1
    return
  }
  recomputing = true
  try {
    do {
      recomputeAgain = false
      const version = ++recomputeVersion
      let limit = normalizedMaxCollapseTags.value
      effectiveMaxCollapseTags.value = limit
      if (!props.multiple || !props.collapseTags || !props.collapseOnOverflow || toMulti(props.modelValue).length <= 1) {
        continue
      }
      await nextTick()
      while (version === recomputeVersion && limit > 1 && hasSelectionOverflow()) {
        limit -= 1
        effectiveMaxCollapseTags.value = limit
        await nextTick()
      }
    } while (recomputeAgain)
  } finally {
    recomputing = false
  }
}

function scheduleCollapseRecompute() {
  void recomputeCollapseTags()
}

onMounted(() => {
  scheduleCollapseRecompute()
  if (typeof ResizeObserver !== 'undefined' && rootRef.value) {
    resizeObserver = new ResizeObserver(scheduleCollapseRecompute)
    resizeObserver.observe(rootRef.value)
  }
})

onBeforeUnmount(() => {
  recomputeVersion += 1
  resizeObserver?.disconnect()
})

watch(
  () => [
    props.modelValue,
    props.options,
    props.multiple,
    props.collapseTags,
    props.collapseOnOverflow,
    props.maxCollapseTags,
  ],
  scheduleCollapseRecompute,
)
</script>

<template>
  <div
    ref="rootRef"
    class="app-filter-select"
    :class="{ 'app-filter-select--multiple': multiple }"
  >
    <el-select
      v-model="selected"
      class="app-filter-select__control"
      :multiple="multiple"
      :clearable="clearable"
      :filterable="filterable"
      :collapse-tags="multiple && collapseTags"
      :collapse-tags-tooltip="multiple && collapseTags"
      :max-collapse-tags="effectiveMaxCollapseTags"
      :fit-input-width="true"
      :disabled="disabled"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      @change="onChange"
    >
      <el-option
        v-for="item in options"
        :key="item.value"
        :label="item.label"
        :value="item.value"
      />
    </el-select>
  </div>
</template>

<style scoped>
.app-filter-select {
  width: 100%;
  min-width: 0;
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
.app-filter-select--multiple .app-filter-select__control :deep(.el-select__wrapper) {
  overflow: hidden;
}
.app-filter-select__control :deep(.el-select__selection) {
  min-width: 0;
}
.app-filter-select--multiple .app-filter-select__control :deep(.el-select__selection) {
  overflow: hidden;
}
</style>

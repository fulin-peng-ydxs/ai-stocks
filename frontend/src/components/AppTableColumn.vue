<script setup lang="ts">
import { computed, useAttrs, useSlots } from 'vue'
import {
  resolveAdaptiveColumnWidth,
  type AdaptiveColumnRole,
} from '@/components/table/adaptiveColumnWidth'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  role?: AdaptiveColumnRole
  type?: string
  label?: string
  prop?: string
  /** 紧随表头标签的日期、单位或短口径摘要；说明性长文本应放帮助提示。 */
  headerMeta?: string
  /** 单元格主内容前的紧凑控件数量；组件据此统一预留列宽并对齐表头。 */
  leadingControls?: number
}>()

const attrs = useAttrs()
const slots = useSlots()
const forwardedAttrs = computed(() => {
  const { width: _width, minWidth: _minWidth, 'min-width': _kebabMinWidth, ...rest } = attrs
  return rest
})
const forwardedSlotNames = computed(() => Object.keys(slots).filter((name) => name !== 'header'))
const sizing = computed(() => resolveAdaptiveColumnWidth({
  ...props,
  sortable: attrs.sortable !== undefined && attrs.sortable !== false,
  filterable: attrs.filters !== undefined || attrs['filter-method'] !== undefined,
  customHeader: Boolean(slots.header),
}))
const headerTitle = computed(() => [props.label, props.headerMeta].filter(Boolean).join(' · '))
const headerStyle = computed(() => ({
  '--app-table-column-header-indent': `${sizing.value.headerIndent ?? 0}px`,
}))
</script>

<template>
  <el-table-column
    v-bind="forwardedAttrs"
    :type="type"
    :label="label"
    :prop="prop"
    :width="sizing.width"
    :min-width="sizing.minWidth"
  >
    <template v-if="$slots.header" #header="scope">
      <slot name="header" v-bind="scope ?? {}" />
    </template>
    <template v-else-if="label || headerMeta" #header>
      <span
        class="app-table-column-header"
        :style="headerStyle"
        :title="sizing.headerCapped ? headerTitle : undefined"
      >
        <span v-if="label" class="app-table-column-header__label">{{ label }}</span>
        <span v-if="headerMeta" class="app-table-column-header__meta">{{ headerMeta }}</span>
      </span>
    </template>
    <template
      v-for="slotName in forwardedSlotNames"
      :key="slotName"
      #[slotName]="scope"
    >
      <slot :name="slotName" v-bind="scope ?? {}" />
    </template>
  </el-table-column>
</template>

<style scoped>
.app-table-column-header {
  display: inline-flex;
  overflow: hidden;
  min-width: 0;
  max-width: calc(100% - var(--app-table-column-header-indent, 0px));
  margin-left: var(--app-table-column-header-indent, 0);
  align-items: baseline;
  flex-direction: row;
  gap: var(--app-space-1);
  justify-content: center;
  line-height: var(--app-line-height-caption);
  white-space: nowrap;
}

.app-table-column-header__label,
.app-table-column-header__meta {
  overflow: hidden;
  max-width: 100%;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-table-column-header__meta {
  flex: 0 0 auto;
  color: var(--el-text-color-placeholder);
  font-size: var(--app-font-size-micro);
  font-weight: var(--app-font-weight-regular);
  line-height: var(--app-line-height-micro);
}
</style>

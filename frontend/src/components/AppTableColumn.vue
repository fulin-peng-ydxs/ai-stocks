<script setup lang="ts">
import {
  computed,
  defineComponent,
  provide,
  reactive,
  type PropType,
  useAttrs,
  useSlots,
} from 'vue'
import {
  resolveActionColumnWidth,
  resolveAdaptiveColumnWidth,
  type AdaptiveColumnRole,
} from '@/components/table/adaptiveColumnWidth'
import {
  ROW_ACTION_COLUMN_WIDTH_CONTEXT,
  type RowActionColumnWidthContext,
} from '@/components/table/rowActionColumnWidth'
import {
  ACTION_COLUMN_CLASS,
  OVERFLOW_AWARE_COLUMN_CLASS,
} from '@/components/table/cellVisualOverflow'

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
  /** 单元格内多选 AppFilterSelect 的目标可见标签数；列宽据此承载值与 +N。 */
  filterSelectVisibleTagCount?: number
  /** 单元格内多选 AppFilterSelect 的展示方式；count 只承载“已选 N”。 */
  filterSelectDisplayMode?: 'tags' | 'count'
}>()

const attrs = useAttrs()
const slots = useSlots()
const actionWidthRequests = reactive(new Map<symbol, number>())
const forwardedAttrs = computed(() => {
  const {
    width: _width,
    minWidth: _minWidth,
    'min-width': _kebabMinWidth,
    className: _className,
    'class-name': _kebabClassName,
    align: _align,
    headerAlign: _headerAlign,
    'header-align': _kebabHeaderAlign,
    showOverflowTooltip: _showOverflowTooltip,
    'show-overflow-tooltip': _kebabShowOverflowTooltip,
    ...rest
  } = attrs
  return rest
})
const forwardedSlotNames = computed(() => Object.keys(slots).filter((name) => name !== 'header'))
const sizing = computed(() => resolveAdaptiveColumnWidth({
  ...props,
  sortable: attrs.sortable !== undefined && attrs.sortable !== false,
  filterable: attrs.filters !== undefined || attrs['filter-method'] !== undefined,
  customHeader: Boolean(slots.header),
}))
const isActionColumn = computed(() => (
  sizing.value.role === 'action' || sizing.value.role === 'action-compact'
))
const overflowAware = computed(() => (
  !['structural', 'rank', 'action', 'action-compact'].includes(sizing.value.role)
))
const resolvedColumnClassName = computed(() => [
  attrs.className,
  attrs['class-name'],
  isActionColumn.value ? ACTION_COLUMN_CLASS : undefined,
  ['number', 'comparison-number', 'rank'].includes(sizing.value.role)
    ? 'app-table-column--tabular'
    : undefined,
  overflowAware.value ? OVERFLOW_AWARE_COLUMN_CLASS : undefined,
].filter(Boolean).join(' '))
const resolvedWidth = computed(() => {
  const defaultWidth = sizing.value.width
  if (!isActionColumn.value || defaultWidth === undefined) return defaultWidth
  return resolveActionColumnWidth(defaultWidth, actionWidthRequests.values())
})

const actionWidthContext: RowActionColumnWidthContext = {
  setMinimumWidth(source, width) {
    if (!isActionColumn.value) return
    actionWidthRequests.set(source, Math.max(0, width))
  },
  removeMinimumWidth(source) {
    actionWidthRequests.delete(source)
  },
}

// Element Plus 延后到表体组件中执行列 slot；用无 DOM 包装的中间组件把列级上下文
// 带到真实单元格渲染树，避免 slot 的异步消费切断 provide/inject 链路。
const RowActionWidthProvider = defineComponent({
  name: 'RowActionWidthProvider',
  props: {
    context: {
      type: Object as PropType<RowActionColumnWidthContext>,
      required: true,
    },
  },
  setup(providerProps, { slots: providerSlots }) {
    provide(ROW_ACTION_COLUMN_WIDTH_CONTEXT, providerProps.context)
    return () => providerSlots.default?.()
  },
})
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
    :width="resolvedWidth"
    :min-width="sizing.minWidth"
    :class-name="resolvedColumnClassName"
    :align="sizing.align"
    :header-align="sizing.align"
  >
    <template v-if="$slots.header" #header="scope">
      <slot name="header" v-bind="scope ?? {}" />
    </template>
    <template v-else-if="label || headerMeta" #header>
      <span
        class="app-table-column-header"
        :style="headerStyle"
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
      <RowActionWidthProvider
        v-if="slotName === 'default' && isActionColumn"
        :context="actionWidthContext"
      >
        <slot :name="slotName" v-bind="scope ?? {}" />
      </RowActionWidthProvider>
      <slot v-else :name="slotName" v-bind="scope ?? {}" />
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

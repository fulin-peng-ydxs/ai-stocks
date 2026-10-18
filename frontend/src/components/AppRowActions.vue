<script setup lang="ts">
import {
  APP_BOTTOM_END_FLOATING_PLACEMENT,
  APP_BOTTOM_FLOATING_FALLBACKS,
} from '@/utils/floatingPlacement'
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppActionHint from './AppActionHint.vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { getActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { hasPermission } from '@/utils/permission'
import {
  computeRowMinimumContentWidth,
  computeRowLayout,
  MORE_BUTTON_ESTIMATED_WIDTH,
  type AppRowAction,
  type AppRowActionMeasure,
  type AppRowActionType,
} from './rowActions'
import { ROW_ACTION_COLUMN_WIDTH_CONTEXT } from './table/rowActionColumnWidth'

const props = withDefaults(defineProps<{
  actions: AppRowAction[]
  inlineLimit?: number
  ariaLabel?: string
  emptyText?: string
  moreLabel?: string
  testId?: string
}>(), {
  inlineLimit: 3,
  ariaLabel: '行操作',
  emptyText: '—',
  moreLabel: '更多',
})

const auth = getActivePinia() ? useAuthStore() : null
const actionColumnWidth = inject(ROW_ACTION_COLUMN_WIDTH_CONTEXT, null)
const actionColumnWidthSource = Symbol('row-action-width')
type ButtonRef = HTMLElement | { $el?: HTMLElement } | null
const morePopover = ref<{ hide?: () => void } | null>(null)
const menuOpen = ref(false)

// ── 宽度自适应折叠 ──
const rootEl = ref<HTMLElement | null>(null)
const measureEl = ref<HTMLElement | null>(null)
const moreMeasureBtn = ref<ButtonRef>(null)
const widthMap = ref<Record<string, number>>({})
const availableWidth = ref(0)
const cellHorizontalInset = ref(0)
const moreWidth = ref(0)
let observer: ResizeObserver | null = null

// 筛选时各行需求撤销/重报可让列宽同帧先缩后扩；最终尺寸不变时，
// ResizeObserver 不会再次通知，动作组却可能已测到中间的窄尺寸。
// 固定列消费所属列的响应式预算；非表格动作组继续使用容器实测宽度。
const layoutWidth = computed(() => {
  const columnWidth = actionColumnWidth?.width.value
  return columnWidth === undefined
    ? availableWidth.value
    : Math.max(0, columnWidth - cellHorizontalInset.value)
})

function isAllowed(action: AppRowAction): boolean {
  if (action.visible === false) return false
  if (!action.permission) return true
  if (!auth) return false
  return hasPermission(auth.role, auth.permissions, action.permission)
}

const visibleActions = computed(() => props.actions.filter(isAllowed))
const actionMeasurementSignature = computed(() => visibleActions.value.map((action) => (
  [action.key, action.label, action.placement ?? 'auto', action.loading ? 'loading' : 'idle'].join('\u0000')
)).join('\u0001'))

const measuredActions = computed<AppRowActionMeasure[]>(() =>
  visibleActions.value.map((action) => {
    const width = widthMap.value[action.key]
    return { ...action, measured: width, measuredOk: width !== undefined }
  }),
)

const widthModeReady = computed(() => {
  if (visibleActions.value.length === 0 || layoutWidth.value <= 0) return false
  const fillable = visibleActions.value.filter((action) => action.placement !== 'more')
  if (fillable.length && fillable.some((action) => widthMap.value[action.key] === undefined)) {
    return false
  }
  return true
})

const layout = computed(() => {
  const limit = Math.max(0, props.inlineLimit)
  if (widthModeReady.value) {
    return computeRowLayout(measuredActions.value, layoutWidth.value, limit, moreWidth.value)
  }
  // 兜底：无实测宽度（jsdom / 测量不可用）时退化为纯数量逻辑
  const fillable = visibleActions.value.filter((action) => action.placement !== 'more')
  const inlineCount = Math.max(0, Math.min(fillable.length, limit))
  const hasMore =
    inlineCount < fillable.length ||
    visibleActions.value.some((action) => action.placement === 'more')
  return { inlineCount, hasMore }
})

const inlineMeasureActions = computed(() =>
  measuredActions.value.filter((action) => action.placement !== 'more').slice(0, layout.value.inlineCount),
)

const inlineActions = computed(() =>
  visibleActions.value.filter((action) => action.placement !== 'more').slice(0, layout.value.inlineCount),
)

const moreActions = computed(() => {
  const inlineKeys = new Set(inlineActions.value.map((action) => action.key))
  return visibleActions.value.filter((action) => (
    action.placement === 'more' || !inlineKeys.has(action.key)
  ))
})

function measure(): void {
  const parent = rootEl.value?.parentElement
  let padX = 0
  let borderX = 0
  if (parent) {
    const cs = getComputedStyle(parent)
    padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
    const cell = parent.closest('td')
    if (cell) {
      const cellStyle = getComputedStyle(cell)
      borderX = (parseFloat(cellStyle.borderLeftWidth) || 0)
        + (parseFloat(cellStyle.borderRightWidth) || 0)
    }
    availableWidth.value = Math.max(0, parent.clientWidth - padX)
  } else {
    availableWidth.value = 0
  }
  cellHorizontalInset.value = padX + borderX

  const buttons = measureEl.value?.querySelectorAll('.app-row-actions__button') ?? []
  const next: Record<string, number> = {}
  visibleActions.value.forEach((action, index) => {
    const btn = buttons[index] as HTMLElement | undefined
    if (btn && btn.offsetWidth > 0) next[action.key] = btn.offsetWidth
  })
  const moreEl = moreMeasureBtn.value
  const moreNode = moreEl
    ? moreEl instanceof HTMLElement ? moreEl : moreEl.$el ?? null
    : null
  const nextMoreWidth = moreNode && moreNode.offsetWidth > 0
    ? moreNode.offsetWidth
    : MORE_BUTTON_ESTIMATED_WIDTH
  moreWidth.value = nextMoreWidth

  widthMap.value = next
  const measured = visibleActions.value.map((action) => {
    const width = next[action.key]
    return { ...action, measured: width, measuredOk: width !== undefined }
  })
  const minimumContentWidth = computeRowMinimumContentWidth(
    measured,
    Math.max(0, props.inlineLimit),
    nextMoreWidth,
  )
  actionColumnWidth?.setMinimumWidth(
    actionColumnWidthSource,
    Math.ceil(minimumContentWidth + cellHorizontalInset.value),
  )
}

function setupObserver(): void {
  const parent = rootEl.value?.parentElement
  if (!parent || typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(() => measure())
  observer.observe(parent)
}

function teardownObserver(): void {
  observer?.disconnect()
  observer = null
}

watch(
  [actionMeasurementSignature, () => props.inlineLimit, () => props.moreLabel],
  () => { void nextTick(measure) },
)

onMounted(() => {
  void nextTick(() => {
    measure()
    setupObserver()
  })
})

function actionTone(action: AppRowAction, inlineIndex?: number): AppRowActionType {
  if (action.type) return action.type
  return inlineIndex === 0 ? 'primary' : 'default'
}

function actionClass(action: AppRowAction, inlineIndex?: number) {
  return [
    `is-tone-${actionTone(action, inlineIndex)}`,
    { 'is-loading': action.loading },
  ]
}

function actionTestId(action: AppRowAction): string | undefined {
  return action.testId ?? (props.testId ? `${props.testId}-${action.key}` : undefined)
}

function runAction(action: AppRowAction, event?: MouseEvent): void {
  if (action.disabled || action.loading) return
  action.onClick?.(event)
}

function closeMenu(): void {
  morePopover.value?.hide?.()
  menuOpen.value = false
}

function runMenuAction(action: AppRowAction, event: MouseEvent): void {
  event.stopPropagation()
  runAction(action, event)
  closeMenu()
}

onBeforeUnmount(() => {
  actionColumnWidth?.removeMinimumWidth(actionColumnWidthSource)
  teardownObserver()
})
</script>

<template>
  <div
    ref="rootEl"
    class="app-row-actions"
    role="group"
    :aria-label="ariaLabel"
    data-overflow-tooltip-disabled
    :data-testid="testId"
  >
    <template v-if="visibleActions.length">
      <AppActionHint
        v-for="(action, index) in inlineMeasureActions"
        :key="action.key"
        :text="action.tooltip"
        :disabled="action.disabled || action.loading"
        :label="action.label"
      >
        <el-button
          class="app-row-actions__button"
          :class="actionClass(action, index)"
          link
          size="small"
          :loading="action.loading"
          :disabled="action.disabled"
          :data-testid="actionTestId(action)"
          @click.stop="runAction(action, $event)"
        >
          {{ action.label }}
        </el-button>
      </AppActionHint>
      <el-popover
        v-if="moreActions.length"
        ref="morePopover"
        trigger="click"
        role="menu"
        :placement="APP_BOTTOM_END_FLOATING_PLACEMENT"
        :width="160"
        :show-arrow="false"
        :persistent="false"
        :popper-style="{ padding: '4px' }"
        popper-class="app-row-actions-popper"
        @before-enter="menuOpen = true"
        @after-leave="menuOpen = false"
        :fallback-placements="APP_BOTTOM_FLOATING_FALLBACKS"
      >
        <template #reference>
          <el-button
            class="app-row-actions__button app-row-actions__more"
            :class="{ 'is-open': menuOpen }"
            link
            size="small"
            :aria-expanded="menuOpen"
            aria-haspopup="menu"
            :data-testid="testId ? `${testId}-more` : undefined"
            @click.stop
          >
            {{ moreLabel }}
            <el-icon class="app-row-actions__more-icon"><ArrowDown /></el-icon>
          </el-button>
        </template>
        <div
          class="app-row-actions-menu"
          :data-testid="testId ? `${testId}-menu` : undefined"
          @click.stop
        >
          <AppActionHint
            v-for="action in moreActions"
            :key="action.key"
            :text="action.tooltip"
            :disabled="action.disabled || action.loading"
            :label="action.label"
          >
            <el-button
              class="app-row-actions-menu__item"
              :class="actionClass(action)"
              text
              size="small"
              :loading="action.loading"
              :disabled="action.disabled || action.loading"
              role="menuitem"
              :data-testid="actionTestId(action)"
              @click="runMenuAction(action, $event)"
            >
              {{ action.label }}
            </el-button>
          </AppActionHint>
        </div>
      </el-popover>
    </template>
    <span v-else class="app-row-actions__empty">{{ emptyText }}</span>
    <!-- 裁切测量副本的滚动溢出，内部仍按完整固有宽度测量，不能用 display:none。 -->
    <span v-if="visibleActions.length" class="app-row-actions__measure-clip" aria-hidden="true">
      <span
        ref="measureEl"
        class="app-row-actions__measure"
        aria-hidden="true"
        :data-testid="testId ? `${testId}-measure` : undefined"
      >
        <el-button
          v-for="(action, index) in measuredActions"
          :key="action.key"
          class="app-row-actions__button"
          :class="actionClass(action, index)"
          link
          size="small"
          :loading="action.loading"
        >
          {{ action.label }}
        </el-button>
        <el-button
          v-if="visibleActions.length"
          ref="moreMeasureBtn"
          class="app-row-actions__button app-row-actions__more"
          link
          size="small"
        >
          {{ moreLabel }}
          <el-icon class="app-row-actions__more-icon"><ArrowDown /></el-icon>
        </el-button>
      </span>
    </span>
  </div>
</template>

<style scoped>
.app-row-actions {
  position: relative;
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: var(--app-space-2);
  max-width: 100%;
  min-width: 0;
  white-space: nowrap;
  vertical-align: middle;
}

.app-row-actions__button {
  margin-left: 0 !important;
  min-height: 24px;
  padding: 0 5px !important;
  font-weight: var(--app-font-weight-section);
}

.app-row-actions__more-icon {
  margin-left: 2px;
  font-size: var(--app-icon-size-xs);
}

.app-row-actions__empty {
  color: var(--el-text-color-secondary);
}

.app-row-actions__measure-clip {
  position: absolute;
  top: 0;
  left: 0;
  width: 0;
  height: 0;
  overflow: clip;
  visibility: hidden;
  pointer-events: none;
}

.app-row-actions__measure {
  position: absolute;
  top: 0;
  left: 0;
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: var(--app-space-2);
  width: max-content;
  max-width: none;
  visibility: hidden;
  pointer-events: none;
  white-space: nowrap;
  z-index: -1;
}

.app-row-actions-menu {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}

.app-row-actions-menu :deep(.app-action-hint) { width: 100%; }

.app-row-actions-menu__item {
  width: 100%;
  min-height: 28px;
  justify-content: flex-start;
  margin-left: 0 !important;
  padding: 0 10px !important;
  border-radius: 4px;
  font-size: var(--app-font-size-body);
  text-align: left;
}
</style>

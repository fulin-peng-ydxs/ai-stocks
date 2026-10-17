<script setup lang="ts">
import { keyboardRangeValue } from '@/utils/keyboard'
import {
  computed,
  inject,
  nextTick,
  onBeforeUnmount,
  onMounted,
  provide,
  ref,
  useAttrs,
  watch,
} from 'vue'
import PageDrawer from '@/components/PageDrawer.vue'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { elementVisualScale, viewportDeltaToLayoutPixels } from '@/utils/displayScaleGeometry'
import { createLatestAnimationFrame } from '@/utils/latestAnimationFrame'
import { adaptiveWorkspaceHeight } from '@/layout/marketWorkspaceSizing'
import {
  WORKSPACE_PROFILE_SIZE,
  WORKSPACE_RESIZE_ACTIVE,
} from '@/layout/workspaceResizeContext'
import {
  closestMasterDetailRatioProfile,
  MASTER_DETAIL_RATIO_DEFAULT,
  MASTER_DETAIL_RATIO_MAX,
  MASTER_DETAIL_RATIO_MIN,
  type MasterDetailRatioRuntimeSample,
} from '@/layout/masterDetailRatioProfiles'

const SPLITTER_WIDTH = 12
const KEYBOARD_STEP = 16

const props = withDefaults(defineProps<{
  secondaryVisible: boolean
  compact?: boolean
  defaultPrimaryRatio?: number
  primaryRatioProfiles?: unknown
  primaryMinWidth?: number
  primaryOnlyMinWidth?: number
  secondaryMinWidth?: number
  compactMaxWidth?: number
  minHeight?: number
  compactMinHeight?: number
  adaptiveHeight?: boolean
  secondaryDrawerTitle?: string
  separatorLabel?: string
  drawerClass?: string
  testIdPrefix?: string
  splitterTestId?: string
  secondaryDrawerTestId?: string
}>(), {
  compact: false,
  defaultPrimaryRatio: MASTER_DETAIL_RATIO_DEFAULT,
  primaryMinWidth: 360,
  primaryOnlyMinWidth: 360,
  secondaryMinWidth: 240,
  compactMaxWidth: 720,
  minHeight: 0,
  compactMinHeight: 0,
  secondaryDrawerTitle: '辅助信息',
  separatorLabel: '调整左右栏宽度',
  drawerClass: 'app-split-workspace-drawer',
  testIdPrefix: 'split-workspace',
})
defineOptions({ inheritAttrs: false })
const attrs = useAttrs()

const emit = defineEmits<{
  'update:secondaryVisible': [visible: boolean]
  primaryRatioChange: [ratio: number]
  primaryRatioSampleChange: [sample: MasterDetailRatioRuntimeSample | undefined]
  compactChange: [compact: boolean]
  compactSecondaryClose: []
}>()

defineSlots<{
  primary: (props: { compact: boolean }) => unknown
  secondary: () => unknown
}>()

const workspaceEl = ref<HTMLElement | null>(null)
const workspaceWidth = ref(0)
const workspaceProfileSize = ref({ width: 0, height: 0 })
const measuredAdaptiveHeight = ref<number | null>(null)
const ancestorWorkspaceResizeActive = inject(WORKSPACE_RESIZE_ACTIVE, ref(false))
const localWorkspaceResizeActive = ref(false)
const workspaceResizeActive = computed(() => (
  ancestorWorkspaceResizeActive.value || localWorkspaceResizeActive.value
))
provide(WORKSPACE_RESIZE_ACTIVE, workspaceResizeActive)
provide(WORKSPACE_PROFILE_SIZE, workspaceProfileSize)
const matchedProfile = computed(() => closestMasterDetailRatioProfile(
  props.primaryRatioProfiles,
  workspaceWidth.value,
))

function clampRatio(value: number): number {
  const finite = Number.isFinite(value) ? Math.round(value) : MASTER_DETAIL_RATIO_DEFAULT
  return Math.min(MASTER_DETAIL_RATIO_MAX, Math.max(MASTER_DETAIL_RATIO_MIN, finite))
}

const configuredPrimaryRatio = computed(() => clampRatio(
  matchedProfile.value?.ratio ?? props.defaultPrimaryRatio,
))
const sessionAdjusted = ref(false)
const sessionAdjustedAtWidth = ref(0)
const compactSecondaryOpen = ref(false)
const autoCompact = computed(() => props.compact || (
  workspaceWidth.value > 0 && workspaceWidth.value <= props.compactMaxWidth
))
const currentMinWidth = computed(() => workspaceWidth.value
  ? Math.max(
      props.primaryMinWidth,
      Math.round(workspaceWidth.value * MASTER_DETAIL_RATIO_MIN / 100),
    )
  : props.primaryMinWidth)
const currentMaxWidth = computed(() => {
  if (!workspaceWidth.value) return currentMinWidth.value
  const contentSafeMax = workspaceWidth.value - props.secondaryMinWidth - SPLITTER_WIDTH
  const ratioMax = Math.round(workspaceWidth.value * MASTER_DETAIL_RATIO_MAX / 100)
  return Math.max(currentMinWidth.value, Math.min(contentSafeMax, ratioMax))
})

function clampSessionWidth(value: number): number {
  return Math.min(currentMaxWidth.value, Math.max(currentMinWidth.value, Math.round(value)))
}

function responsivePrimaryWidth(ratio: number): number {
  if (!workspaceWidth.value) return 1200
  return clampSessionWidth(workspaceWidth.value * ratio / 100)
}

// 配置只提供默认比例；分隔条操作始终停留在当前会话，显式保存由页面设置承接。
const configuredPrimaryWidth = computed(() => responsivePrimaryWidth(configuredPrimaryRatio.value))
const configuredEffectivePrimaryRatio = computed(() => workspaceWidth.value
  ? clampRatio(configuredPrimaryWidth.value / workspaceWidth.value * 100)
  : configuredPrimaryRatio.value)
const primaryWidth = useDefaultedSessionValue(configuredPrimaryWidth, {
  shouldSync: () => !sessionAdjusted.value,
  onSynced: () => { sessionAdjusted.value = false },
})
const renderSecondary = computed(() => props.secondaryVisible && !autoCompact.value)
const workspaceStyle = computed(() => ({
  gridTemplateColumns: renderSecondary.value
    ? `${clampSessionWidth(primaryWidth.value)}px ${SPLITTER_WIDTH}px minmax(${props.secondaryMinWidth}px, 1fr)`
    : 'minmax(0, 1fr)',
  minWidth: autoCompact.value
    ? '0'
    : `${renderSecondary.value
      ? props.primaryMinWidth + SPLITTER_WIDTH + props.secondaryMinWidth
      : props.primaryOnlyMinWidth}px`,
  minHeight: `${autoCompact.value ? props.compactMinHeight : props.minHeight}px`,
  height: props.adaptiveHeight && measuredAdaptiveHeight.value != null
    ? `${measuredAdaptiveHeight.value}px`
    : undefined,
}))
const drawerClassName = computed(() => [
  'app-split-workspace-drawer',
  props.drawerClass === 'app-split-workspace-drawer' ? '' : props.drawerClass,
].filter(Boolean).join(' '))
const effectivePrimaryWidth = computed(() => clampSessionWidth(primaryWidth.value))
const effectivePrimaryRatio = computed(() => workspaceWidth.value
  ? clampRatio(effectivePrimaryWidth.value / workspaceWidth.value * 100)
  : configuredPrimaryRatio.value)
const currentRatioSample = computed<MasterDetailRatioRuntimeSample | undefined>(() => (
  autoCompact.value || !workspaceWidth.value
    ? undefined
    : {
        width: workspaceWidth.value,
        ratio: effectivePrimaryRatio.value,
        configuredRatio: configuredEffectivePrimaryRatio.value,
      }
))

let resizeObserver: ResizeObserver | null = null
let adaptiveResizeObserver: ResizeObserver | null = null
let adaptiveScrollport: HTMLElement | null = null
let adaptiveFrame = 0
let drag: {
  pointerId: number
  startX: number
  startWidth: number
  visualScale: number
} | null = null

const primaryWidthFrame = createLatestAnimationFrame<number>((value) => {
  sessionAdjusted.value = true
  sessionAdjustedAtWidth.value = workspaceWidth.value
  primaryWidth.value = clampSessionWidth(value)
})

function isVerticalScrollport(element: HTMLElement): boolean {
  const overflowY = window.getComputedStyle(element).overflowY
  return overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay'
}

function findVerticalScrollport(element: HTMLElement): HTMLElement {
  let current = element.parentElement
  while (current) {
    if (isVerticalScrollport(current)) return current
    current = current.parentElement
  }
  return document.getElementById('app') ?? document.documentElement
}

function measureAdaptiveHeight(): void {
  adaptiveFrame = 0
  const element = workspaceEl.value
  if (!props.adaptiveHeight || !element) {
    measuredAdaptiveHeight.value = null
    return
  }
  const scrollport = findVerticalScrollport(element)
  const scrollportRect = scrollport.getBoundingClientRect()
  const elementRect = element.getBoundingClientRect()
  const contentTop = viewportDeltaToLayoutPixels(
    elementRect.top - scrollportRect.top,
    element,
    'y',
  ) - scrollport.clientTop + scrollport.scrollTop
  const bottomInset = Number.parseFloat(window.getComputedStyle(scrollport).paddingBottom) || 0
  measuredAdaptiveHeight.value = adaptiveWorkspaceHeight({
    scrollportHeight: scrollport.clientHeight,
    contentTop,
    minHeight: autoCompact.value ? props.compactMinHeight : props.minHeight,
    bottomInset,
  })
}

function scheduleAdaptiveHeightMeasure(): void {
  if (adaptiveFrame) cancelAnimationFrame(adaptiveFrame)
  adaptiveFrame = requestAnimationFrame(measureAdaptiveHeight)
}

function bindAdaptiveHeightMeasurement(): void {
  adaptiveResizeObserver?.disconnect()
  adaptiveResizeObserver = null
  adaptiveScrollport = null
  if (!props.adaptiveHeight || !workspaceEl.value) {
    measuredAdaptiveHeight.value = null
    return
  }
  adaptiveScrollport = findVerticalScrollport(workspaceEl.value)
  if (typeof ResizeObserver !== 'undefined') {
    adaptiveResizeObserver = new ResizeObserver(scheduleAdaptiveHeightMeasure)
    adaptiveResizeObserver.observe(adaptiveScrollport)
    const parent = workspaceEl.value.parentElement
    if (parent && parent !== adaptiveScrollport) adaptiveResizeObserver.observe(parent)
  }
  scheduleAdaptiveHeightMeasure()
}

function resetPrimaryWidth(): void {
  sessionAdjusted.value = false
  sessionAdjustedAtWidth.value = 0
  primaryWidth.value = configuredPrimaryWidth.value
}

function updateWorkspaceWidth(): void {
  const nextWidth = workspaceEl.value?.clientWidth ?? 0
  const nextHeight = workspaceEl.value?.clientHeight ?? 0
  workspaceProfileSize.value = { width: nextWidth, height: nextHeight }
  if (
    sessionAdjusted.value
    && sessionAdjustedAtWidth.value > 0
    && Math.abs(nextWidth - sessionAdjustedAtWidth.value) / sessionAdjustedAtWidth.value > 0.15
  ) {
    sessionAdjusted.value = false
    sessionAdjustedAtWidth.value = 0
  }
  workspaceWidth.value = nextWidth
  primaryWidth.value = !sessionAdjusted.value
    ? configuredPrimaryWidth.value
    : clampSessionWidth(primaryWidth.value)
  // 外部容器或显示器比例在手势期间变化时刷新基准；普通 pointermove 不再读布局。
  if (drag) drag.visualScale = elementVisualScale(workspaceEl.value, 'x')
}

function onPointerMove(event: PointerEvent): void {
  if (!drag || event.pointerId !== drag.pointerId) return
  const layoutDelta = (event.clientX - drag.startX) / drag.visualScale
  primaryWidthFrame.schedule(drag.startWidth + layoutDelta)
}

function finishDrag(event?: PointerEvent): void {
  if (!drag || (event && event.pointerId !== drag.pointerId)) return
  primaryWidthFrame.flush()
  drag = null
  localWorkspaceResizeActive.value = false
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', finishDrag)
  window.removeEventListener('pointercancel', finishDrag)
  document.body.classList.remove('app-split-workspace-is-resizing')
}

function startDrag(event: PointerEvent): void {
  if (drag) finishDrag()
  drag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startWidth: primaryWidth.value,
    visualScale: elementVisualScale(workspaceEl.value, 'x'),
  }
  localWorkspaceResizeActive.value = true
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  document.body.classList.add('app-split-workspace-is-resizing')
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', finishDrag)
  window.addEventListener('pointercancel', finishDrag)
}

function onSeparatorKeydown(event: KeyboardEvent): void {
  const next = keyboardRangeValue(event, primaryWidth.value, {
    axis: 'horizontal', step: KEYBOARD_STEP,
    min: currentMinWidth.value, max: currentMaxWidth.value,
  })
  if (next === undefined) return
  sessionAdjusted.value = true
  sessionAdjustedAtWidth.value = workspaceWidth.value
  primaryWidth.value = clampSessionWidth(next)
}

function openCompactSecondary(): boolean {
  if (!autoCompact.value) return false
  if (!props.secondaryVisible) emit('update:secondaryVisible', true)
  compactSecondaryOpen.value = true
  return true
}

function closeCompactSecondary(): void {
  compactSecondaryOpen.value = false
}

watch(
  [() => props.defaultPrimaryRatio, () => props.primaryRatioProfiles],
  resetPrimaryWidth,
  { deep: true },
)
watch(autoCompact, (compact) => {
  if (!compact) compactSecondaryOpen.value = false
  emit('compactChange', compact)
}, { immediate: true })
watch(effectivePrimaryRatio, (value) => emit('primaryRatioChange', value), { immediate: true })
watch(currentRatioSample, (value) => emit('primaryRatioSampleChange', value), { immediate: true })
watch(
  [() => props.adaptiveHeight, autoCompact],
  () => { void nextTick(bindAdaptiveHeightMeasurement) },
)

defineExpose({ openCompactSecondary, closeCompactSecondary })

onMounted(() => {
  updateWorkspaceWidth()
  if (typeof ResizeObserver !== 'undefined' && workspaceEl.value) {
    resizeObserver = new ResizeObserver(updateWorkspaceWidth)
    resizeObserver.observe(workspaceEl.value)
  }
  bindAdaptiveHeightMeasurement()
  window.addEventListener('resize', scheduleAdaptiveHeightMeasure)
})

onBeforeUnmount(() => {
  finishDrag()
  primaryWidthFrame.cancel()
  resizeObserver?.disconnect()
  resizeObserver = null
  adaptiveResizeObserver?.disconnect()
  adaptiveResizeObserver = null
  adaptiveScrollport = null
  if (adaptiveFrame) cancelAnimationFrame(adaptiveFrame)
  window.removeEventListener('resize', scheduleAdaptiveHeightMeasure)
})
</script>

<template>
  <div
    v-bind="attrs"
    ref="workspaceEl"
    class="app-split-workspace"
    :class="{
      'app-split-workspace--primary-only': !renderSecondary,
      'app-split-workspace--compact': autoCompact,
    }"
    :style="workspaceStyle"
  >
    <div class="app-split-workspace__primary">
      <slot name="primary" :compact="autoCompact" />
    </div>

    <div
      v-if="renderSecondary"
      class="app-split-workspace__splitter"
      role="separator"
      tabindex="0"
      aria-orientation="vertical"
      :aria-label="separatorLabel"
      :aria-valuemin="currentMinWidth"
      :aria-valuemax="currentMaxWidth"
      :aria-valuenow="clampSessionWidth(primaryWidth)"
      :data-testid="splitterTestId || `${testIdPrefix}-splitter`"
      @pointerdown="startDrag"
      @keydown="onSeparatorKeydown"
      @dblclick="resetPrimaryWidth"
    >
      <span aria-hidden="true" />
    </div>

    <div v-if="renderSecondary" class="app-split-workspace__secondary">
      <slot name="secondary" />
    </div>
  </div>

  <PageDrawer
    v-if="autoCompact"
    v-model="compactSecondaryOpen"
    :title="secondaryDrawerTitle"
    size="full"
    :body-scroll="false"
    body-layout="fill"
    :modal-class="drawerClassName"
    :data-testid="secondaryDrawerTestId || `${testIdPrefix}-secondary-drawer`"
    @closed="emit('compactSecondaryClose')"
  >
    <div class="app-split-workspace__drawer-secondary">
      <slot name="secondary" />
    </div>
  </PageDrawer>
</template>

<style scoped>
.app-split-workspace {
  display: grid;
  gap: 0;
  min-height: 0;
  height: 100%;
  overflow-x: auto;
}
.app-split-workspace--compact {
  overflow-x: hidden;
}
.app-split-workspace__primary,
.app-split-workspace__secondary {
  display: flex;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.app-split-workspace__primary > :deep(*),
.app-split-workspace__secondary > :deep(*),
.app-split-workspace__drawer-secondary > :deep(*) {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
}
.app-split-workspace__drawer-secondary {
  display: flex;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
}
.app-split-workspace__splitter {
  position: relative;
  min-width: 0;
  cursor: col-resize;
  touch-action: none;
  outline: none;
}
.app-split-workspace__splitter::before {
  position: absolute;
  inset: 0 5px;
  content: '';
  background: var(--el-border-color-lighter);
  transition: background-color 0.15s, box-shadow 0.15s;
}
.app-split-workspace__splitter > span {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 3px;
  height: 36px;
  border-radius: 2px;
  background: var(--el-border-color-darker);
  transform: translate(-50%, -50%);
}
.app-split-workspace__splitter:hover::before,
.app-split-workspace__splitter:focus-visible::before {
  background: var(--el-color-primary-light-7);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-5);
}
.app-split-workspace__splitter:focus-visible > span {
  background: var(--el-color-primary);
}
@media (prefers-reduced-motion: reduce) {
  .app-split-workspace__splitter::before {
    transition: none;
  }
}
</style>

<style>
body.app-split-workspace-is-resizing {
  cursor: col-resize;
  user-select: none;
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import AppIconButton from '@/components/AppIconButton.vue'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { viewportDeltaToLayoutPixels } from '@/utils/displayScaleGeometry'

const MASTER_MIN_WIDTH = 360
const MASTER_MAX_WIDTH = 1200
const DETAIL_MIN_WIDTH = 240
const SPLITTER_WIDTH = 12
const KEYBOARD_STEP = 16

const props = defineProps<{
  analysisVisible: boolean
  compact?: boolean
  eyebrow: string
  title: string
  meta?: string
  listAriaLabel?: string
  defaultMasterWidth?: number
  testIdPrefix?: string
}>()

const emit = defineEmits<{
  'update:analysisVisible': [visible: boolean]
  masterWidthChange: [width: number]
}>()

function toggleAnalysis(): void {
  emit('update:analysisVisible', !props.analysisVisible)
}

const renderAnalysis = computed(() => props.analysisVisible && !props.compact)
const testIdPrefix = computed(() => props.testIdPrefix || 'market')
const workspaceEl = ref<HTMLElement | null>(null)
const workspaceWidth = ref(0)
const configuredMasterWidth = computed(() => clampWidth(props.defaultMasterWidth ?? MASTER_MAX_WIDTH))
// 抽屉配置只提供默认值；分隔条始终只改当前会话值，不反写持久层。
const masterWidth = useDefaultedSessionValue(configuredMasterWidth)
let resizeObserver: ResizeObserver | null = null
let drag: { pointerId: number; startX: number; startWidth: number } | null = null

function clampWidth(value: number): number {
  const finite = Number.isFinite(value) ? Math.round(value) : MASTER_MAX_WIDTH
  return Math.min(MASTER_MAX_WIDTH, Math.max(MASTER_MIN_WIDTH, finite))
}

const currentMaxWidth = computed(() => {
  if (!workspaceWidth.value) return MASTER_MAX_WIDTH
  return Math.max(
    MASTER_MIN_WIDTH,
    Math.min(MASTER_MAX_WIDTH, workspaceWidth.value - DETAIL_MIN_WIDTH - SPLITTER_WIDTH),
  )
})

function clampSessionWidth(value: number): number {
  return Math.min(currentMaxWidth.value, Math.max(MASTER_MIN_WIDTH, Math.round(value)))
}

const workspaceStyle = computed(() => renderAnalysis.value
  ? { gridTemplateColumns: `${clampSessionWidth(masterWidth.value)}px ${SPLITTER_WIDTH}px minmax(${DETAIL_MIN_WIDTH}px, 1fr)` }
  : undefined)
const effectiveMasterWidth = computed(() => clampSessionWidth(masterWidth.value))

watch(effectiveMasterWidth, (value) => emit('masterWidthChange', value), { immediate: true })

function updateWorkspaceWidth(): void {
  workspaceWidth.value = workspaceEl.value?.clientWidth ?? 0
  masterWidth.value = clampSessionWidth(masterWidth.value)
}

function onPointerMove(event: PointerEvent): void {
  if (!drag || event.pointerId !== drag.pointerId) return
  const layoutDelta = viewportDeltaToLayoutPixels(
    event.clientX - drag.startX,
    workspaceEl.value,
    'x',
  )
  masterWidth.value = clampSessionWidth(drag.startWidth + layoutDelta)
}

function finishDrag(event?: PointerEvent): void {
  if (!drag || (event && event.pointerId !== drag.pointerId)) return
  drag = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', finishDrag)
  window.removeEventListener('pointercancel', finishDrag)
  document.body.classList.remove('market-master-detail-is-resizing')
}

function startDrag(event: PointerEvent): void {
  if (drag) finishDrag()
  drag = { pointerId: event.pointerId, startX: event.clientX, startWidth: masterWidth.value }
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  document.body.classList.add('market-master-detail-is-resizing')
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', finishDrag)
  window.addEventListener('pointercancel', finishDrag)
}

function onSeparatorKeydown(event: KeyboardEvent): void {
  let next: number | undefined
  if (event.key === 'ArrowLeft') next = masterWidth.value - KEYBOARD_STEP
  if (event.key === 'ArrowRight') next = masterWidth.value + KEYBOARD_STEP
  if (event.key === 'Home') next = MASTER_MIN_WIDTH
  if (event.key === 'End') next = currentMaxWidth.value
  if (next === undefined) return
  event.preventDefault()
  masterWidth.value = clampSessionWidth(next)
}

onMounted(() => {
  updateWorkspaceWidth()
  if (typeof ResizeObserver !== 'undefined' && workspaceEl.value) {
    resizeObserver = new ResizeObserver(updateWorkspaceWidth)
    resizeObserver.observe(workspaceEl.value)
  }
})

onBeforeUnmount(() => {
  finishDrag()
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div
    ref="workspaceEl"
    class="market-master-detail"
    :class="{ 'market-master-detail--list-only': !renderAnalysis }"
    :style="workspaceStyle"
  >
    <section class="market-list-panel" :aria-label="listAriaLabel || title">
      <header class="market-list-head">
        <div>
          <div class="market-panel-eyebrow">{{ eyebrow }}</div>
          <h3 class="app-section-title">{{ title }}</h3>
        </div>
        <div class="market-list-actions">
          <span v-if="meta" class="app-caption-text">{{ meta }}</span>
          <AppIconButton
            v-if="!compact"
            :label="analysisVisible ? '收起走势分析，仅看列表' : '显示走势分析'"
            :data-testid="analysisVisible ? `${testIdPrefix}-hide-analysis` : `${testIdPrefix}-show-analysis`"
            :native-title="false"
            @click="toggleAnalysis"
          >
            <el-icon><DArrowRight v-if="analysisVisible" /><DArrowLeft v-else /></el-icon>
          </AppIconButton>
        </div>
      </header>
      <div class="market-list-body">
        <slot name="list" />
      </div>
    </section>

    <div
      v-if="renderAnalysis"
      class="market-master-detail__splitter"
      role="separator"
      tabindex="0"
      aria-orientation="vertical"
      aria-label="调整列表与走势分析宽度"
      :aria-valuemin="MASTER_MIN_WIDTH"
      :aria-valuemax="currentMaxWidth"
      :aria-valuenow="clampSessionWidth(masterWidth)"
      data-testid="market-master-detail-splitter"
      @pointerdown="startDrag"
      @keydown="onSeparatorKeydown"
      @dblclick="masterWidth = configuredMasterWidth"
    >
      <span aria-hidden="true" />
    </div>

    <slot v-if="renderAnalysis" name="analysis" />
  </div>
</template>

<style scoped>
.market-master-detail {
  display: grid;
  grid-template-columns: 1200px 12px minmax(240px, 1fr);
  gap: 0;
  min-width: 612px;
  min-height: 0;
  height: 100%;
  overflow-x: auto;
}
.market-master-detail__splitter {
  position: relative;
  min-width: 0;
  cursor: col-resize;
  touch-action: none;
  outline: none;
}
.market-master-detail__splitter::before {
  position: absolute;
  inset: 0 5px;
  content: '';
  background: var(--el-border-color-lighter);
  transition: background-color 0.15s, box-shadow 0.15s;
}
.market-master-detail__splitter > span {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 3px;
  height: 36px;
  border-radius: 2px;
  background: var(--el-border-color-darker);
  transform: translate(-50%, -50%);
}
.market-master-detail__splitter:hover::before,
.market-master-detail__splitter:focus-visible::before {
  background: var(--el-color-primary-light-7);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-5);
}
.market-master-detail__splitter:focus-visible > span {
  background: var(--el-color-primary);
}
.market-master-detail--list-only {
  grid-template-columns: minmax(0, 1fr);
  min-width: 640px;
}
.market-list-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
}
.market-list-head {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-height: 64px;
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 42%, var(--el-bg-color));
}
.market-panel-eyebrow {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.market-list-head h3 {
  margin: 0;
}
.market-list-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.market-list-actions > span {
  max-width: 180px;
  color: var(--el-text-color-secondary);
  text-align: right;
}
.market-list-body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}
.market-list-body :deep(.app-data-table) {
  flex: 1 1 auto;
  min-height: 0;
}
:deep(.el-table__row.stock-analysis-row--active > td.el-table__cell) {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, var(--el-bg-color));
}
:deep(.el-table__row.stock-analysis-row--active > td:first-child) {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
@media (max-width: 1180px) {
  .market-list-actions > span {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .market-master-detail__splitter::before {
    transition: none;
  }
}
</style>

<style>
body.market-master-detail-is-resizing {
  cursor: col-resize;
  user-select: none;
}
</style>

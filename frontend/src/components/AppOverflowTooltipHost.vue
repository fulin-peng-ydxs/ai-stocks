<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  findOverflowTooltipTarget,
  overflowTooltipContent,
} from '@/components/overflow/overflowTooltip'
import { useTooltipInputModality } from '@/composables/useTooltipInputModality'
import { APP_HOVER_TOOLTIP_DELAY_MS } from '@/components/overflow/tooltipTiming'

const visible = ref(false)
const content = ref('')
const virtualRef = ref<HTMLElement>()
const contentRef = ref<HTMLElement>()
const contentTruncated = ref(false)
let hoverTarget: HTMLElement | null = null
let focusTarget: HTMLElement | null = null
const modality = useTooltipInputModality(dismissCurrent)
let hoverTimer: ReturnType<typeof setTimeout> | null = null
let contentResizeObserver: ResizeObserver | null = null

function measureContentOverflow(): void {
  const element = contentRef.value
  contentTruncated.value = Boolean(
    visible.value && element && element.scrollHeight > element.clientHeight + 1,
  )
}

watch([content, visible], async () => {
  await nextTick()
  measureContentOverflow()
}, { flush: 'post' })

watch(contentRef, async (element, previous) => {
  if (previous) contentResizeObserver?.unobserve(previous)
  if (element) contentResizeObserver?.observe(element)
  await nextTick()
  measureContentOverflow()
}, { flush: 'post' })

function clearHoverTimer(): void {
  if (hoverTimer == null) return
  clearTimeout(hoverTimer)
  hoverTimer = null
}

function showFor(element: HTMLElement): void {
  if (!element.isConnected || findOverflowTooltipTarget(element) !== element) { hideCurrent(); return }
  const nextContent = overflowTooltipContent(element)
  if (!nextContent) return
  virtualRef.value = element
  contentTruncated.value = false
  content.value = nextContent
  visible.value = true
}

function hideCurrent(): void {
  visible.value = false
  contentTruncated.value = false
  virtualRef.value = undefined
  content.value = ''
}

function scheduleHover(element: HTMLElement): void {
  clearHoverTimer()
  hoverTimer = setTimeout(() => {
    hoverTimer = null
    if (hoverTarget === element && element.isConnected && !focusTarget) showFor(element)
  }, APP_HOVER_TOOLTIP_DELAY_MS)
}

function syncVisibleTarget(): void {
  const next = focusTarget || hoverTarget
  if (next) {
    showFor(next)
    return
  }
  hideCurrent()
}

function onMouseOver(event: MouseEvent): void {
  const next = findOverflowTooltipTarget(event.target)
  if (!next || hoverTarget === next) return
  hoverTarget = next
  if (focusTarget) return
  hideCurrent()
  scheduleHover(next)
}

function matchesHoverTarget(target: EventTarget | null): boolean {
  return Boolean(
    hoverTarget
    && target instanceof Node
    && (hoverTarget.contains(target) || findOverflowTooltipTarget(target) === hoverTarget),
  )
}

function onMouseMove(event: MouseEvent): void {
  if (!hoverTarget || focusTarget) return
  if (matchesHoverTarget(event.target)) {
    if (visible.value) hideCurrent()
    scheduleHover(hoverTarget)
  }
}

function onMouseOut(event: MouseEvent): void {
  if (!hoverTarget) return
  if (!matchesHoverTarget(event.target) || matchesHoverTarget(event.relatedTarget)) return
  hoverTarget = null
  clearHoverTimer()
  syncVisibleTarget()
}

function onFocusIn(event: FocusEvent): void {
  // 鼠标点击也会让按钮获得焦点；只有键盘焦点可以持续展示提示。
  if (modality.isPointerInteraction()) return
  const next = findOverflowTooltipTarget(event.target)
    || (event.target instanceof Node && hoverTarget?.contains(event.target) ? hoverTarget : null)
  if (!next) return
  focusTarget = next
  clearHoverTimer()
  syncVisibleTarget()
}

function onFocusOut(event: FocusEvent): void {
  if (!focusTarget) return
  if (event.relatedTarget instanceof Node && focusTarget.contains(event.relatedTarget)) return
  focusTarget = null
  if (!hoverTarget) {
    hideCurrent()
    return
  }
  hideCurrent()
  scheduleHover(hoverTarget)
}

function onPointerDown(): void {
  dismissCurrent()
}

function dismissCurrent(): void {
  focusTarget = null
  hoverTarget = null
  clearHoverTimer()
  hideCurrent()
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape') dismissCurrent()
}

onMounted(() => {
  // 捕获阶段先清理，设置抽屉等控件可能阻止事件冒泡。
  document.addEventListener('pointerdown', onPointerDown, true)
  document.addEventListener('keydown', onKeyDown, true)
  document.addEventListener('click', dismissCurrent, true)
  document.addEventListener('mouseover', onMouseOver)
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseout', onMouseOut)
  document.addEventListener('focusin', onFocusIn)
  document.addEventListener('focusout', onFocusOut)
  window.addEventListener('resize', dismissCurrent)
  if (typeof ResizeObserver !== 'undefined') {
    contentResizeObserver = new ResizeObserver(measureContentOverflow)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.removeEventListener('keydown', onKeyDown, true)
  document.removeEventListener('click', dismissCurrent, true)
  document.removeEventListener('mouseover', onMouseOver)
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseout', onMouseOut)
  document.removeEventListener('focusin', onFocusIn)
  document.removeEventListener('focusout', onFocusOut)
  window.removeEventListener('resize', dismissCurrent)
  clearHoverTimer()
  contentResizeObserver?.disconnect()
})
</script>

<template>
  <el-tooltip
    v-if="virtualRef"
    :visible="visible"
    :content="content"
    :virtual-ref="virtualRef"
    virtual-triggering
    placement="top"
    popper-class="app-wrapping-popper app-overflow-tooltip-popper"
  >
    <template #content>
      <div class="app-overflow-tooltip-content">
        <span ref="contentRef" class="app-overflow-tooltip-content__text">{{ content }}</span>
        <span v-if="contentTruncated" class="app-overflow-tooltip-content__notice">… 内容已截断</span>
      </div>
    </template>
  </el-tooltip>
</template>

<style scoped>
.app-overflow-tooltip-content__text {
  display: -webkit-box;
  max-height: calc(8 * var(--app-line-height-table));
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 8;
  line-height: var(--app-line-height-table);
  white-space: normal;
}

.app-overflow-tooltip-content__notice {
  display: block;
  margin-top: 4px;
  color: var(--app-muted-text);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-compact);
}
</style>

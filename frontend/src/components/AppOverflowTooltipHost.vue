<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  findOverflowTooltipTarget,
  overflowTooltipContent,
} from '@/components/overflow/overflowTooltip'
import { APP_HOVER_TOOLTIP_DELAY_MS } from '@/components/overflow/tooltipTiming'

const visible = ref(false)
const content = ref('')
const virtualRef = ref<HTMLElement>()
let hoverTarget: HTMLElement | null = null
let focusTarget: HTMLElement | null = null
let suppressedTitle: { element: HTMLElement; value: string } | null = null
let hoverTimer: ReturnType<typeof setTimeout> | null = null

function clearHoverTimer(): void {
  if (hoverTimer == null) return
  clearTimeout(hoverTimer)
  hoverTimer = null
}

function restoreSuppressedTitle(): void {
  if (!suppressedTitle) return
  suppressedTitle.element.title = suppressedTitle.value
  suppressedTitle = null
}

function showFor(element: HTMLElement): void {
  const nextContent = overflowTooltipContent(element)
  if (!nextContent) return
  if (virtualRef.value !== element) restoreSuppressedTitle()
  if (element.title) {
    suppressedTitle = { element, value: element.title }
    element.removeAttribute('title')
  }
  virtualRef.value = element
  content.value = nextContent
  visible.value = true
}

function hideCurrent(): void {
  visible.value = false
  restoreSuppressedTitle()
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
  const next = findOverflowTooltipTarget(event.target)
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

onMounted(() => {
  document.addEventListener('mouseover', onMouseOver)
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseout', onMouseOut)
  document.addEventListener('focusin', onFocusIn)
  document.addEventListener('focusout', onFocusOut)
})

onBeforeUnmount(() => {
  document.removeEventListener('mouseover', onMouseOver)
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseout', onMouseOut)
  document.removeEventListener('focusin', onFocusIn)
  document.removeEventListener('focusout', onFocusOut)
  clearHoverTimer()
  restoreSuppressedTitle()
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
  />
</template>

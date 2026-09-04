<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  findOverflowTooltipTarget,
  overflowTooltipContent,
} from '@/components/overflow/overflowTooltip'

const visible = ref(false)
const content = ref('')
const virtualRef = ref<HTMLElement>()
let hoverTarget: HTMLElement | null = null
let focusTarget: HTMLElement | null = null
let suppressedTitle: { element: HTMLElement; value: string } | null = null

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

function syncVisibleTarget(): void {
  const next = focusTarget || hoverTarget
  if (next) {
    showFor(next)
    return
  }
  visible.value = false
  restoreSuppressedTitle()
  virtualRef.value = undefined
  content.value = ''
}

function onMouseOver(event: MouseEvent): void {
  const next = findOverflowTooltipTarget(event.target)
  if (!next) return
  hoverTarget = next
  syncVisibleTarget()
}

function onMouseOut(event: MouseEvent): void {
  if (!hoverTarget) return
  if (event.relatedTarget instanceof Node && hoverTarget.contains(event.relatedTarget)) return
  hoverTarget = null
  syncVisibleTarget()
}

function onFocusIn(event: FocusEvent): void {
  const next = findOverflowTooltipTarget(event.target)
  if (!next) return
  focusTarget = next
  syncVisibleTarget()
}

function onFocusOut(event: FocusEvent): void {
  if (!focusTarget) return
  if (event.relatedTarget instanceof Node && focusTarget.contains(event.relatedTarget)) return
  focusTarget = null
  syncVisibleTarget()
}

onMounted(() => {
  document.addEventListener('mouseover', onMouseOver)
  document.addEventListener('mouseout', onMouseOut)
  document.addEventListener('focusin', onFocusIn)
  document.addEventListener('focusout', onFocusOut)
})

onBeforeUnmount(() => {
  document.removeEventListener('mouseover', onMouseOver)
  document.removeEventListener('mouseout', onMouseOut)
  document.removeEventListener('focusin', onFocusIn)
  document.removeEventListener('focusout', onFocusOut)
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

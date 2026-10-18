<script setup lang="ts" generic="T">
import { computed, getCurrentInstance, nextTick, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import AppIconButton from './AppIconButton.vue'

// 仅提交移动意图；权限、分组边界和保存仍由列表所有者负责。
const props = withDefaults(defineProps<{
  items: T[]
  itemKey: (item: T) => string
  itemLabel: (item: T) => string
  label: string
  disabled?: boolean
}>(), { disabled: false })
const emit = defineEmits<{ reorder: [items: T[]] }>()
const root = ref<HTMLElement>()
const helpId = `reorder-help-${getCurrentInstance()!.uid}`
const activeKey = ref<string | null>(null)
const destination = ref<number | null>(null)
const announcement = ref('')
const sourceIndex = computed(() => props.items.findIndex(item => props.itemKey(item) === activeKey.value))
let pointerId: number | null = null
let capture: HTMLElement | null = null
let startX = 0
let startY = 0
let pointerX = 0
let pointerY = 0
let moved = false
let frame = 0
let scrollport: HTMLElement | null = null

function rows(): HTMLElement[] {
  return Array.from(root.value?.children ?? []).filter(
    (node): node is HTMLElement => node instanceof HTMLElement && node.hasAttribute('data-reorder-key'),
  )
}

function cancel(): void {
  window.removeEventListener('pointermove', pointerMove)
  window.removeEventListener('pointerup', pointerUp)
  window.removeEventListener('pointercancel', pointerCancel)
  window.removeEventListener('keydown', escape, true)
  window.removeEventListener('blur', pointerCancel)
  document.removeEventListener('visibilitychange', pointerCancel)
  cancelAnimationFrame(frame)
  if (pointerId !== null && capture?.hasPointerCapture?.(pointerId)) capture.releasePointerCapture(pointerId)
  pointerId = null
  capture = null
  scrollport = null
  activeKey.value = null
  destination.value = null
}

function commit(): void {
  const from = sourceIndex.value
  const to = destination.value
  const key = activeKey.value
  cancel()
  if (props.disabled || from < 0 || to === null || from === to) return
  const next = [...props.items]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item!)
  emit('reorder', next)
  announcement.value = `已将${props.itemLabel(item!)}移至第 ${to + 1} 位`
  void nextTick(() => rows().find(row => row.dataset.reorderKey === key)?.querySelector('button')?.focus())
}

function updateDestination(): void {
  const bounds = root.value?.getBoundingClientRect()
  if (!bounds || pointerX < bounds.left || pointerX > bounds.right
    || pointerY < bounds.top || pointerY > bounds.bottom) {
    destination.value = null
    return
  }
  const allRows = rows()
  let boundary = allRows.findIndex(row => {
    const rect = row.getBoundingClientRect()
    return pointerY < rect.top + rect.height / 2
  })
  if (boundary < 0) boundary = props.items.length
  destination.value = boundary > sourceIndex.value ? boundary - 1 : boundary
}

function autoScroll(): void {
  if (pointerId === null) return
  if (moved && scrollport) {
    const rect = scrollport.getBoundingClientRect()
    const top = Math.max(0, rect.top)
    const bottom = Math.min(window.innerHeight, rect.bottom)
    if (pointerY >= top && pointerY <= bottom && pointerX >= rect.left && pointerX <= rect.right) {
      const delta = pointerY < top + 40 ? -10 : pointerY > bottom - 40 ? 10 : 0
      if (delta) {
        scrollport.scrollTop += delta
        updateDestination()
      }
    }
  }
  frame = requestAnimationFrame(autoScroll)
}

function pointerDown(event: PointerEvent, item: T): void {
  if (props.disabled || props.items.length < 2 || event.button !== 0 || event.isPrimary === false) return
  cancel()
  activeKey.value = props.itemKey(item)
  destination.value = sourceIndex.value
  startX = pointerX = event.clientX
  startY = pointerY = event.clientY
  moved = false
  pointerId = event.pointerId
  capture = event.currentTarget as HTMLElement
  capture.focus()
  capture.setPointerCapture?.(pointerId)
  scrollport = root.value?.parentElement ?? null
  while (scrollport && !/(auto|scroll)/.test(getComputedStyle(scrollport).overflowY)) {
    scrollport = scrollport.parentElement
  }
  window.addEventListener('pointermove', pointerMove, { passive: false })
  window.addEventListener('pointerup', pointerUp)
  window.addEventListener('pointercancel', pointerCancel)
  window.addEventListener('keydown', escape, true)
  window.addEventListener('blur', pointerCancel)
  document.addEventListener('visibilitychange', pointerCancel)
  frame = requestAnimationFrame(autoScroll)
  event.preventDefault()
}

function pointerMove(event: PointerEvent): void {
  if (event.pointerId !== pointerId) return
  pointerX = event.clientX
  pointerY = event.clientY
  moved ||= Math.hypot(pointerX - startX, pointerY - startY) >= 5
  if (!moved) return
  event.preventDefault()
  updateDestination()
}

function pointerUp(event: PointerEvent): void {
  if (event.pointerId !== pointerId) return
  if (moved) {
    pointerX = event.clientX
    pointerY = event.clientY
    updateDestination()
    commit()
  } else cancel()
}

function pointerCancel(): void { cancel() }
function escape(event: KeyboardEvent): void {
  if (event.key === 'Escape' && activeKey.value !== null) {
    event.preventDefault()
    event.stopPropagation()
    cancel()
    announcement.value = '已取消排序'
  }
}

function keydown(event: KeyboardEvent, item: T): void {
  if (props.disabled || props.items.length < 2 || pointerId !== null) return
  if (event.key === ' ' || event.key === 'Enter') {
    event.preventDefault()
    if (activeKey.value !== null) commit()
    else {
      activeKey.value = props.itemKey(item)
      destination.value = sourceIndex.value
      window.addEventListener('keydown', escape, true)
      window.addEventListener('blur', pointerCancel)
      document.addEventListener('visibilitychange', pointerCancel)
      announcement.value = `已拿起${props.itemLabel(item)}，使用方向键选择位置，空格确认，Esc 取消`
    }
  } else if (activeKey.value !== null && ['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const current = destination.value ?? sourceIndex.value
    destination.value = event.key === 'Home' ? 0 : event.key === 'End' ? props.items.length - 1
      : Math.max(0, Math.min(props.items.length - 1, current + (event.key === 'ArrowUp' ? -1 : 1)))
    announcement.value = `目标位置：第 ${destination.value + 1} 位`
  } else if (event.key === 'Tab') cancel()
}

// 拖动期间数据水合、保存或权限变化即取消，避免将旧快照覆盖到新列表。
watch(() => [props.disabled, ...props.items.flatMap(item => [props.itemKey(item), item])], cancel)
onBeforeUnmount(cancel)
onDeactivated(cancel)
</script>

<template>
  <div ref="root" class="app-reorder-list" role="group" :aria-label="label">
    <span :id="helpId" class="app-reorder-list__sr">拖动把手调整顺序；键盘按空格拿起，方向键选择位置，空格确认，Esc 取消。</span>
    <div
      v-for="(item, index) in items"
      :key="itemKey(item)"
      class="app-reorder-list__row"
      :class="{
        'is-editable': !disabled && items.length > 1,
        'is-dragging': activeKey === itemKey(item),
        'is-drop-before': destination !== null && destination !== sourceIndex && destination < sourceIndex && index === destination,
        'is-drop-after': destination !== null && destination !== sourceIndex && destination > sourceIndex && index === destination,
      }"
      :data-reorder-key="itemKey(item)"
    >
      <AppIconButton
        v-if="!disabled && items.length > 1"
        class="app-reorder-list__handle"
        size="sm"
        :tone="activeKey === itemKey(item) ? 'primary' : 'default'"
        :label="`拖动排序：${itemLabel(item)}`"
        tooltip="拖动调整顺序；也可按空格后用方向键移动"
        :aria-describedby="helpId"
        :aria-pressed="activeKey === itemKey(item)"
        @pointerdown="pointerDown($event, item)"
        @keydown="keydown($event, item)"
        @blur="pointerId === null && cancel()"
        @lostpointercapture="pointerCancel"
        @click.stop
      >
        <svg viewBox="0 0 16 20" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="4" r="1.3" /><circle cx="11" cy="4" r="1.3" />
          <circle cx="5" cy="10" r="1.3" /><circle cx="11" cy="10" r="1.3" />
          <circle cx="5" cy="16" r="1.3" /><circle cx="11" cy="16" r="1.3" />
        </svg>
      </AppIconButton>
      <div class="app-reorder-list__content"><slot :item="item" :index="index" /></div>
    </div>
    <span class="app-reorder-list__sr" role="status" aria-live="polite">{{ announcement }}</span>
  </div>
</template>

<style scoped>
.app-reorder-list { display: grid; gap: var(--app-space-2); min-width: 0; }
.app-reorder-list__row { position: relative; min-width: 0; }
.app-reorder-list__row.is-editable { display: grid; grid-template-columns: max-content minmax(0, 1fr); column-gap: var(--app-space-2); align-items: start; }
.app-reorder-list__handle { margin-top: var(--app-space-5); cursor: grab; touch-action: none; user-select: none; }
.app-reorder-list__handle:not(:hover):not(:focus-visible):not([aria-pressed="true"]) { color: var(--el-text-color-placeholder); }
.is-dragging > .app-reorder-list__handle { cursor: grabbing; }
.is-dragging > .app-reorder-list__content { opacity: 0.65; outline: 1px dashed var(--el-color-primary); border-radius: var(--layout-card-radius); }
.app-reorder-list__content { min-width: 0; }
.is-drop-before::before, .is-drop-after::after { content: ''; position: absolute; inset-inline: 0; height: 3px; background: var(--el-color-primary); border-radius: 2px; pointer-events: none; z-index: 1; }
.is-drop-before::before { top: -5px; }
.is-drop-after::after { bottom: -5px; }
.app-reorder-list__sr { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>

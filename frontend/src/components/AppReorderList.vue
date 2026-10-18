<script setup lang="ts" generic="T">
import { computed, getCurrentInstance, ref, type ComputedRef } from 'vue'
import AppDragHandle from './AppDragHandle.vue'
import { useReorderInteraction } from '@/composables/useReorderInteraction'

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
const sourceIndex: ComputedRef<number> = computed((): number => props.items.findIndex(item => props.itemKey(item) === activeKey.value))
function rows(): HTMLElement[] {
  return Array.from(root.value?.children ?? []).filter(
    (node): node is HTMLElement => node instanceof HTMLElement && node.hasAttribute('data-reorder-key'),
  )
}
const { activeKey, destination, announcement, pointerDown, keydown, blur, cancel } = useReorderInteraction<number>({
  root,
  disabled: () => props.disabled || props.items.length < 2,
  revision: () => props.items.flatMap(item => [props.itemKey(item), item]),
  initialTarget: key => props.items.findIndex(item => props.itemKey(item) === key),
  pointerTarget: (x, y): number | null => {
    const bounds = root.value?.getBoundingClientRect()
    if (!bounds || x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) return null
    let boundary = rows().findIndex(row => {
      const rect = row.getBoundingClientRect()
      return y < rect.top + rect.height / 2
    })
    if (boundary < 0) boundary = props.items.length
    return boundary > sourceIndex.value ? boundary - 1 : boundary
  },
  keyboardTarget: (_key, current, direction): number => {
    const index = current ?? sourceIndex.value
    return direction === 'first' ? 0 : direction === 'last' ? props.items.length - 1
      : Math.max(0, Math.min(props.items.length - 1, index + (direction === 'previous' ? -1 : 1)))
  },
  label: key => props.itemLabel(props.items.find(item => props.itemKey(item) === key)!),
  describe: (key, target) => `目标位置：${props.itemLabel(props.items.find(item => props.itemKey(item) === key)!)}，第 ${target + 1} 位`,
  commit: (key, target) => {
    const from = props.items.findIndex(item => props.itemKey(item) === key)
    if (from < 0 || from === target) return
    const next = [...props.items]
    const [item] = next.splice(from, 1)
    next.splice(target, 0, item!)
    emit('reorder', next)
  },
})
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
      <AppDragHandle
        v-if="!disabled && items.length > 1"
        class="app-reorder-list__handle"
        :label="itemLabel(item)"
        :describedby="helpId"
        :active="activeKey === itemKey(item)"
        @pointerdown="pointerDown($event, itemKey(item))"
        @keydown="keydown($event, itemKey(item))"
        @blur="blur"
        @lostpointercapture="cancel"
      />
      <div class="app-reorder-list__content"><slot :item="item" :index="index" /></div>
    </div>
    <span class="app-reorder-list__sr" role="status" aria-live="polite">{{ announcement }}</span>
  </div>
</template>

<style scoped>
.app-reorder-list { display: grid; gap: var(--app-space-2); min-width: 0; }
.app-reorder-list__row { position: relative; min-width: 0; }
.app-reorder-list__row.is-editable { display: grid; grid-template-columns: max-content minmax(0, 1fr); column-gap: var(--app-space-2); align-items: start; }
.app-reorder-list__handle { margin-top: var(--app-space-5); }
.is-dragging > .app-reorder-list__content { opacity: 0.65; outline: 1px dashed var(--el-color-primary); border-radius: var(--layout-card-radius); }
.app-reorder-list__content { min-width: 0; }
.is-drop-before::before, .is-drop-after::after { content: ''; position: absolute; inset-inline: 0; height: 3px; background: var(--el-color-primary); border-radius: 2px; pointer-events: none; z-index: 1; }
.is-drop-before::before { top: -5px; }
.is-drop-after::after { bottom: -5px; }
.app-reorder-list__sr { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>

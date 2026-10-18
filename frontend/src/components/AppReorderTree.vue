<script setup lang="ts" generic="T extends ReorderTreeItem">
import { computed, getCurrentInstance, nextTick, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { ElTree } from 'element-plus'
import AppDragHandle from './AppDragHandle.vue'
import { useReorderInteraction } from '@/composables/useReorderInteraction'
import { acceptsKeyboardEvent } from '@/utils/keyboard'
import { findTreeItem, moveTreeItem, treeRevision, treeSiblings, type ReorderTreeItem, type TreeDropTarget } from '@/utils/reorderTree'

const props = withDefaults(defineProps<{
  items: T[]
  itemLabel: (item: T) => string
  canContain: (item: T) => boolean
  label: string
  currentKey: string
  canReorder: boolean
  disabled?: boolean
  busy?: boolean
}>(), { disabled: false, busy: false })
const emit = defineEmits<{ reorder: [items: T[]]; select: [id: string] }>()
const root = ref<HTMLElement>()
const tree = ref<InstanceType<typeof ElTree>>()
const helpId = `reorder-tree-help-${getCurrentInstance()!.uid}`
const expanded = ref<string[]>([])
const knownKeys = new Set<string>()
watch(() => props.items, items => {
  const currentKeys = new Set<string>()
  const newlyExpanded: string[] = []
  const walk = (nodes: T[]) => nodes.forEach(item => {
    currentKeys.add(item.id)
    if (!knownKeys.has(item.id) && item.children.length) newlyExpanded.push(item.id)
    walk(item.children as T[])
  })
  walk(items)
  expanded.value = [...expanded.value.filter(id => currentKeys.has(id)), ...newlyExpanded]
  knownKeys.clear()
  currentKeys.forEach(key => knownKeys.add(key))
}, { immediate: true })
function labelForKey(key: string): string {
  const item = findTreeItem(props.items, key)
  return item ? props.itemLabel(item) : key
}
const { activeKey, destination, announcement, pointerDown, keydown, blur, cancel, focus } = useReorderInteraction<TreeDropTarget>({
  root,
  disabled: () => !props.canReorder || props.disabled || props.busy,
  revision: () => treeRevision(props.items),
  initialTarget: key => ({ id: key, position: 'before' }),
  pointerTarget: (x, y, key) => {
    const bounds = root.value?.getBoundingClientRect()
    if (!bounds || x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) return null
    const rows = Array.from(root.value?.querySelectorAll<HTMLElement>('[data-reorder-key]') ?? [])
    const row = rows.find(element => {
      const rect = element.getBoundingClientRect()
      return rect.height > 0 && y >= rect.top && y <= rect.bottom
    })
    if (!row) return null
    const id = row.dataset.reorderKey!
    const item = findTreeItem(props.items, id)!
    const rect = row.getBoundingClientRect()
    const ratio = (y - rect.top) / rect.height
    const position = props.canContain(item) && ratio >= 0.25 && ratio <= 0.75 ? 'inside'
      : ratio < 0.5 ? 'before' : 'after'
    const target: TreeDropTarget = { id, position }
    return moveTreeItem(props.items, key, target, props.canContain) ? target : null
  },
  keyboardTarget: (key, current, direction) => {
    const siblings = treeSiblings(props.items, key) ?? []
    const from = siblings.findIndex(item => item.id === key)
    let currentIndex = siblings.findIndex(item => item.id === current?.id)
    if (currentIndex < 0) currentIndex = from
    const nextIndex = direction === 'first' ? 0 : direction === 'last' ? siblings.length - 1
      : Math.max(0, Math.min(siblings.length - 1, currentIndex + (direction === 'previous' ? -1 : 1)))
    const item = siblings[nextIndex]
    return item ? { id: item.id, position: nextIndex <= from ? 'before' : 'after' } : null
  },
  label: labelForKey,
  describe: (key, target) => `${labelForKey(key)}：${target.position === 'inside' ? '移入' : target.position === 'before' ? '排在前面：' : '排在后面：'}${labelForKey(target.id)}`,
  commit: (key, target) => {
    const next = moveTreeItem(props.items, key, target, props.canContain)
    if (next) {
      if (target.position === 'inside') setExpanded(target.id, true)
      emit('reorder', next)
    }
  },
})
const dropText = computed(() => {
  if (!destination.value || !activeKey.value || destination.value.id === activeKey.value) return ''
  return `${destination.value.position === 'inside' ? '移入分组：' : destination.value.position === 'before' ? '排在前面：' : '排在后面：'}${labelForKey(destination.value.id)}`
})
function setExpanded(key: string, value: boolean): void {
  expanded.value = value ? [...new Set([...expanded.value, key])] : expanded.value.filter(id => id !== key)
}
function select(id: string): void { if (!props.busy) emit('select', id) }
function activateNode(event: KeyboardEvent): void {
  const target = event.target as HTMLElement
  if (props.busy || target.getAttribute('role') !== 'treeitem' || !acceptsKeyboardEvent(event)) return
  if (event.key !== 'Enter' && event.key !== ' ') return
  const key = target.dataset.key
  if (!key) return
  event.preventDefault()
  event.stopPropagation()
  select(key)
}
// 异步保存/失败重载后，把焦点交回仍存在的原把手；卸载后不再抢焦点。
let pendingFocus: string | null = null
let viewActive = true
onActivated(() => { viewActive = true })
onDeactivated(() => { viewActive = false; pendingFocus = null })
onBeforeUnmount(() => { viewActive = false; pendingFocus = null })
watch(() => props.busy, async (busy, previous) => {
  if (busy) {
    pendingFocus = root.value?.contains(document.activeElement)
      ? (document.activeElement as HTMLElement).closest<HTMLElement>('[data-reorder-key]')?.dataset.reorderKey ?? null : null
  } else if (previous && pendingFocus) {
    const key = pendingFocus
    pendingFocus = null
    await nextTick()
    if (viewActive) focus(key)
  }
}, { flush: 'sync' })
</script>

<template>
  <div ref="root" class="app-reorder-tree" :aria-label="label" :aria-busy="busy" :inert="busy || undefined" @keydown.capture="activateNode">
    <p :id="helpId" class="app-reorder-tree__sr">树节点使用方向键导航与展开，Enter 选择。拖动六点把手可调整顺序或移入分组；把手按空格拿起，上下键或 Home、End 选择同级位置，空格确认，Esc 取消。跨层也可在属性中选择上级菜单。</p>
    <ElTree
      ref="tree"
      :data="items"
      node-key="id"
      :props="{ label: (data: any) => itemLabel(data), children: 'children' }"
      :current-node-key="currentKey"
      :default-expanded-keys="expanded"
      :auto-expand-parent="false"
      highlight-current
      :expand-on-click-node="false"
      :draggable="false"
      @node-click="(data: T) => select(data.id)"
      @node-expand="(data: T) => setExpanded(data.id, true)"
      @node-collapse="(data: T) => setExpanded(data.id, false)"
    >
      <template #default="{ data }">
        <span
          class="app-reorder-tree__row"
          :class="{
            'is-dragging': activeKey === data.id,
            'is-drop-before': activeKey !== data.id && destination?.id === data.id && destination?.position === 'before',
            'is-drop-after': activeKey !== data.id && destination?.id === data.id && destination?.position === 'after',
            'is-drop-inside': destination?.id === data.id && destination?.position === 'inside',
          }"
          :data-reorder-key="data.id"
        >
          <AppDragHandle
            v-if="canReorder"
            :label="itemLabel(data)"
            :describedby="helpId"
            :active="activeKey === data.id"
            :disabled="disabled || busy"
            @pointerdown="pointerDown($event, data.id)"
            @keydown="keydown($event, data.id)"
            @blur="blur"
            @lostpointercapture="cancel"
          />
          <span class="app-reorder-tree__content"><slot :item="data" /></span>
        </span>
      </template>
    </ElTree>
    <div v-if="activeKey && dropText" class="app-reorder-tree__drop-hint" aria-hidden="true">{{ dropText }}</div>
    <span class="app-reorder-tree__sr" role="status" aria-live="polite">{{ announcement }}</span>
  </div>
</template>

<style scoped>
.app-reorder-tree { min-width: 0; }
.app-reorder-tree__row { position: relative; display: flex; align-items: center; gap: var(--app-space-2); width: 100%; min-width: 0; }
.app-reorder-tree__content { display: flex; flex: 1; min-width: 0; }
.app-reorder-tree :deep(.el-tree-node__content) { min-height: 36px; height: auto; }
.is-dragging > .app-reorder-tree__content { opacity: 0.65; }
.is-drop-inside { outline: 1px solid var(--el-color-primary); outline-offset: -1px; border-radius: var(--layout-control-radius); }
.is-drop-before::before, .is-drop-after::after { content: ''; position: absolute; inset-inline: 0; height: 3px; background: var(--el-color-primary); pointer-events: none; z-index: 1; }
.is-drop-before::before { top: 0; }
.is-drop-after::after { bottom: 0; }
.app-reorder-tree__drop-hint { position: sticky; bottom: 0; padding: var(--app-space-2); background: var(--el-bg-color); color: var(--el-color-primary); font-size: var(--app-font-size-caption); border-top: 1px solid var(--app-border-default); pointer-events: none; }
.app-reorder-tree__sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>

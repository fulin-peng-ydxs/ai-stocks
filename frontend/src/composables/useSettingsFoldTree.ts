import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowReactive,
  shallowRef,
  type ComponentPublicInstance,
  type ComputedRef,
} from 'vue'

interface SettingsFoldNode {
  open: ComputedRef<boolean>
  setOpen: (value: boolean) => void
  foldable: () => boolean
  children: ComputedRef<SettingsFoldNode[]>
}

interface SettingsFoldTreeApi {
  level: ComputedRef<number>
  register: (id: symbol, node: SettingsFoldNode) => void
  unregister: (id: symbol) => void
}

const SETTINGS_FOLD_TREE_API = Symbol('settings-fold-tree-api')
type SettingsFoldElement = HTMLElement & { [SETTINGS_FOLD_TREE_API]?: SettingsFoldTreeApi }

/**
 * 按实际 DOM 层级连接设置抽屉里的可折叠节点。
 * Vue 插槽的组件归属不等同于视觉父级，因此父节点只登记最近的直接视觉子节点。
 */
export function useSettingsFoldTree(
  open: ComputedRef<boolean>,
  setOpen: (value: boolean) => void,
  options: { rootLevel: () => number; transparent: () => boolean; foldable: () => boolean },
) {
  const rootElement = ref<SettingsFoldElement>()
  const childNodes = shallowReactive(new Map<symbol, SettingsFoldNode>())
  const nodeId = Symbol('settings-fold-node')
  const parentTree = shallowRef<SettingsFoldTreeApi>()
  // 匿名包装器只承接插槽和配置上下文，不额外占据一个可见层级。
  const level = computed(() => options.transparent()
    ? parentTree.value?.level.value ?? options.rootLevel() - 1
    : parentTree.value ? parentTree.value.level.value + 1 : options.rootLevel())
  const directChildGroups: ComputedRef<SettingsFoldNode[]> = computed(() => (
    [...childNodes.values()].flatMap(node => node.foldable() ? [node] : node.children.value)
  ))
  const currentNode: SettingsFoldNode = { open, setOpen, foldable: options.foldable, children: directChildGroups }

  const currentTree: SettingsFoldTreeApi = {
    level,
    register(id, node) {
      childNodes.set(id, node)
    },
    unregister(id) {
      childNodes.delete(id)
    },
  }

  function setRootElement(element: Element | ComponentPublicInstance | null): void {
    const next = element instanceof HTMLElement ? element as SettingsFoldElement : undefined
    if (rootElement.value && rootElement.value !== next) {
      delete rootElement.value[SETTINGS_FOLD_TREE_API]
    }
    rootElement.value = next
    if (next) next[SETTINGS_FOLD_TREE_API] = currentTree
  }

  onMounted(() => {
    const parentElement = rootElement.value?.parentElement?.closest<SettingsFoldElement>(
      '[data-settings-fold-node]',
    )
    parentTree.value = parentElement?.[SETTINGS_FOLD_TREE_API]
    parentTree.value?.register(nodeId, currentNode)
  })

  onBeforeUnmount(() => {
    parentTree.value?.unregister(nodeId)
    if (rootElement.value) delete rootElement.value[SETTINGS_FOLD_TREE_API]
  })

  const hasChildGroups = computed(() => directChildGroups.value.length > 0)
  const allChildGroupsClosed = computed(() => (
    hasChildGroups.value && directChildGroups.value.every((node) => !node.open.value)
  ))

  function toggleChildGroups(): void {
    const nextOpen = allChildGroupsClosed.value
    // 父级可能已被整体收起；显式操作下级时先露出内容，避免变化藏在折叠区域内。
    setOpen(true)
    directChildGroups.value.forEach((node) => node.setOpen(nextOpen))
  }

  return {
    allChildGroupsClosed,
    hasChildGroups,
    level,
    setRootElement,
    toggleChildGroups,
  }
}

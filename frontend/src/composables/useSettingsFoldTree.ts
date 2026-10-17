import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowReactive,
  type ComponentPublicInstance,
  type ComputedRef,
} from 'vue'

interface SettingsFoldNode {
  open: ComputedRef<boolean>
  setOpen: (value: boolean) => void
}

interface SettingsFoldTreeApi {
  register: (id: symbol, node: SettingsFoldNode) => void
  unregister: (id: symbol) => void
}

const SETTINGS_FOLD_TREE_API = Symbol('settings-fold-tree-api')
type SettingsFoldElement = HTMLElement & { [SETTINGS_FOLD_TREE_API]?: SettingsFoldTreeApi }

/**
 * 按实际 DOM 层级连接设置抽屉里的可折叠节点。
 * Vue 插槽的组件归属不等同于视觉父级，因此父节点只登记最近的直接视觉子节点。
 */
export function useSettingsFoldTree(open: ComputedRef<boolean>, setOpen: (value: boolean) => void) {
  const rootElement = ref<SettingsFoldElement>()
  const childNodes = shallowReactive(new Map<symbol, SettingsFoldNode>())
  const nodeId = Symbol('settings-fold-node')
  const currentNode: SettingsFoldNode = { open, setOpen }
  let parentTree: SettingsFoldTreeApi | undefined

  const currentTree: SettingsFoldTreeApi = {
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
    parentTree = parentElement?.[SETTINGS_FOLD_TREE_API]
    parentTree?.register(nodeId, currentNode)
  })

  onBeforeUnmount(() => {
    parentTree?.unregister(nodeId)
    if (rootElement.value) delete rootElement.value[SETTINGS_FOLD_TREE_API]
  })

  const hasChildGroups = computed(() => childNodes.size > 0)
  const allChildGroupsClosed = computed(() => (
    hasChildGroups.value && [...childNodes.values()].every((node) => !node.open.value)
  ))

  function toggleChildGroups(): void {
    const nextOpen = allChildGroupsClosed.value
    // 父级可能已被整体收起；显式操作下级时先露出内容，避免变化藏在折叠区域内。
    setOpen(true)
    childNodes.forEach((node) => node.setOpen(nextOpen))
  }

  return {
    allChildGroupsClosed,
    hasChildGroups,
    setRootElement,
    toggleChildGroups,
  }
}

import {
  cloneVNode,
  computed,
  defineComponent,
  ref,
  type Component,
  type PropType,
  type VNode,
} from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { findMenuLeaf, type MenuTreeNode } from '@/utils/permission'

export interface WorkspaceTab {
  key: string
  path: string
  title: string
  cacheName: string
}

export const WORKSPACE_TAB_LIMIT = 12
const workspaceTabs = ref<WorkspaceTab[]>([])
const cacheNames = new Map<string, string>()
const cacheWrappers = new Map<string, Component>()
const lastPathByMenu = new Map<string, string>()
let cacheSequence = 0

const workspaceCacheNames = computed(() => workspaceTabs.value.map((tab) => tab.cacheName))

function cacheNameFor(key: string): string {
  const existing = cacheNames.get(key)
  if (existing) return existing
  const name = `WorkspaceTabView${++cacheSequence}`
  cacheNames.set(key, name)
  return name
}

function releaseCache(key: string) {
  cacheNames.delete(key)
  cacheWrappers.delete(key)
}

function repairLastMenuPath(removedKey: string) {
  for (const [menuPath, fullPath] of lastPathByMenu) {
    if (fullPath.split('?')[0] !== removedKey) continue
    // 只回补菜单主页标签（key 精确等于菜单路径）；详情子路由不进菜单记忆。
    const replacement = [...workspaceTabs.value].reverse().find(
      (tab) => tab.key === menuPath,
    )
    if (replacement) lastPathByMenu.set(menuPath, replacement.path)
    else lastPathByMenu.delete(menuPath)
  }
}

function tabTitle(route: RouteLocationNormalizedLoaded, menus: MenuTreeNode[]): string {
  const leaf = findMenuLeaf(menus, route.path)
  const routeTitle = typeof route.meta.title === 'string' ? route.meta.title : ''
  const base = route.path === leaf?.index ? leaf.title : (routeTitle || leaf?.title || '研究页面')
  const code = typeof route.params.code === 'string' ? route.params.code : ''
  return code ? `${base} · ${code}` : base
}

export function visitWorkspaceTab(route: RouteLocationNormalizedLoaded, menus: MenuTreeNode[]) {
  if (route.meta.fullscreen || route.path === '/') return
  const menuPath = findMenuLeaf(menus, route.path)?.index
  // 菜单记忆只记「菜单主页自身」的访问（含查询态，如 /stocks?restore=1）；
  // 详情子路由（/stocks/:code、/sectors/:code）不覆盖菜单记忆——点菜单永远回主页，
  // 详情现场只由工作标签恢复（DESIGN「工作标签」节）。
  if (menuPath && route.path === menuPath) lastPathByMenu.set(menuPath, route.fullPath)
  const next: WorkspaceTab = {
    key: route.path,
    path: route.fullPath,
    title: tabTitle(route, menus),
    cacheName: cacheNameFor(route.path),
  }
  const existing = workspaceTabs.value.findIndex((tab) => tab.key === next.key)
  if (existing >= 0) {
    workspaceTabs.value[existing] = { ...next, cacheName: workspaceTabs.value[existing].cacheName }
    return
  }
  if (workspaceTabs.value.length >= WORKSPACE_TAB_LIMIT) {
    const removed = workspaceTabs.value.shift()
    if (removed) {
      releaseCache(removed.key)
      repairLastMenuPath(removed.key)
    }
  }
  workspaceTabs.value.push(next)
}

export function removeWorkspaceTab(key: string, activeKey: string): string | undefined {
  if (workspaceTabs.value.length <= 1) return undefined
  const index = workspaceTabs.value.findIndex((tab) => tab.key === key)
  if (index < 0) return undefined
  workspaceTabs.value.splice(index, 1)
  releaseCache(key)
  repairLastMenuPath(key)
  if (key !== activeKey) return undefined
  return workspaceTabs.value[Math.min(index, workspaceTabs.value.length - 1)]?.path
}

export function resetWorkspaceTabs() {
  workspaceTabs.value = []
  cacheNames.clear()
  cacheWrappers.clear()
  lastPathByMenu.clear()
}

/** 菜单再次进入时恢复该菜单主页最后停留的访问（含查询态）；详情子路由不被菜单记忆，由工作标签恢复。 */
export function resolveWorkspaceMenuPath(menuPath: string): string {
  return lastPathByMenu.get(menuPath) ?? menuPath
}

/**
 * 每个标签使用独立具名包装组件，让 KeepAlive.include 能精确淘汰某个路由实例；
 * 不能直接按页面组件名缓存，否则多个个股详情标签会共享名称且无法单独关闭。
 */
export function workspaceViewWrapper(key: string): Component {
  const existing = cacheWrappers.get(key)
  if (existing) return existing
  const name = cacheNameFor(key)
  const wrapper = defineComponent({
    name,
    inheritAttrs: false,
    props: {
      view: { type: Object as PropType<VNode>, required: true },
    },
    setup(props) {
      return () => cloneVNode(props.view)
    },
  })
  cacheWrappers.set(key, wrapper)
  return wrapper
}

export function useWorkspaceTabs() {
  return { workspaceTabs, workspaceCacheNames, workspaceViewWrapper }
}

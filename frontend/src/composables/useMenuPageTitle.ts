import {
  computed,
  getCurrentInstance,
  inject,
  toValue,
  type ComputedRef,
  type MaybeRefOrGetter,
} from 'vue'
import type { Pinia } from 'pinia'
import { routeLocationKey } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { findMenuLeaf, type MenuTreeNode } from '@/utils/permission'

export interface MenuPageTitleOptions {
  /** 页面特殊阶段的短后缀，例如“进行中”；基础名称仍来自菜单。 */
  suffix?: MaybeRefOrGetter<string | undefined>
  /** 仅在菜单和路由元数据均不可用时使用。 */
  fallback?: string
}

export function resolveMenuPageTitle(
  menus: MenuTreeNode[],
  path: string,
  routeTitle: unknown,
  options: { suffix?: string; fallback?: string } = {},
): string {
  const menuTitle = findMenuLeaf(menus, path)?.title.trim()
  const fallback = typeof routeTitle === 'string' ? routeTitle.trim() : ''
  const base = menuTitle || fallback || options.fallback?.trim() || ''
  const suffix = options.suffix?.trim()
  return suffix && base ? `${base} · ${suffix}` : base
}

/** 页面标题统一跟随后端菜单名称；菜单未就绪时以路由 meta.title 稳定回退。 */
export function useMenuPageTitle(options: MenuPageTitleOptions = {}): ComputedRef<string> {
  const route = inject(routeLocationKey, null)
  const pinia = getCurrentInstance()?.appContext.config.globalProperties.$pinia as Pinia | undefined
  const auth = pinia ? useAuthStore(pinia) : null
  return computed(() => resolveMenuPageTitle(auth?.menus ?? [], route?.path ?? '', route?.meta.title, {
    suffix: toValue(options.suffix),
    fallback: options.fallback,
  }))
}

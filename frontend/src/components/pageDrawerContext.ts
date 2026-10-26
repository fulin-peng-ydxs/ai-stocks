import type { InjectionKey } from 'vue'

/** 统一抽屉外壳的后代控件上下文，覆盖插槽、嵌套组件与 Teleport。 */
export const PAGE_DRAWER_SURFACE: InjectionKey<boolean> = Symbol('page-drawer-surface')

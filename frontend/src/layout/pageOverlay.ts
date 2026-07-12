import type { InjectionKey, Ref } from 'vue'

/** 当前 LayoutHost 的页面级浮层挂载点；页面抽屉不得越过该边界覆盖应用顶栏与导航。 */
export const PAGE_OVERLAY_TARGET: InjectionKey<Ref<HTMLElement | null>> = Symbol('page-overlay-target')

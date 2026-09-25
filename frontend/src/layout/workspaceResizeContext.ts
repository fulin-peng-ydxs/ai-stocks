import type { InjectionKey, Ref } from 'vue'

/** 父级工作区正在调整布局；后代可据此延后昂贵的尺寸同步。 */
export const WORKSPACE_RESIZE_ACTIVE: InjectionKey<Readonly<Ref<boolean>>> = Symbol(
  'workspace-resize-active',
)

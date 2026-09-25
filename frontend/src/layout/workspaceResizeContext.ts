import type { InjectionKey, Ref } from 'vue'

export interface WorkspaceProfileSize {
  width: number
  height: number
}

/** 父级工作区正在调整布局；后代可据此延后昂贵的尺寸同步。 */
export const WORKSPACE_RESIZE_ACTIVE: InjectionKey<Readonly<Ref<boolean>>> = Symbol(
  'workspace-resize-active',
)

/**
 * 组件比例档案使用的稳定视觉环境尺寸。
 * 内部分栏只改变后代渲染尺寸，不应改变这份由外层工作区提供的匹配上下文。
 */
export const WORKSPACE_PROFILE_SIZE: InjectionKey<Readonly<Ref<WorkspaceProfileSize>>> = Symbol(
  'workspace-profile-size',
)

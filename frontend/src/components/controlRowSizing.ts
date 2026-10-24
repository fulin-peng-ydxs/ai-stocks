import { computed, inject, provide, type CSSProperties, type InjectionKey, type Ref } from 'vue'
import {
  formContextKey, formItemContextKey, useFormSize, type FormContext, type FormItemContext,
} from 'element-plus'

export type ControlRowSize = 'default' | 'small' | 'large'

const CONTROL_ROW_SIZE: InjectionKey<Readonly<Ref<ControlRowSize>> | null> =
  Symbol('control-row-size')
const CONTROL_ROW_FORM_BOUNDARY: InjectionKey<{
  form?: FormContext
  formItem?: FormItemContext
}> = Symbol('control-row-form-boundary')

/** 行外维持表单/页面规则；嵌套行优先继承最近行，显式 default 回到页面密度。 */
export function useControlRowSizing() {
  const parentSize = inject(CONTROL_ROW_SIZE, null)
  const boundary = inject(CONTROL_ROW_FORM_BOUNDARY, undefined)
  // Teleport 不切断 Vue 注入：只忽略边界外的旧表单，边界内新建的表单仍正常继承。
  const inheritedSize = useFormSize(parentSize ?? undefined, {
    form: !!boundary?.form && boundary.form === inject(formContextKey, undefined),
    formItem: !!boundary?.formItem && boundary.formItem === inject(formItemContextKey, undefined),
  })
  const size = computed<ControlRowSize>(() => inheritedSize.value || 'default')
  provide(CONTROL_ROW_SIZE, size)
  const style = computed<CSSProperties>(() => ({
    '--app-control-row-height': size.value === 'small'
      ? 'var(--app-control-height-sm)'
      : size.value === 'large'
        ? 'var(--app-control-height-lg)'
        : 'var(--app-density-control-height, var(--app-control-height-md))',
  }))
  return { size, style }
}

/** 新编辑表单和独立浮层不继承调用工具行；CSS 边界同时清理 DOM 继承。 */
export function resetControlRowSizing() {
  provide(CONTROL_ROW_SIZE, null)
  provide(CONTROL_ROW_FORM_BOUNDARY, {
    form: inject(formContextKey, undefined),
    formItem: inject(formItemContextKey, undefined),
  })
}

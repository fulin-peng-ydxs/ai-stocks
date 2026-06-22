/**
 * L2 布局覆盖层（用户 Web 端自定义的运行态）。
 *
 * 模型：默认 schema（开发态）→ 用户稀疏覆盖（仅 editable 白名单内的 path）→ 合并 → 校验 → effective。
 * 持久化：localStorage（分层存决策；L3 组件偏好仍走 usePageSettings，L2 走这里，键名独立）。
 * 「可改不能乱改」：每次 setKnob 经 coerceEditableValue 守门（越界即抛）；合并后整体再过 validateLayout，
 * 极端跨旋钮冲突时回落默认，绝不把非法布局交给渲染器。
 */
import { computed, reactive, watch } from 'vue'
import type { EditableKnob, PageLayout } from './schema'
import { cloneLayout, getLayoutValue, setLayoutValue } from './path'
import { coerceEditableValue, validateLayout } from './validator'

type OverlayValue = string | number | boolean
type Overlay = Record<string, OverlayValue>

export function useLayoutConfig(base: PageLayout) {
  const storageKey = `ai-stocks:layout:${base.pageKey}`
  const knobByPath = new Map<string, EditableKnob>(base.editable.map((k) => [k.path, k]))

  // 载入已存覆盖：只接受白名单内、且能通过取值域的项（schema 变更后旧覆盖自动失效）
  const overlay = reactive<Overlay>({})
  try {
    const raw = localStorage.getItem(storageKey)
    if (raw) {
      for (const [path, value] of Object.entries(JSON.parse(raw) as Overlay)) {
        const knob = knobByPath.get(path)
        if (!knob) continue
        try {
          overlay[path] = coerceEditableValue(knob, value)
        } catch {
          /* 旧值越界：丢弃 */
        }
      }
    }
  } catch {
    /* 损坏数据：忽略 */
  }

  watch(
    overlay,
    () => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(overlay))
      } catch {
        /* ignore */
      }
    },
    { deep: true },
  )

  /** 合并后的有效布局（交给 LayoutHost）。 */
  const effective = computed<PageLayout>(() => {
    const merged = cloneLayout(base)
    for (const [path, value] of Object.entries(overlay)) setLayoutValue(merged, path, value)
    if (validateLayout(merged).some((i) => i.level === 'error')) return cloneLayout(base)
    return merged
  })

  /** 改一个旋钮（越界/类型不符抛 LayoutConfigError）。 */
  function setKnob(path: string, value: unknown): void {
    const knob = knobByPath.get(path)
    if (!knob) throw new Error(`未开放编辑的布局项: ${path}`)
    overlay[path] = coerceEditableValue(knob, value)
  }

  function resetKnob(path: string): void {
    delete overlay[path]
  }

  function resetAll(): void {
    for (const key of Object.keys(overlay)) delete overlay[key]
  }

  const isDirty = computed(() => Object.keys(overlay).length > 0)

  /** 读某旋钮当前有效值（供表单回显）。 */
  function valueOf(path: string): unknown {
    return getLayoutValue(effective.value, path)
  }

  return { effective, knobs: base.editable, setKnob, resetKnob, resetAll, isDirty, valueOf }
}

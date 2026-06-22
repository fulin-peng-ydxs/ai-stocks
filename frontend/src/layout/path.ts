/**
 * PageLayout 内字段的点分路径读写（L2 覆盖层落点）。
 * 支持两类路径：
 *   - 'slots.<id>.<field>' → 定位某 slot 的字段（minH/minW/scroll/...）
 *   - 其余按对象层级导航（'density' / 'responsive.allowReflow' / ...）
 * 配合 EditableKnob 白名单使用：调用方只对白名单内 path 读写，越界由 validator 兜底。
 */
import type { PageLayout } from './schema'

/** 深拷贝一份布局（覆盖层合并时用，避免污染默认 schema）。 */
export function cloneLayout(layout: PageLayout): PageLayout {
  return JSON.parse(JSON.stringify(layout)) as PageLayout
}

/** 读取 path 当前值；路径不可达返回 undefined。 */
export function getLayoutValue(layout: PageLayout, path: string): unknown {
  const parts = path.split('.')
  if (parts[0] === 'slots') {
    const slot = layout.slots.find((s) => s.id === parts[1])
    if (!slot || parts.length < 3) return undefined
    return (slot as unknown as Record<string, unknown>)[parts[2]]
  }
  let node: unknown = layout
  for (const p of parts) {
    if (node == null || typeof node !== 'object') return undefined
    node = (node as Record<string, unknown>)[p]
  }
  return node
}

/** 就地写入 path（调用方应传入 clone）；路径不可达则不操作。 */
export function setLayoutValue(layout: PageLayout, path: string, value: unknown): void {
  const parts = path.split('.')
  if (parts[0] === 'slots') {
    const slot = layout.slots.find((s) => s.id === parts[1])
    if (!slot || parts.length < 3) return
    ;(slot as unknown as Record<string, unknown>)[parts[2]] = value
    return
  }
  let node: Record<string, unknown> = layout as unknown as Record<string, unknown>
  for (let i = 0; i < parts.length - 1; i++) {
    const next = node[parts[i]]
    if (next == null || typeof next !== 'object') return
    node = next as Record<string, unknown>
  }
  node[parts[parts.length - 1]] = value
}

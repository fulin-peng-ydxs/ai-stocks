/**
 * 布局约束校验器（M1 核心）——把规范的「可执行规则」从 prose 变成机制性强制。
 *
 * 职责边界（见 plan.md 决策 c）：本校验器只覆盖 **schema 层可判定** 的规则：
 *   - 原型/组件合法性、组件最低尺寸下限（规范 §3）
 *   - 主表唯一（growMain）、滚动轴唯一（规范 §6）
 *   - 操作区一致性（规范 §1）
 *   - 重排多列三条件 + 断点合法性（规范 §5）
 *   - 可编辑白名单 path 真实性与取值域（L2「可改不能乱改」）
 * 而 **CSS/DOM 层** 的红线（100vh 硬编码、teleport+scoped 陷阱、真实渲染的单滚动轴，规范 §9）
 * 由 M2 渲染器「由构造即合规」保证，不在此处判定。
 *
 * 三处复用：开发期单测（本目录 __tests__）、运行期用户改配置、CI 构建。
 */
import { COMPONENT_CATALOG, getComponentMeta } from './components'
import { ARCHETYPES, type EditableKnob, type PageLayout, type SlotSpec } from './schema'

/** 多列重排时列间距（px），与 global.css `.v-page` 的 gap 对齐，用于估算拆列后单列净宽。 */
export const COLUMN_GAP = 12

export interface ValidationIssue {
  level: 'error' | 'warn'
  code: string
  message: string
  slotId?: string
}

/** slot 上允许被 editable 白名单指向的字段（防止 path 指向 id/component 等结构性字段）。 */
const SLOT_EDITABLE_FIELDS = new Set(['minW', 'minH', 'idealW', 'idealH', 'scroll', 'growMain', 'order'])

function effectiveMinW(slot: SlotSpec): number {
  return slot.minW ?? COMPONENT_CATALOG[slot.component]?.minW ?? 0
}

/** 校验一份 PageLayout，返回全部问题（error + warn）。空数组表示完全合规。 */
export function validateLayout(layout: PageLayout): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  const push = (level: ValidationIssue['level'], code: string, message: string, slotId?: string) =>
    issues.push({ level, code, message, slotId })

  // 1. 原型合法
  if (!ARCHETYPES.includes(layout.archetype)) {
    push('error', 'archetype.unknown', `未知布局原型: ${layout.archetype}`)
  }

  // 2. slots 非空 + id 唯一
  if (!layout.slots.length) {
    push('error', 'slots.empty', '布局至少需要一个组件槽')
  }
  const seenIds = new Set<string>()
  for (const slot of layout.slots) {
    if (seenIds.has(slot.id)) push('error', 'slot.id.duplicate', `重复的 slot id: ${slot.id}`, slot.id)
    seenIds.add(slot.id)

    // 3. 组件已登记
    const meta = getComponentMeta(slot.component)
    if (!meta) {
      push('error', 'component.unknown', `未登记的组件种类: ${slot.component}`, slot.id)
      continue
    }

    // 4. 显式最低尺寸不得低于组件目录下限（规范 §3：不能把组件压到不可用）
    if (slot.minW != null && slot.minW < meta.minW) {
      push('error', 'slot.minW.below', `${slot.id} 最低宽 ${slot.minW} 低于 ${meta.label} 下限 ${meta.minW}`, slot.id)
    }
    if (slot.minH != null && slot.minH < meta.minH) {
      push('error', 'slot.minH.below', `${slot.id} 最低高 ${slot.minH} 低于 ${meta.label} 下限 ${meta.minH}`, slot.id)
    }

    // 5a. growMain 的组件必须 canGrowMain
    if (slot.growMain && !meta.canGrowMain) {
      push('error', 'slot.growMain.unsupported', `${meta.label}(${slot.id}) 不能作为吃富余空间的主表/主图`, slot.id)
    }
    // 操作区不应承载成长主体
    if (slot.growMain && slot.region === 'action') {
      push('error', 'slot.growMain.inAction', `${slot.id} 在操作区不能 growMain`, slot.id)
    }
  }

  const mainSlots = layout.slots.filter((s) => s.region === 'main')
  const actionSlots = layout.slots.filter((s) => s.region === 'action')

  // 5b. 主内容区至多一个 growMain（规范 §1：富余空间交给一个主表/主图）
  const growCount = mainSlots.filter((s) => s.growMain).length
  if (growCount > 1) {
    push('error', 'growMain.multiple', `主内容区出现 ${growCount} 个 growMain，至多允许 1 个`)
  }

  // 6. 滚动轴唯一（规范 §6）：同一 region 内至多一个「整区滚动」(scroll=region)
  for (const region of ['action', 'main'] as const) {
    const regionScroll = layout.slots.filter(
      (s) => s.region === region && (s.scroll ?? COMPONENT_CATALOG[s.component]?.defaultScroll) === 'region',
    )
    if (regionScroll.length > 1) {
      push('error', 'scroll.region.multiple', `${region} 区出现 ${regionScroll.length} 个整区滚动，主滚动轴必须唯一`)
    }
  }

  // 7. 操作区一致性（规范 §1）
  if (!layout.hasActionRegion && actionSlots.length) {
    push('error', 'action.region.unexpected', `hasActionRegion=false 时不应有操作区组件（${actionSlots.map((s) => s.id).join(',')}）`)
  }
  if (layout.hasActionRegion && !actionSlots.length) {
    push('warn', 'action.region.empty', 'hasActionRegion=true 但没有任何操作区组件')
  }
  if (!mainSlots.length) {
    push('error', 'main.region.empty', '缺少主内容区组件')
  }

  // 8 + 9 + 10. 响应式断点与重排三条件（规范 §5）
  validateResponsive(layout, mainSlots, push)

  // 11. 可编辑白名单
  validateEditable(layout, push)

  return issues
}

function validateResponsive(
  layout: PageLayout,
  mainSlots: SlotSpec[],
  push: (level: ValidationIssue['level'], code: string, message: string, slotId?: string) => void,
): void {
  const { allowReflow, breakpoints } = layout.responsive

  // 8. 断点合法：非空、升序、首项 minWidth=0、columns≥1
  if (!breakpoints.length) {
    push('error', 'responsive.empty', '响应式断点表不能为空')
    return
  }
  if (breakpoints[0].minWidth !== 0) {
    push('error', 'responsive.noBase', '断点表首项 minWidth 必须为 0（覆盖窄屏单列）')
  }
  for (let i = 0; i < breakpoints.length; i++) {
    const bp = breakpoints[i]
    if (bp.columns < 1) push('error', 'responsive.columns.invalid', `断点 ${bp.minWidth} 列数必须 ≥1`)
    if (i > 0 && bp.minWidth <= breakpoints[i - 1].minWidth) {
      push('error', 'responsive.notAscending', `断点 minWidth 必须严格升序（${bp.minWidth} ≤ ${breakpoints[i - 1].minWidth}）`)
    }
  }

  const maxColumns = Math.max(...breakpoints.map((b) => b.columns))

  // 10. allowReflow=false 却声明多列 → 矛盾
  if (!allowReflow && maxColumns > 1) {
    push('error', 'reflow.disabledButMultiCol', 'allowReflow=false 但断点声明了多列；不重排应恒为单列')
    return
  }
  if (!allowReflow) return

  // 9a. 重排条件 3：参与重排的主内容区组件必须无强阅读顺序（reflowable）
  const nonReflowable = mainSlots.filter((s) => !COMPONENT_CATALOG[s.component]?.reflowable)
  for (const s of nonReflowable) {
    push('error', 'reflow.nonReflowable', `${COMPONENT_CATALOG[s.component]?.label}(${s.id}) 有强阅读顺序/为大表，不可参与重排多列`, s.id)
  }

  // 9b. 单组件重排无意义（规范 §5「单个大表不要重排」）
  if (mainSlots.length < 2) {
    push('warn', 'reflow.singleSlot', '主内容区只有一个组件，重排多列无意义')
  }

  // 9c. 重排条件 2：拆列后每个组件仍满足最低宽度
  const maxMinW = Math.max(0, ...mainSlots.map(effectiveMinW))
  for (const bp of breakpoints) {
    if (bp.columns < 2) continue
    const colW = (bp.minWidth - (bp.columns - 1) * COLUMN_GAP) / bp.columns
    if (colW < maxMinW) {
      push(
        'error',
        'reflow.belowMinWidth',
        `断点 ${bp.minWidth}px 拆 ${bp.columns} 列后单列净宽约 ${Math.floor(colW)}px，低于组件最低宽 ${maxMinW}px`,
      )
    }
  }
}

function validateEditable(
  layout: PageLayout,
  push: (level: ValidationIssue['level'], code: string, message: string, slotId?: string) => void,
): void {
  for (const knob of layout.editable) {
    if (!pathExists(layout, knob.path)) {
      push('error', 'editable.path.invalid', `可编辑 path 指向不存在的字段: ${knob.path}`)
    }
    if (knob.type === 'enum' && !knob.options?.length) {
      push('error', 'editable.enum.noOptions', `${knob.path} 为 enum 但未提供 options`)
    }
    if ((knob.type === 'int' || knob.type === 'number') && knob.min != null && knob.max != null && knob.min >= knob.max) {
      push('error', 'editable.range.invalid', `${knob.path} 取值域非法：min(${knob.min}) ≥ max(${knob.max})`)
    }
  }
}

/** path 是否指向 PageLayout 内真实可编辑字段。slot 字段按白名单字段名判定（允许当前未显式赋值的项）。 */
export function pathExists(layout: PageLayout, path: string): boolean {
  const parts = path.split('.')
  if (parts[0] === 'slots') {
    if (parts.length < 3) return false
    const slot = layout.slots.find((s) => s.id === parts[1])
    if (!slot) return false
    return SLOT_EDITABLE_FIELDS.has(parts[2])
  }
  let node: unknown = layout
  for (const p of parts) {
    if (node == null || typeof node !== 'object' || !(p in (node as Record<string, unknown>))) return false
    node = (node as Record<string, unknown>)[p]
  }
  return true
}

/** 校验失败异常（运行期用户改配置时拒绝并提示）。 */
export class LayoutConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LayoutConfigError'
  }
}

/** 是否完全合规（无 error；warn 不算阻断）。 */
export function isLayoutValid(layout: PageLayout): boolean {
  return !validateLayout(layout).some((i) => i.level === 'error')
}

/** 断言合规：有 error 即抛（开发期/CI 用）。 */
export function assertLayout(layout: PageLayout): void {
  const errors = validateLayout(layout).filter((i) => i.level === 'error')
  if (errors.length) {
    throw new LayoutConfigError(
      `布局 ${layout.pageKey} 不合规:\n` + errors.map((e) => `  - [${e.code}] ${e.message}`).join('\n'),
    )
  }
}

/**
 * 校验并规范化单个可编辑旋钮的值（L2「可改不能乱改」的逐项守门，对齐后端 app_config._coerce）。
 * 越界/类型不符抛 LayoutConfigError；合法返回规范化值。
 */
export function coerceEditableValue(knob: EditableKnob, value: unknown): string | number | boolean {
  if (knob.type === 'bool') {
    if (typeof value !== 'boolean') throw new LayoutConfigError(`${knob.path} 需为布尔值`)
    return value
  }
  if (knob.type === 'enum') {
    if ((typeof value !== 'string' && typeof value !== 'number') || !knob.options?.includes(value)) {
      throw new LayoutConfigError(`${knob.path} 需为 ${JSON.stringify(knob.options)} 之一`)
    }
    return value
  }
  // int / number
  if (typeof value === 'boolean') throw new LayoutConfigError(`${knob.path} 需为数值`)
  const num = Number(value)
  if (!Number.isFinite(num)) throw new LayoutConfigError(`${knob.path} 需为${knob.type === 'int' ? '整数' : '数值'}`)
  if (knob.type === 'int' && !Number.isInteger(num)) throw new LayoutConfigError(`${knob.path} 需为整数`)
  if (knob.min != null && num < knob.min) throw new LayoutConfigError(`${knob.path} 不能小于 ${knob.min}`)
  if (knob.max != null && num > knob.max) throw new LayoutConfigError(`${knob.path} 不能大于 ${knob.max}`)
  return num
}

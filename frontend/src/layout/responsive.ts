/**
 * 自适应策略模型（P8 / R1）——把"代码内响应式规则 + 浏览器肉眼验证"升级为
 * 受控、可命名、可摘要、可校验的策略层。
 *
 * 设计原则（plan.md §17.2 / §6.4）：受控策略而非自由布局编辑器。
 *   - 代码红线（不可配）：页面外壳永不整页滚动、主表优先内滚、禁止视口硬编码高度、单大表不靠多列重排解决高度。
 *     这些由 validator + 契约测试 + LayoutHost「由构造即合规」强制，不在本文件开放。
 *   - 受控策略（可命名/可摘要/有限调整）：页面响应式画像（ResponsiveProfile）、各设备档位列数、
 *     哪些 slot 允许重排、哪些大表/大图不可重排——本文件提供统一命名与摘要，供工作台展示。
 *
 * 本文件不渲染、不写库，纯派生函数；是「响应式策略」的单一事实源（命名不再散落在各页注释）。
 */
import { COMPONENT_CATALOG } from './components'
import type { PageLayout, SlotSpec } from './schema'
import type { ResponsiveProfile } from './pageRegistry'

/** 三类页面响应式策略的统一命名与说明（plan.md §17.3）。 */
export const RESPONSIVE_PROFILES: Record<ResponsiveProfile, { label: string; desc: string }> = {
  'single-column': { label: '单列内滚', desc: '始终单列，富余高度交给主体内部滚动（列表/详情主区单组件）。' },
  'safe-reflow': { label: '安全重排', desc: '仅在满足各组件最低宽度时，允许无强阅读顺序的平级块重排多列（仪表盘类）。' },
  'mixed-panel': { label: '混合面板', desc: '固定分析块 + 主 grow 区，放不下时整区滚动兜底（工作台类）。' },
}

export function responsiveProfileLabel(p: ResponsiveProfile): string {
  return RESPONSIVE_PROFILES[p]?.label ?? p
}

/** 设备档位（plan.md §17.3）：项目响应式验收基线。 */
export interface DeviceTier {
  key: 'small' | 'laptop' | 'desktop'
  label: string
  /** 短标签（摘要表头用）。 */
  short: string
  w: number
  h: number
}
export const DEVICE_TIERS: DeviceTier[] = [
  { key: 'small', label: '小屏 1100×620', short: '小屏', w: 1100, h: 620 },
  { key: 'laptop', label: '笔记本 1366×768', short: '笔记本', w: 1366, h: 768 },
  { key: 'desktop', label: '桌面 1440×900', short: '桌面', w: 1440, h: 900 },
]

/** 顶层主区 slot（排除嵌套/overlay）。响应式摘要只针对参与主流布局的顶层主区组件。 */
function topMainSlots(layout: PageLayout): SlotSpec[] {
  return layout.slots
    .filter((s) => s.region === 'main' && !s.parentId)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
}

function isReflowable(s: SlotSpec): boolean {
  return s.reflowable ?? COMPONENT_CATALOG[s.component]?.reflowable ?? false
}

/** 给定视口宽度，按断点表推导列数（取 minWidth ≤ width 的最大断点）。 */
export function columnsAt(layout: PageLayout, width: number): number {
  let cols = 1
  for (const bp of [...layout.responsive.breakpoints].sort((a, b) => a.minWidth - b.minWidth)) {
    if (width >= bp.minWidth) cols = bp.columns
  }
  return Math.max(1, cols)
}

export interface ResponsiveSlotInfo {
  id: string
  label: string
  component: string
  /** growMain 主表/主图（吃富余空间、强阅读顺序，永不参与多列重排）。 */
  growMain: boolean
}

export interface ResponsiveSummary {
  profile: ResponsiveProfile
  profileLabel: string
  profileDesc: string
  /** 是否允许多列重排（layout.responsive.allowReflow）。 */
  allowReflow: boolean
  /** 各设备档位下的列数与退化路径。 */
  tiers: { key: DeviceTier['key']; label: string; short: string; width: number; columns: number }[]
  /** 允许参与重排的顶层主区 slot。 */
  reflowableSlots: ResponsiveSlotInfo[]
  /** 不可重排的大表/大图等顶层主区 slot（强阅读顺序，靠内部滚动而非拆列解决高度）。 */
  lockedSlots: ResponsiveSlotInfo[]
}

/**
 * 派生一份页面响应式摘要：策略命名/说明 + 三档列数 + 可重排/不可重排 slot 分类。
 * 供页面布局工作台「响应式摘要」面板展示（plan.md §17.4.1 / §17.6）。
 */
export function describeResponsive(layout: PageLayout, profile: ResponsiveProfile): ResponsiveSummary {
  const info = RESPONSIVE_PROFILES[profile] ?? { label: profile, desc: '' }
  const main = topMainSlots(layout)
  const toInfo = (s: SlotSpec): ResponsiveSlotInfo => ({
    id: s.id,
    label: s.label || s.id,
    component: COMPONENT_CATALOG[s.component]?.label ?? s.component,
    growMain: !!s.growMain,
  })
  return {
    profile,
    profileLabel: info.label,
    profileDesc: info.desc,
    allowReflow: layout.responsive.allowReflow,
    tiers: DEVICE_TIERS.map((t) => ({
      key: t.key,
      label: t.label,
      short: t.short,
      width: t.w,
      columns: columnsAt(layout, t.w),
    })),
    reflowableSlots: main.filter(isReflowable).map(toInfo),
    lockedSlots: main.filter((s) => !isReflowable(s)).map(toInfo),
  }
}

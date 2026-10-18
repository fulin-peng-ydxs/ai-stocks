export type AdaptiveColumnRole =
  | 'structural'
  | 'switch'
  | 'rank'
  | 'code'
  | 'name'
  | 'entity'
  | 'status'
  | 'number'
  | 'comparison-number'
  | 'date'
  | 'datetime'
  | 'key'
  | 'action'
  | 'action-compact'
  | 'text'
  | 'description'

interface AdaptiveColumnRule {
  minWidth?: number
  width?: number
}

export type AdaptiveColumnAlign = 'left' | 'center' | 'right'
export type TableControlWidth = 'compact' | 'short' | 'medium' | 'long' | 'wide'

interface AdaptiveColumnSizing extends AdaptiveColumnRule {
  headerCapped?: boolean
  headerIndent?: number
  align: AdaptiveColumnAlign
}

export interface AdaptiveColumnDescriptor {
  role?: AdaptiveColumnRole
  type?: string
  label?: string
  prop?: string
  headerMeta?: string
  sortable?: boolean
  filterable?: boolean
  customHeader?: boolean
  leadingControls?: number
  /** 表格内 AppFilterSelect 需要完整显示的标签数；同时预留 +N 和单元格留白。 */
  filterSelectVisibleTagCount?: number
  /** 表格内 AppFilterSelect 的展示方式；count 只承载“已选 N”。 */
  filterSelectDisplayMode?: 'tags' | 'count'
  /** 表内编辑控件（或同组控件）的容量档位，含控件外的单元格留白。 */
  controlWidth?: TableControlWidth
}

interface AdaptiveColumnPolicy extends AdaptiveColumnRule {
  maxAutoWidth?: number
  align: AdaptiveColumnAlign
}

/**
 * 表格列语义呈现的唯一事实源：同一角色共同决定列宽、表头和单元格对齐。
 * 内容列只提供最小宽度，最终宽度由 Element Plus 的 fit 算法按容器余量同比分配；
 * 结构列和操作列使用固定语义宽度，避免无内容承载能力的列吞占富余空间。
 * 当列宽总和超过容器时，表体自然进入横向滚动。
 */
export const ADAPTIVE_COLUMN_RULES: Record<AdaptiveColumnRole, AdaptiveColumnPolicy> = {
  structural: { width: 48, align: 'center' },
  // 标准开关 40px + 单元格留白 24px，额外保留 16px 操作空间。
  switch: { width: 80, align: 'center' },
  rank: { width: 60, align: 'center' },
  code: { minWidth: 112, maxAutoWidth: 192, align: 'left' },
  name: { minWidth: 128, maxAutoWidth: 240, align: 'left' },
  // 主副两行共同识别业务对象；前置控件占位由 leadingControls 统一叠加。
  entity: { minWidth: 152, maxAutoWidth: 320, align: 'left' },
  // 状态列要容纳表格单元格留白与常见五字标签，避免有限枚举仍属于正常
  // 短文案时被 max-width: 100% 误压缩成省略号。
  status: { minWidth: 112, maxAutoWidth: 192, align: 'center' },
  number: { minWidth: 96, maxAutoWidth: 192, align: 'right' },
  // 横向比较矩阵以列中轴对照不同系列，数值仍使用等宽数字，但不沿用普通数值右边界。
  'comparison-number': { minWidth: 96, maxAutoWidth: 192, align: 'center' },
  date: { minWidth: 120, maxAutoWidth: 192, align: 'left' },
  datetime: { minWidth: 168, maxAutoWidth: 224, align: 'left' },
  key: { minWidth: 160, maxAutoWidth: 240, align: 'left' },
  // 操作列数值是默认下限；运行时可按行操作组的最低可用组合向上扩展。
  action: { width: 144, align: 'center' },
  // 紧凑操作列同样以该值为默认下限，而不是不可突破的固定上限。
  'action-compact': { width: 96, align: 'center' },
  text: { minWidth: 140, maxAutoWidth: 240, align: 'left' },
  description: { minWidth: 200, maxAutoWidth: 320, align: 'left' },
}

const HEADER_FONT_SIZE = 14
const HEADER_HORIZONTAL_SPACE = 32
const HEADER_SORT_CONTROL_WIDTH = 24
const HEADER_FILTER_CONTROL_WIDTH = 20
const HEADER_CUSTOM_SLOT_RESERVE = 16
const HEADER_META_GAP = 4
// 紧凑前置操作统一按 24px xs 图标按钮 + 8px 实体列间距预留，
// 使表头起点与按钮之后的主名称文字严格共线。
const LEADING_CONTROL_SLOT_WIDTH = 32
const MAX_LEADING_CONTROLS = 4
const COLUMN_WIDTH_GRID = 8
const TABLE_CELL_HORIZONTAL_INSET = 24
// 与 global.css 的 --app-control-width-* 档位一致；统一供编辑列和多选列估算。
const TABLE_CONTROL_WIDTHS: Record<TableControlWidth, number> = {
  compact: 96, short: 140, medium: 180, long: 220, wide: 300,
}
const FILTER_SELECT_WIDTH_BY_VISIBLE_TAG_COUNT = [
  0, TABLE_CONTROL_WIDTHS.medium, TABLE_CONTROL_WIDTHS.long, TABLE_CONTROL_WIDTHS.wide,
] as const
const FILTER_SELECT_COUNT_MODE_WIDTH = TABLE_CONTROL_WIDTHS.short

function glyphWidthInEm(char: string): number {
  if (/\s/.test(char)) return 0.32
  if (/[A-Z0-9]/.test(char)) return 0.66
  if (/[a-z]/.test(char)) return 0.56
  if (/[.,:;!|'`/\\()\[\]{}\-_+%]/.test(char)) return 0.46
  // 中文、全角字符和 emoji 按完整字宽估算，避免混排表头被低估。
  return 1
}

/**
 * 使用稳定字符权重估算表头宽度，避免浏览器字体测量和数据变化引发列宽二次跳动。
 */
export function estimateHeaderTextWidth(text: string | undefined): number {
  if (!text) return 0
  const em = Array.from(text.trim()).reduce((total, char) => total + glyphWidthInEm(char), 0)
  return Math.ceil(em * HEADER_FONT_SIZE)
}

function roundUpToGrid(width: number): number {
  return Math.ceil(width / COLUMN_WIDTH_GRID) * COLUMN_WIDTH_GRID
}

function resolveLeadingControlsReserve(count: number | undefined): number {
  const normalizedCount = Math.min(
    MAX_LEADING_CONTROLS,
    Math.max(0, Math.floor(Number.isFinite(count) ? count! : 0)),
  )
  return normalizedCount * LEADING_CONTROL_SLOT_WIDTH
}

function resolveFilterSelectReserve(
  count: number | undefined,
  displayMode: 'tags' | 'count' | undefined,
): number {
  if (displayMode === 'count') return FILTER_SELECT_COUNT_MODE_WIDTH + TABLE_CELL_HORIZONTAL_INSET
  if (count === undefined) return 0
  const normalized = Math.min(3, Math.max(1, Math.floor(Number(count))))
  return FILTER_SELECT_WIDTH_BY_VISIBLE_TAG_COUNT[normalized] + TABLE_CELL_HORIZONTAL_INSET
}

function resolveHeaderSizing(
  descriptor: AdaptiveColumnDescriptor,
  maxAutoWidth: number,
): { minWidth: number; capped: boolean } {
  const titleWidth = estimateHeaderTextWidth(descriptor.label)
  const metaWidth = estimateHeaderTextWidth(descriptor.headerMeta)
  const contentWidth = titleWidth + metaWidth + (titleWidth && metaWidth ? HEADER_META_GAP : 0)
  if (!contentWidth) return { minWidth: 0, capped: false }

  const controlsWidth = (descriptor.sortable ? HEADER_SORT_CONTROL_WIDTH : 0)
    + (descriptor.filterable ? HEADER_FILTER_CONTROL_WIDTH : 0)
    + (descriptor.customHeader ? HEADER_CUSTOM_SLOT_RESERVE : 0)
  const estimatedWidth = roundUpToGrid(contentWidth + HEADER_HORIZONTAL_SPACE + controlsWidth)
  return {
    minWidth: Math.min(maxAutoWidth, estimatedWidth),
    capped: estimatedWidth > maxAutoWidth,
  }
}

const DATETIME_PATTERN = /(时间|时刻|创建于|更新于|最近触发|下次触发|截止)/
const DATE_PATTERN = /(日期|交易日|买入日|卖出日|开始日|结束日)/
const DESCRIPTION_PATTERN = /(说明|描述|备注|详情|信息|原因|内容|表达式|参数|关联|上下文|变更|错误)/
const ACTION_PATTERN = /(操作|动作)/
const CODE_PATTERN = /(代码|证券代码|股票代码)/
const NAME_PATTERN = /(名称|姓名|租户名|账号|用户|角色名|方案名)/
const KEY_PATTERN = /(\bID\b|标识|键|Key|路径|物理表|字段名|接口)/
const STATUS_PATTERN = /(状态|评级|质量|类型|来源|方向|启用|可用|环境|密度|层级|权限|模式|严重度|任务类型)/
const NUMBER_PATTERN = /(数量|行数|总数|评分|得分|收益|胜率|耗时|进度|天数|日数|权重|比例|金额|价格|涨幅|跌幅|百分比|页大小|手数|排名)/
const RANK_PATTERN = /^(#|序号|排名)$/

function descriptorText(descriptor: AdaptiveColumnDescriptor): string {
  return `${descriptor.label ?? ''} ${descriptor.prop ?? ''}`.trim()
}

export function inferAdaptiveColumnRole(
  descriptor: AdaptiveColumnDescriptor,
): AdaptiveColumnRole {
  if (descriptor.role) return descriptor.role
  if (['selection', 'expand'].includes(descriptor.type ?? '')) return 'structural'
  if (descriptor.type === 'index') return 'rank'

  const text = descriptorText(descriptor)
  if (RANK_PATTERN.test(descriptor.label ?? '')) return 'rank'
  if (ACTION_PATTERN.test(text)) return 'action'
  if (DATETIME_PATTERN.test(text) || /(?:^|_)(?:created|updated|completed)_at$/.test(descriptor.prop ?? '')) {
    return 'datetime'
  }
  if (DATE_PATTERN.test(text) || /(?:^|_)(?:date|day)$/.test(descriptor.prop ?? '')) return 'date'
  if (DESCRIPTION_PATTERN.test(text)) return 'description'
  if (CODE_PATTERN.test(text) || descriptor.prop === 'code') return 'code'
  if (NAME_PATTERN.test(text) || /(?:^|_)name(?:_cn)?$/.test(descriptor.prop ?? '')) return 'name'
  if (KEY_PATTERN.test(text) || /(?:^|_)(?:id|key)$/.test(descriptor.prop ?? '')) return 'key'
  if (STATUS_PATTERN.test(text) || /(?:^|_)(?:status|state|type)$/.test(descriptor.prop ?? '')) return 'status'
  if (NUMBER_PATTERN.test(text)) return 'number'
  return 'text'
}

export function resolveAdaptiveColumnWidth(
  descriptor: AdaptiveColumnDescriptor,
): AdaptiveColumnSizing & { role: AdaptiveColumnRole } {
  const role = inferAdaptiveColumnRole(descriptor)
  const policy = ADAPTIVE_COLUMN_RULES[role]
  if (policy.width !== undefined) {
    // 普通「# / 序号 / 排名」保持紧凑固定宽度；显式使用 rank 角色的长标题
    // （如「全市场排名」）仍需为标题和排序控件留足空间，不能套用 60px 序号列。
    const compactRank = role === 'rank' && (!descriptor.label || RANK_PATTERN.test(descriptor.label))
    if (role !== 'rank' || compactRank) return { role, width: policy.width, align: policy.align }
    const headerSizing = resolveHeaderSizing(descriptor, 160)
    return {
      role,
      minWidth: Math.max(policy.width, headerSizing.minWidth),
      align: policy.align,
    }
  }

  const headerIndent = resolveLeadingControlsReserve(descriptor.leadingControls)
  const baseMinWidth = Math.max(
    (policy.minWidth ?? 0) + headerIndent,
    descriptor.controlWidth
      ? roundUpToGrid(TABLE_CONTROL_WIDTHS[descriptor.controlWidth] + TABLE_CELL_HORIZONTAL_INSET)
      : 0,
    resolveFilterSelectReserve(
      descriptor.filterSelectVisibleTagCount,
      descriptor.filterSelectDisplayMode,
    ),
  )
  const headerSizing = resolveHeaderSizing(
    descriptor,
    Math.max(0, (policy.maxAutoWidth ?? Number.POSITIVE_INFINITY) - headerIndent),
  )
  return {
    role,
    minWidth: Math.max(baseMinWidth, headerSizing.minWidth + headerIndent),
    headerCapped: headerSizing.capped,
    headerIndent,
    align: policy.align,
  }
}

/** 操作列取语义档位默认值与当前各行最低宽度需求的最大值。 */
export function resolveActionColumnWidth(
  defaultWidth: number,
  rowMinimumWidths: Iterable<number>,
): number {
  let resolved = defaultWidth
  for (const width of rowMinimumWidths) {
    if (Number.isFinite(width)) resolved = Math.max(resolved, Math.ceil(width))
  }
  return resolved
}

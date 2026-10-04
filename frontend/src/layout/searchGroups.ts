/** 列表搜索候选与默认常显项；页面、布局登记、设置抽屉共同消费。 */
export interface SearchGroup {
  pageKey: string
  parentId?: string
  slotId: string
  label: string
  fields: { key: string; label: string }[]
  defaults: string[]
}

function group(pageKey: string, slotId: string, label: string, fields: string[][], defaults: string[], parentId?: string): SearchGroup {
  return { pageKey, slotId, label, parentId, fields: fields.map(([key, label]) => ({ key, label })), defaults }
}

export const SEARCH_GROUPS = {
  stocks: group('stocks', 'filter', '个股搜索', [['boards', '上市板块'], ['status', '股票状态'], ['membership', '所属行业 / 概念'], ['keyword', '代码 / 名称']], ['boards', 'keyword']),
  users: group('user-manage', 'head', '用户搜索', [['tenant', '租户'], ['role', '角色'], ['status', '状态'], ['keyword', '账号 / 邮箱']], ['status', 'keyword']),
  audit: group('audit-log', 'filters', '审计搜索', [['date', '时间范围'], ['event', '事件类型'], ['result', '结果'], ['status', '状态'], ['tenant', '租户'], ['resource', '资源码'], ['actor', '处理人'], ['target', '目标对象']], ['date', 'actor']),
  quality: group('data-quality', 'head', '质检搜索', [['status', '状态'], ['severity', '严重度'], ['type', '问题类型'], ['keyword', '股票 / 板块']], ['status', 'keyword']),
  indicators: group('config-tech', 'techFilters', '技术指标搜索', [['layer', '业务层级'], ['source', '来源'], ['dtype', '输出类型'], ['status', '状态'], ['presets', '展开快捷预设'], ['keyword', '名称 / 标识']], ['layer', 'keyword']),
  ladder: group('limit-ladder', 'head', '连板天梯搜索', [['boards', '上市板块'], ['ignoreSt', '忽略 ST'], ['oneWord', '仅一字板'], ['keyword', '代码 / 名称']], ['boards', 'keyword']),
  history: group('trade-discipline', 'historyFilters', '履约历史搜索', [['date', '交易日期范围'], ['rule', '规则'], ['assessment', '结果'], ['operation', '操作状态'], ['amended', '修订状态'], ['stock', '股票'], ['reason', '违规原因']], ['date', 'stock'], 'workspaceTabs'),
  assets: group('data-overview', 'assetFilters', '数据资产搜索', [['category', '业务分类'], ['legacy', '查看迁移旧表'], ['keyword', '中文名 / 表名 / 用途']], ['category', 'keyword'], 'workspace'),
} satisfies Record<string, SearchGroup>
export type SearchGroupKey = keyof typeof SEARCH_GROUPS

/** 无效、重复和权限变化后的候选只在读取时回退，不改写用户保存的原始偏好。 */
export function resolveCommonFields(value: unknown, candidates: { key: string }[], defaults: string[]): string[] {
  const allowed = new Set(candidates.map((field) => field.key))
  const selected = Array.isArray(value) ? value.filter((key): key is string => typeof key === 'string') : []
  return [...new Set([...selected, ...defaults, ...allowed])].filter((key) => allowed.has(key)).slice(0, 2)
}

export interface SearchFieldState {
  value: unknown
  /** false 表示该模式/身份不适用，不用于表达加载中或加载失败。 */
  available?: boolean
  active?: boolean
  range?: boolean
  /** 默认使用控件占位提示或自带标签；仅无可见提示的控件显式设 false，补充左侧标签。 */
  selfLabelled?: boolean
  summary?: string
  options?: readonly { value?: unknown; code?: unknown; id?: unknown; label?: string; name?: string }[]
  clear?: () => void
  error?: string
}

export function searchSummary(state: SearchFieldState): string {
  if (state.active === false) return ''
  const raw = (Array.isArray(state.value) ? state.value : [state.value])
    .map((value) => typeof value === 'string' ? value.trim() : value)
  const values = raw.filter((value) => value !== '' && value != null && value !== false)
  if (!values.length && state.active !== true) return ''
  if (state.summary) return state.summary
  if (state.range && values.length) return raw.map(value => value || '不限').join(' 至 ')
  const labels = values.map((value) => {
    const option = state.options?.find((option) => String(option.value ?? option.code ?? option.id) === String(value))
    return option?.label ?? option?.name ?? (value === true ? '是' : String(value))
  })
  return labels.length > 2 ? `${labels.slice(0, 2).join('、')} 等 ${labels.length} 项` : labels.join('、')
}

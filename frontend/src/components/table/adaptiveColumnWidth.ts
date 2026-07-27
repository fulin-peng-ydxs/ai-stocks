export type AdaptiveColumnRole =
  | 'structural'
  | 'rank'
  | 'code'
  | 'name'
  | 'status'
  | 'number'
  | 'date'
  | 'datetime'
  | 'key'
  | 'action'
  | 'text'
  | 'description'

interface AdaptiveColumnRule {
  minWidth?: number
  width?: number
}

export interface AdaptiveColumnDescriptor {
  role?: AdaptiveColumnRole
  type?: string
  label?: string
  prop?: string
}

/**
 * 自适应列宽的唯一数值事实源。
 * 除结构列外只提供最小宽度，最终宽度由 Element Plus 的 fit 算法按容器余量同比分配；
 * 当最小宽度总和超过容器时，表体自然进入横向滚动。
 */
export const ADAPTIVE_COLUMN_RULES: Record<AdaptiveColumnRole, AdaptiveColumnRule> = {
  structural: { width: 48 },
  rank: { width: 60 },
  code: { minWidth: 112 },
  name: { minWidth: 128 },
  status: { minWidth: 96 },
  number: { minWidth: 96 },
  date: { minWidth: 120 },
  datetime: { minWidth: 168 },
  key: { minWidth: 160 },
  action: { minWidth: 232 },
  text: { minWidth: 140 },
  description: { minWidth: 200 },
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
): AdaptiveColumnRule & { role: AdaptiveColumnRole } {
  const role = inferAdaptiveColumnRole(descriptor)
  return { role, ...ADAPTIVE_COLUMN_RULES[role] }
}

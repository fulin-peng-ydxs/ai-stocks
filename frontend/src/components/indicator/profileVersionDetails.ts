import { formatPercent } from '@/utils/marketValue'
import { formatNumber } from '@/utils/numberFormat'
import type { IndicatorDef, ScoreProfileVersion } from '@/api/scoreProfile'
import type { Backstop, CondTree, TradeProfileVersion } from '@/api/tradeProfile'
import { enumText } from '@/utils/displayText'

export interface VersionRuleRow {
  id: string; name: string; state: string; params: string; rule: string; weight?: string
}
const numberText = (value: unknown) => typeof value === 'number' && Number.isFinite(value)
  ? formatNumber(value, 'parameter') : '未记录'
const percentText = (value: unknown) => typeof value === 'number' && Number.isFinite(value)
  ? formatPercent(value, { input: 'ratio' }) : '未记录'
const valueText = (value: unknown): string => typeof value === 'boolean'
  ? value ? '是' : '否' : numberText(value)

/** 历史版本按其保存值展示；不补入当前指标默认参数，也不修改待恢复的配置。 */
function ruleIdentity(indicator: string, enabled: boolean | undefined,
  params: Record<string, number> | undefined, definitions: IndicatorDef[], index: number) {
  const definition = definitions.find(item => item.key === indicator)
  return {
    id: String(index), name: definition?.name_cn || '未登记指标',
    state: enabled === false ? '停用' : '启用',
    params: Object.entries(params ?? {}).map(([key, value]) => {
      const param = definition?.params.find(item => item.name === key)
      return `${param?.label || '未登记参数'} ${numberText(value)}${param?.unit || ''}`
    }).join('；') || '未保存参数',
  }
}

export function scoreVersionRows(version: ScoreProfileVersion, definitions: IndicatorDef[]): VersionRuleRow[] {
  return version.items.map((item, index) => {
    const scoring = item.scoring
    let rule = '评分方式未识别'
    if (scoring?.type === 'bool') rule = '条件评分'
    else if (scoring?.type === 'linear') rule = `线性评分：${numberText(scoring.min)}～${numberText(scoring.max)}`
    else if (scoring?.type === 'band') rule = '分段评分：' + scoring.bands
      .map(([low, high, score]) => `${numberText(low)}～${numberText(high)}：${numberText(score)} 分`).join('；')
    return { ...ruleIdentity(item.indicator, item.enabled, item.params, definitions, index),
      weight: percentText(item.weight), rule }
  })
}

export function conditionVersionRows(tree: CondTree | Record<string, never>, definitions: IndicatorDef[]): VersionRuleRow[] {
  const comparisons = { '==': '等于', '!=': '不等于', '>': '大于', '>=': '大于等于',
    '<': '小于', '<=': '小于等于', between: '介于' }
  return (tree.children ?? []).map((item, index) => ({
    ...ruleIdentity(item.indicator, item.enabled, item.params, definitions, index),
    rule: `${enumText(comparisons, item.cmp, '比较方式未识别')} ${Array.isArray(item.value)
      ? item.value.map(valueText).join('～') : valueText(item.value)}`,
  }))
}

export function conditionRelation(tree: CondTree | Record<string, never>): string {
  if (!tree.children?.length) return '未设置条件'
  return enumText({ AND: '全部启用条件同时满足', OR: '任一启用条件满足' }, tree.op, '条件关系未识别')
}

export function backstopFields(backstop: Backstop | TradeProfileVersion['backstop']) {
  const percent = (value: number | null | undefined) => value == null ? '未设置' : percentText(value)
  return [
    { label: '止盈', value: percent(backstop?.take_profit) },
    { label: '止损', value: percent(backstop?.stop_loss) },
    { label: '最长持有', value: backstop?.max_hold_days == null ? '未设置' : `${numberText(backstop.max_hold_days)} 个交易日` },
  ]
}

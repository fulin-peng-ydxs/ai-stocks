import type { ActionSubtypeOption, DraftActionRule } from '@/api/tradeDiscipline'

export const builtinActionSubtypeOptions: readonly ActionSubtypeOption[] = [
  { name: 'open_position', label: '建仓', action_type: 'buy', builtin: true },
  { name: 'add_position', label: '加仓', action_type: 'buy', builtin: true },
  { name: 'liquidate', label: '清仓', action_type: 'sell', builtin: true },
  { name: 'reduce_position', label: '减仓', action_type: 'sell', builtin: true },
]

/** 管理与打卡共用类型名称；已删除的自定义类型仍按规则快照展示。 */
export function actionSubtypeLabel(
  rule: Pick<DraftActionRule, 'action_type' | 'action_subtype' | 'action_subtype_label'>,
  options: readonly ActionSubtypeOption[] = builtinActionSubtypeOptions,
): string {
  if (rule.action_subtype_label) return rule.action_subtype_label
  const option = options.find((item) => (
    item.action_type === rule.action_type && item.name === rule.action_subtype
  ))
  if (option) return option.label || option.name
  if (rule.action_subtype === 'do_t') return '做 T'
  return rule.action_subtype?.trim() || '未选择类型'
}

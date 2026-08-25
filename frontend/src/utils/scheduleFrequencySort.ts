import type { FreqConfig, FreqType } from '@/api/data'

export interface ScheduleFrequencyValue {
  freq_type: FreqType | null
  freq_config?: FreqConfig | null
  trigger_mode?: 'time' | 'dependency'
  trigger_text?: string
}

const FREQ_RANK: Record<FreqType, number> = { daily: 0, weekly: 1, monthly: 2, cron: 3 }

function compareText(left: unknown, right: unknown): number {
  return String(left ?? '').localeCompare(String(right ?? ''), 'zh', { numeric: true })
}

function compareWeekdays(left: number[] | undefined, right: number[] | undefined): number {
  const leftDays = [...(left ?? [])].sort((a, b) => a - b)
  const rightDays = [...(right ?? [])].sort((a, b) => a - b)
  const length = Math.max(leftDays.length, rightDays.length)
  for (let index = 0; index < length; index += 1) {
    const result = (leftDays[index] ?? 0) - (rightDays[index] ?? 0)
    if (result !== 0) return result
  }
  return 0
}

/** 按列表中实际展示的频率配置排序，同类型任务不再退化为按任务名称排序。 */
export function compareScheduleFrequency(
  left: ScheduleFrequencyValue,
  right: ScheduleFrequencyValue,
): number {
  const leftRank = left.trigger_mode === 'dependency' || !left.freq_type ? 4 : FREQ_RANK[left.freq_type]
  const rightRank = right.trigger_mode === 'dependency' || !right.freq_type ? 4 : FREQ_RANK[right.freq_type]
  const rankResult = leftRank - rightRank
  if (rankResult !== 0) return rankResult
  if (leftRank === 4 && rightRank === 4) {
    return compareText(left.trigger_text, right.trigger_text)
  }

  const leftConfig = left.freq_config ?? {}
  const rightConfig = right.freq_config ?? {}
  if (left.freq_type === 'weekly' && right.freq_type === 'weekly') {
    const weekdayResult = compareWeekdays(leftConfig.weekdays, rightConfig.weekdays)
    return weekdayResult || compareText(leftConfig.time, rightConfig.time)
  }
  if (left.freq_type === 'monthly' && right.freq_type === 'monthly') {
    const dayResult = (leftConfig.day ?? 1) - (rightConfig.day ?? 1)
    return dayResult || compareText(leftConfig.time, rightConfig.time)
  }
  if (left.freq_type === 'cron' && right.freq_type === 'cron') {
    return compareText(leftConfig.cron?.trim(), rightConfig.cron?.trim())
  }
  return compareText(leftConfig.time, rightConfig.time)
}

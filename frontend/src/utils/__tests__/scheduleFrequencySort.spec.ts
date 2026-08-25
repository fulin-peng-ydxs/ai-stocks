import { describe, expect, it } from 'vitest'
import { compareScheduleFrequency, type ScheduleFrequencyValue } from '@/utils/scheduleFrequencySort'

function frequency(
  freq_type: ScheduleFrequencyValue['freq_type'],
  freq_config: NonNullable<ScheduleFrequencyValue['freq_config']>,
): ScheduleFrequencyValue {
  return { freq_type, freq_config }
}

describe('compareScheduleFrequency', () => {
  it('每日任务按执行时间排序', () => {
    const values = ['20:20', '20:10', '21:30', '00:00', '01:00'].map((time) =>
      frequency('daily', { time }),
    )

    expect(values.sort(compareScheduleFrequency).map((item) => item.freq_config?.time)).toEqual([
      '00:00', '01:00', '20:10', '20:20', '21:30',
    ])
  })

  it('每周先按星期组合、再按执行时间排序，且不修改原星期数组', () => {
    const weekdays = [5, 1, 3]
    const values = [
      frequency('weekly', { weekdays: [1, 3, 5], time: '20:00' }),
      frequency('weekly', { weekdays: [2], time: '09:00' }),
      frequency('weekly', { weekdays, time: '08:00' }),
    ]

    expect(values.sort(compareScheduleFrequency).map((item) => item.freq_config?.time)).toEqual([
      '08:00', '20:00', '09:00',
    ])
    expect(weekdays).toEqual([5, 1, 3])
  })

  it('每月按日期和时间排序，避免 10 号排在 2 号之前', () => {
    const values = [
      frequency('monthly', { day: 10, time: '08:00' }),
      frequency('monthly', { day: 2, time: '20:00' }),
      frequency('monthly', { day: 2, time: '09:00' }),
    ]

    expect(values.sort(compareScheduleFrequency).map((item) => item.freq_config)).toEqual([
      { day: 2, time: '09:00' },
      { day: 2, time: '20:00' },
      { day: 10, time: '08:00' },
    ])
  })

  it('不同频率类型保持每日、每周、每月、cron 的既有顺序', () => {
    const values = [
      frequency('cron', { cron: '0 1 * * *' }),
      frequency('monthly', { day: 1, time: '08:00' }),
      frequency('weekly', { weekdays: [1], time: '08:00' }),
      frequency('daily', { time: '08:00' }),
    ]

    expect(values.sort(compareScheduleFrequency).map((item) => item.freq_type)).toEqual([
      'daily', 'weekly', 'monthly', 'cron',
    ])
  })

  it('依赖触发排在时间频率之后并按触发说明稳定排序', () => {
    const values: ScheduleFrequencyValue[] = [
      { freq_type: null, trigger_mode: 'dependency', trigger_text: '质检·完成后' },
      frequency('cron', { cron: '0 1 * * *' }),
      { freq_type: null, trigger_mode: 'dependency', trigger_text: '更新·成功后' },
    ]
    expect(values.sort(compareScheduleFrequency).map((item) => item.trigger_text || item.freq_type)).toEqual([
      'cron', '更新·成功后', '质检·完成后',
    ])
  })
})

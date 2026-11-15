import { describe, expect, it } from 'vitest'
import { formatClockMinutes, formatClockTime, formatDateOnly, formatDateTimeMinutes, formatDateTimeSeconds, formatDateYear } from '@/utils/dateTime'

describe('dateTime', () => {
  it('日期、年份和日志时钟统一处理 ISO 后缀及各自的空值口径', () => {
    const timestamp = '2026-09-09T01:02:03.456+08:00'
    expect(formatDateOnly(timestamp)).toBe('2026-09-09')
    expect(formatDateYear(timestamp)).toBe('2026')
    expect(formatClockTime(timestamp)).toBe('01:02:03')
    expect(formatClockMinutes(timestamp)).toBe('01:02')
    expect(formatDateOnly('2026-09-09')).toBe('2026-09-09')
    expect(formatClockTime('01:02:03')).toBe('01:02:03')
    expect(formatClockTime('2026-09-09')).toBe('—')
    for (const format of [formatDateOnly, formatDateYear, formatClockTime, formatClockMinutes]) {
      for (const value of [null, undefined, '', '  ']) expect(format(value, '未记录')).toBe('未记录')
    }
  })
  it('统一秒级日期时间展示且不转换时区', () => {
    expect(formatDateTimeSeconds('2026-09-09T01:02:03.456Z'))
      .toBe('2026-09-09 01:02:03')
    expect(formatDateTimeSeconds('2026-09-09T01:02:03+08:00'))
      .toBe('2026-09-09 01:02:03')
    expect(formatDateTimeSeconds('2026-09-09 01:02:03'))
      .toBe('2026-09-09 01:02:03')
  })

  it('分钟级格式与秒级格式保持独立', () => {
    expect(formatDateTimeMinutes('2026-09-09T01:02:03Z'))
      .toBe('2026-09-09 01:02')
  })

  it('允许调用方保留各自的空值文案', () => {
    expect(formatDateTimeSeconds(null)).toBe('—')
    expect(formatDateTimeSeconds(undefined, '-')).toBe('-')
    expect(formatDateTimeMinutes('', '时间未填写')).toBe('时间未填写')
  })
})

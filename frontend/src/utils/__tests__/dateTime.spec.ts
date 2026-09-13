import { describe, expect, it } from 'vitest'
import { formatDateTimeMinutes, formatDateTimeSeconds } from '@/utils/dateTime'

describe('dateTime', () => {
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

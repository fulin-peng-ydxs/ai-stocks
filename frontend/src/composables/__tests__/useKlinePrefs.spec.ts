// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { ALL_DAYS, useKlinePrefs } from '@/composables/useKlinePrefs'

describe('useKlinePrefs', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('读取旧 localStorage fallback 并保持原接口', () => {
    localStorage.setItem('ai-stocks:kline-prefs', JSON.stringify({
      periods: [30, 90],
      includeAll: false,
      defaultPeriod: 90,
    }))

    const { prefs, options, validDefault } = useKlinePrefs()

    expect(prefs.periods).toEqual([30, 90])
    expect(options.value).toEqual([
      { value: 30, label: '近 30 日' },
      { value: 90, label: '近 90 日' },
    ])
    expect(validDefault.value).toBe(90)
  })

  it('重置后恢复默认范围和全部选项', () => {
    const { prefs, options, reset } = useKlinePrefs()
    prefs.includeAll = false
    reset()

    expect(prefs.periods).toEqual([60, 120, 250])
    expect(prefs.defaultPeriod).toBe(120)
    expect(options.value.at(-1)).toEqual({ value: ALL_DAYS, label: '全部' })
  })
})

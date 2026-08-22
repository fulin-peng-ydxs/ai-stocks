import { beforeEach, describe, expect, it, vi } from 'vitest'

const getTradeDates = vi.hoisted(() => vi.fn())

vi.mock('@/api/backtest', () => ({ getTradeDates }))

describe('交易日共享状态', () => {
  beforeEach(() => {
    vi.resetModules()
    getTradeDates.mockReset()
  })

  it('暴露加载中与就绪状态，并保留交易日边界', async () => {
    let resolveRequest!: (value: { dates: string[]; min: string; max: string }) => void
    getTradeDates.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }))
    const { useTradeDates } = await import('@/composables/useTradeDates')
    const dates = useTradeDates()

    const loading = dates.ensureLoaded()
    expect(dates.status.value).toBe('loading')
    resolveRequest({ dates: ['2026-08-22'], min: '2026-08-22', max: '2026-08-22' })
    await loading

    expect(dates.status.value).toBe('ready')
    expect(dates.dataMin.value).toBe('2026-08-22')
    expect(dates.dataMax.value).toBe('2026-08-22')
    expect(dates.loadError.value).toBeNull()
  })

  it('失败状态可观察且允许原地重试', async () => {
    const failure = new Error('calendar unavailable')
    getTradeDates
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce({ dates: ['2026-08-22'], min: '2026-08-22', max: '2026-08-22' })
    const { useTradeDates } = await import('@/composables/useTradeDates')
    const dates = useTradeDates()

    await dates.ensureLoaded()
    expect(dates.status.value).toBe('error')
    expect(dates.loadError.value).toBe(failure)

    await dates.ensureLoaded()
    expect(dates.status.value).toBe('ready')
    expect(getTradeDates).toHaveBeenCalledTimes(2)
  })
})

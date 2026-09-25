import { afterEach, describe, expect, it, vi } from 'vitest'
import { createLatestAnimationFrame } from '@/utils/latestAnimationFrame'

describe('createLatestAnimationFrame', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('同一帧只应用最新值', () => {
    let callback: FrameRequestCallback | undefined
    const cancel = vi.fn()
    vi.stubGlobal('requestAnimationFrame', vi.fn((next: FrameRequestCallback) => {
      callback = next
      return 7
    }))
    vi.stubGlobal('cancelAnimationFrame', cancel)
    const apply = vi.fn()
    const frame = createLatestAnimationFrame(apply)

    frame.schedule(1)
    frame.schedule(2)
    frame.schedule(3)

    expect(requestAnimationFrame).toHaveBeenCalledTimes(1)
    expect(apply).not.toHaveBeenCalled()
    callback?.(0)
    expect(apply).toHaveBeenCalledTimes(1)
    expect(apply).toHaveBeenLastCalledWith(3)
    expect(cancel).not.toHaveBeenCalled()
  })

  it('flush 同步应用终态且 cancel 丢弃未应用值', () => {
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 9))
    const cancel = vi.fn()
    vi.stubGlobal('cancelAnimationFrame', cancel)
    const apply = vi.fn()
    const frame = createLatestAnimationFrame(apply)

    frame.schedule('final')
    frame.flush()
    expect(cancel).toHaveBeenCalledWith(9)
    expect(apply).toHaveBeenLastCalledWith('final')

    frame.schedule('discarded')
    frame.cancel()
    expect(apply).toHaveBeenCalledTimes(1)
  })
})

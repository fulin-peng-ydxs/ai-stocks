// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth, writeAuth } from '@/api/authToken'
import {
  calculateAutoDisplayScalePercent,
  initDisplayScale,
  resetDisplayScaleForTests,
  setCustomDisplayScalePercent,
  setDisplayScaleMode,
  syncDisplayScalePreference,
  useDisplayScale,
} from '@/composables/useDisplayScale'

const prefApi = vi.hoisted(() => ({
  listUserPreferences: vi.fn(),
  saveUserPreference: vi.fn(),
}))

vi.mock('@/api/userPreferences', () => prefApi)

function setDpr(value: number): void {
  Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value })
}

function setScreenArea(width: number, height: number): void {
  Object.defineProperty(window.screen, 'availWidth', { configurable: true, value: width })
  Object.defineProperty(window.screen, 'availHeight', { configurable: true, value: height })
}

function login(): void {
  writeAuth({
    accessToken: 'scale-token',
    refreshToken: 'scale-refresh',
    user: { id: 'scale-user', account: 'scale-user' },
    tenant: { id: 'tenant-a' },
    role: 'normal',
  })
}

describe('应用显示比例', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
    clearAuth()
    resetDisplayScaleForTests()
    setDpr(1)
    setScreenArea(1920, 1080)
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
  })

  it('自动模式按屏幕有效逻辑面积连续调节，并为常规屏和超大屏保留阅读边界', () => {
    expect(calculateAutoDisplayScalePercent({ width: 1366, height: 768 })).toBe(100)
    expect(calculateAutoDisplayScalePercent({ width: 1800, height: 1169 })).toBe(100)
    expect(calculateAutoDisplayScalePercent({ width: 2560, height: 1440 })).toBe(92)
    expect(calculateAutoDisplayScalePercent({ width: 3360, height: 1890 })).toBe(85)
    expect(calculateAutoDisplayScalePercent({ width: 7680, height: 4320 })).toBe(82)
    expect(calculateAutoDisplayScalePercent({ width: 0, height: 0 })).toBe(100)
  })

  it('挂载前恢复自动比例并写入全局缩放事实源', () => {
    setDpr(2)
    initDisplayScale()

    expect(useDisplayScale().mode.value).toBe('auto')
    expect(useDisplayScale().effectivePercent.value).toBe(
      calculateAutoDisplayScalePercent(),
    )
    expect(document.documentElement.style.getPropertyValue('--app-display-scale')).toBe(
      String(calculateAutoDisplayScalePercent() / 100),
    )
    expect(document.documentElement.style.getPropertyValue('--app-display-scale-inverse')).toBe('1')
    expect(document.documentElement.dataset.displayResolution).toBe('high')
  })

  it('连续微调自动切换为自定义，允许任意整数百分比并记忆', () => {
    setDpr(2)
    initDisplayScale()
    setCustomDisplayScalePercent(73)

    expect(useDisplayScale().mode.value).toBe('custom')
    expect(useDisplayScale().effectivePercent.value).toBe(73)
    expect(JSON.parse(localStorage.getItem('ai-stocks-display-scale') || '{}')).toEqual({
      mode: 'custom',
      customPercent: 73,
    })

    setDisplayScaleMode('auto')
    expect(useDisplayScale().effectivePercent.value).toBe(calculateAutoDisplayScalePercent())
  })

  it('从自动切到自定义时继承当前比例，不产生视觉跳变', () => {
    setDpr(2)
    initDisplayScale()
    setDisplayScaleMode('custom')

    expect(useDisplayScale().mode.value).toBe('custom')
    expect(useDisplayScale().effectivePercent.value).toBe(calculateAutoDisplayScalePercent())
  })

  it('窗口跨屏后重算自动比例，但不覆盖用户自定义比例', () => {
    vi.useFakeTimers()
    setScreenArea(3360, 1890)
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(85)

    setScreenArea(1800, 1169)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(100)

    setCustomDisplayScalePercent(117)
    setScreenArea(3360, 1890)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(117)
  })

  it('同尺寸跨屏未触发 resize 时，在窗口重新获得焦点后补算自动比例', () => {
    vi.useFakeTimers()
    setScreenArea(1800, 1169)
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(100)

    setScreenArea(3360, 1890)
    window.dispatchEvent(new Event('focus'))
    vi.advanceTimersByTime(130)

    expect(useDisplayScale().effectivePercent.value).toBe(85)
  })

  it('登录后复用全局用户偏好通道保存并恢复设置', async () => {
    login()
    prefApi.listUserPreferences.mockResolvedValue({
      items: [{ value: { mode: 'custom', customPercent: 76 } }],
    })

    await syncDisplayScalePreference()

    expect(useDisplayScale().mode.value).toBe('custom')
    expect(useDisplayScale().effectivePercent.value).toBe(76)
    expect(document.documentElement.style.getPropertyValue('--app-display-scale')).toBe('0.76')
    expect(document.documentElement.style.getPropertyValue('--app-display-scale-inverse')).toBe(
      String(1 / 0.76),
    )
  })
})

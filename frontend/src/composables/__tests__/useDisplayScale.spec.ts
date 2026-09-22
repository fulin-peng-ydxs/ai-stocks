// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth, writeAuth } from '@/api/authToken'
import {
  calculateAutoDisplayScalePercent,
  initDisplayScale,
  setAutoScaleResponsiveExponent,
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

function setScreenPosition(left: number, top: number): void {
  Object.defineProperty(window.screen, 'availLeft', { configurable: true, value: left })
  Object.defineProperty(window.screen, 'availTop', { configurable: true, value: top })
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
  afterEach(() => { resetDisplayScaleForTests(); vi.useRealTimers() })
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
    clearAuth()
    resetDisplayScaleForTests()
    setDpr(1)
    setScreenArea(1920, 1080)
    setScreenPosition(0, 0)
    document.body.innerHTML = ''
    prefApi.listUserPreferences.mockResolvedValue({ items: [] })
    prefApi.saveUserPreference.mockResolvedValue({})
  })

  it('自动模式按屏幕有效逻辑面积双向连续调节，并保留可读边界', () => {
    expect(calculateAutoDisplayScalePercent({ width: 1366, height: 768 })).toBe(90)
    expect(calculateAutoDisplayScalePercent({ width: 1800, height: 1169 })).toBe(95)
    expect(calculateAutoDisplayScalePercent({ width: 1920, height: 1080 })).toBe(94)
    expect(calculateAutoDisplayScalePercent({ width: 2560, height: 1440 })).toBe(100)
    expect(calculateAutoDisplayScalePercent({ width: 3360, height: 1890 })).toBe(106)
    expect(calculateAutoDisplayScalePercent({ width: 7680, height: 4320 })).toBe(110)
    expect(calculateAutoDisplayScalePercent({ width: 800, height: 600 })).toBe(90)
    expect(calculateAutoDisplayScalePercent({ width: 0, height: 0 })).toBe(100)
  })

  it('指数动态更新自动策略，零值有效且手动比例不受影响', () => {
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(94)
    setAutoScaleResponsiveExponent(0)
    expect(useDisplayScale().effectivePercent.value).toBe(100)
    setAutoScaleResponsiveExponent(0.08)
    expect(useDisplayScale().effectivePercent.value).toBe(96)
    setCustomDisplayScalePercent(125)
    setAutoScaleResponsiveExponent(1)
    expect(useDisplayScale().effectivePercent.value).toBe(125)
    setDisplayScaleMode('auto')
    expect(useDisplayScale().effectivePercent.value).toBe(90)
  })

  it.each([undefined, null, true, '0.2', NaN, Infinity, -0.1, 1.1])(
    '非法或缺失指数 %s 回退默认值', (value) => {
      initDisplayScale()
      setAutoScaleResponsiveExponent(0)
      setAutoScaleResponsiveExponent(value)
      expect(useDisplayScale().effectivePercent.value).toBe(94)
    },
  )

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
    expect(document.documentElement.style.getPropertyValue('--app-display-scale-inverse')).toBe(
      String(1 / 0.94),
    )
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
      customProfiles: [{ width: 1920, height: 1080, percent: 73 }],
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

  it('临时切到自动后再回自定义会恢复当前尺寸的既有档案', () => {
    initDisplayScale()
    setCustomDisplayScalePercent(83)
    setDisplayScaleMode('auto')
    expect(useDisplayScale().effectivePercent.value).toBe(94)

    setDisplayScaleMode('custom')

    expect(useDisplayScale().effectivePercent.value).toBe(83)
  })

  it('窗口跨屏后重算自动比例，但不覆盖用户自定义比例', () => {
    vi.useFakeTimers()
    setScreenArea(3360, 1890)
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(106)

    setScreenArea(1800, 1169)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(95)

    setCustomDisplayScalePercent(117)
    setScreenArea(3360, 1890)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(117)
  })

  it('自定义模式按显示器可用尺寸保存并自动采用最近档案', () => {
    vi.useFakeTimers()
    initDisplayScale()
    setCustomDisplayScalePercent(82)

    setScreenArea(3360, 1890)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(82)
    setCustomDisplayScalePercent(112)

    setScreenArea(1920, 1080)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(82)

    setScreenArea(1900, 1060)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(82)

    setScreenArea(2560, 1440)
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().effectivePercent.value).toBe(112)
  })

  it('同尺寸跨屏未触发 resize 时，在窗口重新获得焦点后补算自动比例', () => {
    vi.useFakeTimers()
    setScreenArea(1800, 1169)
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(95)

    setScreenArea(3360, 1890)
    window.dispatchEvent(new Event('focus'))
    vi.advanceTimersByTime(130)

    expect(useDisplayScale().effectivePercent.value).toBe(106)
  })

  it('跨到同尺寸同缩放屏幕时仍更新几何修订并触发布局复测', () => {
    vi.useFakeTimers()
    initDisplayScale()
    const originalPercent = useDisplayScale().effectivePercent.value
    const originalRevision = useDisplayScale().geometryRevision.value

    setScreenPosition(1920, 0)
    window.dispatchEvent(new Event('focus'))
    vi.advanceTimersByTime(130)

    expect(useDisplayScale().effectivePercent.value).toBe(originalPercent)
    expect(useDisplayScale().geometryRevision.value).toBe(originalRevision + 1)

    vi.advanceTimersByTime(420)
    expect(useDisplayScale().geometryRevision.value).toBe(originalRevision + 2)

    vi.advanceTimersByTime(500)
    expect(useDisplayScale().geometryRevision.value).toBe(originalRevision + 2)
  })

  it('屏幕签名尚未变化时也按真实视口事件重建并在稳定后复测', () => {
    vi.useFakeTimers()
    initDisplayScale()
    const originalRevision = useDisplayScale().geometryRevision.value

    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)
    expect(useDisplayScale().geometryRevision.value).toBe(originalRevision + 1)

    vi.advanceTimersByTime(420)
    expect(useDisplayScale().geometryRevision.value).toBe(originalRevision + 2)
  })

  it('视口变化时重建应用根缩放合成层并恢复原有内联 transform', () => {
    vi.useFakeTimers()
    document.body.innerHTML = '<div id="app" style="transform: scale(.8)"></div>'
    const appRoot = document.querySelector<HTMLElement>('#app')!
    const geometryRead = vi.spyOn(appRoot, 'getBoundingClientRect')
    initDisplayScale()

    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(130)

    expect(geometryRead).toHaveBeenCalledTimes(2)
    expect(appRoot.style.transform).toBe('scale(.8)')
    expect(appRoot.style.getPropertyPriority('transform')).toBe('')
  })

  it('跨屏没有窗口事件时仍补算，并在隐藏期间跳过探测', () => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    initDisplayScale()
    expect(useDisplayScale().effectivePercent.value).toBe(94)
    setScreenArea(3360, 1890)
    vi.advanceTimersByTime(1500)
    expect(useDisplayScale().effectivePercent.value).toBe(106)
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    setScreenArea(1366, 768)
    vi.advanceTimersByTime(1500)
    expect(useDisplayScale().effectivePercent.value).toBe(106)
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    vi.advanceTimersByTime(1500)
    expect(useDisplayScale().effectivePercent.value).toBe(90)
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

  it('登录后恢复当前显示器最接近的自定义比例档案', async () => {
    login()
    prefApi.listUserPreferences.mockResolvedValue({
      items: [{
        value: {
          mode: 'custom',
          customPercent: 100,
          customProfiles: [
            { width: 1920, height: 1080, percent: 84 },
            { width: 3360, height: 1890, percent: 108 },
          ],
        },
      }],
    })

    await syncDisplayScalePreference()

    expect(useDisplayScale().effectivePercent.value).toBe(84)
  })

  it('登录用户调整滑块时把当前尺寸档案写入全局偏好', async () => {
    vi.useFakeTimers()
    login()
    initDisplayScale()

    setCustomDisplayScalePercent(86)
    vi.advanceTimersByTime(260)
    await Promise.resolve()

    expect(prefApi.saveUserPreference).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'global',
      prefKey: 'display-scale',
      schemaVersion: 2,
      value: {
        mode: 'custom',
        customPercent: 86,
        customProfiles: [{ width: 1920, height: 1080, percent: 86 }],
      },
    }))
  })
})

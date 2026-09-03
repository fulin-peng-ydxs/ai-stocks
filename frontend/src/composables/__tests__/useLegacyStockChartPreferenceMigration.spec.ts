// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'

const mocks = vi.hoisted(() => ({
  token: 'token',
  list: vi.fn(),
  savePreference: vi.fn(),
}))

vi.mock('@/api/authToken', () => ({ getAccessToken: () => mocks.token }))
vi.mock('@/api/userPreferences', () => ({
  listUserPreferences: mocks.list,
  saveUserPreference: mocks.savePreference,
}))

const legacyCharts = {
  slot2: 'macd',
  slot3: 'volume',
  heightRatios: {
    kline: [1],
    'kline|volume': [0.7, 0.3],
    'kline|macd': [0.65, 0.35],
    'kline|volume|macd': [0.5, 0.3, 0.2],
    'kline|macd|volume': [0.55, 0.25, 0.2],
  },
}

describe('useLegacyStockChartPreferenceMigration', () => {
  beforeEach(() => {
    localStorage.clear()
    mocks.token = 'token'
    mocks.list.mockReset()
    mocks.savePreference.mockReset()
  })

  it('先迁入组件用户配置，再清理页面偏好中的旧 charts 字段', async () => {
    const setComponentKnob = vi.fn()
    const saveRemoteUserConfig = vi.fn().mockResolvedValue(undefined)
    mocks.list.mockResolvedValue({
      items: [{
        scope: 'page', pageKey: 'stocks', prefKey: 'settings', schemaVersion: 1,
        value: { adjustMode: 'hfq', charts: legacyCharts },
      }],
    })
    localStorage.setItem(
      'ai-stocks:page-settings:stocks',
      JSON.stringify({ adjustMode: 'hfq', charts: legacyCharts }),
    )

    mount(defineComponent({
      setup() {
        useLegacyStockChartPreferenceMigration({
          pageKey: 'stocks',
          componentSourceOf: () => 'default',
          setComponentKnob,
          whenRemoteHydrated: async () => undefined,
          saveRemoteUserConfig,
          remoteSaveFailed: () => false,
        })
        return () => null
      },
    }))
    await flushPromises()

    expect(setComponentKnob).toHaveBeenCalledWith('chart', 'stockChart', legacyCharts)
    expect(saveRemoteUserConfig).toHaveBeenCalledOnce()
    expect(mocks.savePreference).toHaveBeenCalledWith(expect.objectContaining({
      pageKey: 'stocks',
      value: { adjustMode: 'hfq' },
    }))
    expect(JSON.parse(localStorage.getItem('ai-stocks:page-settings:stocks')!))
      .toEqual({ adjustMode: 'hfq' })
    expect(saveRemoteUserConfig.mock.invocationCallOrder[0])
      .toBeLessThan(mocks.savePreference.mock.invocationCallOrder[0])
  })

  it('已有组件用户配置时不再查询旧偏好或覆盖新值', async () => {
    const setComponentKnob = vi.fn()
    mocks.list.mockResolvedValue({
      items: [{
        scope: 'page', pageKey: 'board', prefKey: 'settings', schemaVersion: 1,
        value: { charts: legacyCharts },
      }],
    })

    mount(defineComponent({
      setup() {
        useLegacyStockChartPreferenceMigration({
          pageKey: 'board',
          componentSourceOf: () => 'user',
          setComponentKnob,
          whenRemoteHydrated: async () => undefined,
          saveRemoteUserConfig: vi.fn(),
          remoteSaveFailed: () => false,
        })
        return () => null
      },
    }))
    await flushPromises()

    expect(setComponentKnob).not.toHaveBeenCalled()
    expect(mocks.list).not.toHaveBeenCalled()
    expect(mocks.savePreference).not.toHaveBeenCalled()
  })
})

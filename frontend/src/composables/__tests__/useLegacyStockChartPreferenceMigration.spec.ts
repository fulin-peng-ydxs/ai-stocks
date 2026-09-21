// @vitest-environment jsdom
import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import { normalizeStockChartPreferences } from '@/composables/useStockChartPreferences'
import { normalizeStockAnalysisPreferences } from '@/composables/useStockAnalysisSession'
import { normalizeSectorAnalysisPreferences } from '@/composables/useSectorAnalysisPreferences'

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

const legacyAnalysis = {
  defaultChartMode: 'kline',
  showAnalysisPanel: false,
  compareRange: 120,
  benchmarkCode: '000300.SH',
  compareMetrics: ['daily', 'cum'],
  defaultCompareMetric: 'daily',
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
        value: { adjustMode: 'hfq', charts: legacyCharts, ...legacyAnalysis },
      }],
    })
    localStorage.setItem(
      'ai-stocks:page-settings:stocks',
      JSON.stringify({ adjustMode: 'hfq', charts: legacyCharts, ...legacyAnalysis }),
    )

    mount(defineComponent({
      setup() {
        useLegacyStockChartPreferenceMigration({
          pageKey: 'stocks',
          analysisType: 'stock',
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

    expect(setComponentKnob).toHaveBeenCalledWith(
      'chart',
      'stockChart',
      normalizeStockChartPreferences(legacyCharts),
    )
    expect(setComponentKnob).toHaveBeenCalledWith(
      'chart',
      'stockAnalysis',
      normalizeStockAnalysisPreferences(legacyAnalysis),
    )
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

  it('页面偏好已完成水合时先保存组件配置，再调用页面 schema 保存清理旧字段', async () => {
    const setComponentKnob = vi.fn()
    const saveRemoteUserConfig = vi.fn().mockResolvedValue(undefined)
    const savePageSettings = vi.fn().mockResolvedValue(undefined)
    const legacySnapshot = ref({ adjustMode: 'qfq', ...legacyAnalysis })

    mount(defineComponent({
      setup() {
        useLegacyStockChartPreferenceMigration({
          pageKey: 'board',
          analysisType: 'stock',
          componentSourceOf: () => 'default',
          setComponentKnob,
          whenRemoteHydrated: async () => undefined,
          whenPageSettingsHydrated: async () => undefined,
          legacySnapshot,
          saveRemoteUserConfig,
          savePageSettings,
          remoteSaveFailed: () => false,
        })
        return () => null
      },
    }))
    await flushPromises()

    expect(setComponentKnob).toHaveBeenCalledWith(
      'chart',
      'stockAnalysis',
      normalizeStockAnalysisPreferences(legacyAnalysis),
    )
    expect(saveRemoteUserConfig).toHaveBeenCalledOnce()
    expect(savePageSettings).toHaveBeenCalledOnce()
    expect(saveRemoteUserConfig.mock.invocationCallOrder[0])
      .toBeLessThan(savePageSettings.mock.invocationCallOrder[0])
    expect(mocks.list).not.toHaveBeenCalled()
  })

  it('已有组件用户配置时不覆盖新值，仅清理页面偏好旧字段', async () => {
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
    expect(mocks.list).toHaveBeenCalledOnce()
    expect(mocks.savePreference).toHaveBeenCalledWith(expect.objectContaining({
      pageKey: 'board',
      value: {},
    }))
  })

  it('板块页把独立指标模型迁入 sectorAnalysis，而不是股票默认项', async () => {
    const setComponentKnob = vi.fn()
    const sectorLegacy = {
      defaultChartMode: 'compare',
      showAnalysisPanel: true,
      benchmarkCode: '000905.SH',
      compareMetrics: ['cum', 'inflow'],
      defaultCompareMetric: 'inflow',
      compareWindow: 120,
    }

    mount(defineComponent({
      setup() {
        useLegacyStockChartPreferenceMigration({
          pageKey: 'sectors',
          analysisType: 'sector',
          componentSourceOf: () => 'default',
          setComponentKnob,
          whenRemoteHydrated: async () => undefined,
          whenPageSettingsHydrated: async () => undefined,
          legacySnapshot: ref(sectorLegacy),
          saveRemoteUserConfig: vi.fn().mockResolvedValue(undefined),
          savePageSettings: vi.fn().mockResolvedValue(undefined),
          remoteSaveFailed: () => false,
        })
        return () => null
      },
    }))
    await flushPromises()

    expect(setComponentKnob).toHaveBeenCalledWith(
      'chart',
      'sectorAnalysis',
      normalizeSectorAnalysisPreferences(sectorLegacy),
    )
    expect(setComponentKnob).not.toHaveBeenCalledWith(
      'chart',
      'stockAnalysis',
      expect.anything(),
    )
  })

  it('可按属性归属把旧页面展示偏好分别迁入布局与组件配置', async () => {
    const setComponentKnob = vi.fn()
    const setKnob = vi.fn()
    const saveRemoteUserConfig = vi.fn().mockResolvedValue(undefined)
    const savePageSettings = vi.fn().mockResolvedValue(undefined)

    mount(defineComponent({
      setup() {
        useLegacyStockChartPreferenceMigration({
          pageKey: 'stock-detail',
          sourceOf: () => 'default',
          setKnob,
          componentSourceOf: () => 'default',
          setComponentKnob,
          whenRemoteHydrated: async () => undefined,
          whenPageSettingsHydrated: async () => undefined,
          legacySnapshot: ref({
            adjustMode: 'qfq',
            showIndicatorSnapshot: false,
            indicators: { ma20: true, ma60: false, is_vol_breakout: true },
          }),
          saveRemoteUserConfig,
          savePageSettings,
          remoteSaveFailed: () => false,
          legacyLayoutMappings: [
            {
              legacyField: 'showIndicatorSnapshot',
              path: 'slots.indicatorSnapshot.visible',
            },
          ],
          legacyComponentMappings: [
            {
              legacyField: 'indicators',
              slotId: 'indicatorSnapshot',
              componentField: 'visibleIndicatorFields',
              transform: (value) => Object.entries(value as Record<string, boolean>)
                .filter(([, visible]) => visible)
                .map(([field]) => field),
            },
          ],
        })
        return () => null
      },
    }))
    await flushPromises()

    expect(setKnob).toHaveBeenCalledWith('slots.indicatorSnapshot.visible', false)
    expect(setComponentKnob).toHaveBeenCalledWith(
      'indicatorSnapshot',
      'visibleIndicatorFields',
      ['ma20', 'is_vol_breakout'],
    )
    expect(saveRemoteUserConfig).toHaveBeenCalledOnce()
    expect(savePageSettings).toHaveBeenCalledOnce()
  })
})

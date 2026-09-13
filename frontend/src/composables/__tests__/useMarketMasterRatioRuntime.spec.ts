import { describe, expect, it } from 'vitest'
import { useMarketMasterRatioRuntime } from '@/composables/useMarketMasterRatioRuntime'

describe('useMarketMasterRatioRuntime', () => {
  it('拖动会话值只供采用按钮读取，抽屉继续回显已配置生效基线', () => {
    const runtime = useMarketMasterRatioRuntime()

    runtime.setCurrentMasterRatioSample({
      width: 1200,
      ratio: 70,
      configuredRatio: 65,
    })

    expect(runtime.componentRuntimeValueOf('workspace', 'masterRatio')).toBe(65)
    expect(runtime.componentRuntimeValueOf('workspace', 'masterRatioProfiles')).toEqual({
      width: 1200,
      ratio: 70,
    })
  })
})

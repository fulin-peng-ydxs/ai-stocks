import { describe, expect, it } from 'vitest'
import {
  closestMasterDetailRatioProfile,
  normalizeMasterDetailRatioProfiles,
  upsertMasterDetailRatioProfile,
} from '@/layout/masterDetailRatioProfiles'

describe('masterDetailRatioProfiles', () => {
  it('归一化非法项、重复宽度并稳定排序', () => {
    expect(normalizeMasterDetailRatioProfiles({ profiles: [
      { width: 1920, ratio: 46 },
      { width: -1, ratio: 50 },
      { width: 1280, ratio: 52 },
      { width: 1920, ratio: 47 },
      { width: 1400, ratio: 80 },
    ] })).toEqual({ profiles: [
      { width: 1280, ratio: 52 },
      { width: 1920, ratio: 47 },
    ] })
  })

  it('只在15%范围内选择相对距离最近的档案', () => {
    const config = { profiles: [{ width: 1280, ratio: 52 }, { width: 1920, ratio: 46 }] }
    expect(closestMasterDetailRatioProfile(config, 1800)).toEqual({ width: 1920, ratio: 46 })
    expect(closestMasterDetailRatioProfile(config, 1500)).toBeUndefined()
  })

  it('5%内更新现有档案，超过范围时新增', () => {
    const original = { profiles: [{ width: 1280, ratio: 52 }] }
    expect(upsertMasterDetailRatioProfile(original, { width: 1320, ratio: 50 })).toEqual({
      profiles: [{ width: 1320, ratio: 50 }],
    })
    expect(upsertMasterDetailRatioProfile(original, { width: 1600, ratio: 48 })).toEqual({
      profiles: [{ width: 1280, ratio: 52 }, { width: 1600, ratio: 48 }],
    })
  })
})

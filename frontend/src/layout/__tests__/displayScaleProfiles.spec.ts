import { describe, expect, it } from 'vitest'
import {
  closestDisplayScaleProfile,
  normalizeDisplayScaleProfiles,
  upsertDisplayScaleProfile,
} from '../displayScaleProfiles'

describe('界面比例尺寸档案', () => {
  it('清理非法档案并对相同尺寸保留最新项', () => {
    expect(normalizeDisplayScaleProfiles([
      { width: 1920, height: 1080, percent: 80 },
      { width: 1920, height: 1080, percent: 84 },
      { width: 0, height: 1080, percent: 90 },
      { width: 2560, height: 1440, percent: 151 },
    ])).toEqual([{ width: 1920, height: 1080, percent: 84 }])
  })

  it('在宽高容差内选择综合距离最近的档案', () => {
    const profiles = [
      { width: 1920, height: 1080, percent: 84 },
      { width: 2560, height: 1440, percent: 100 },
    ]
    expect(closestDisplayScaleProfile(profiles, { width: 2000, height: 1120 })?.percent).toBe(84)
    expect(closestDisplayScaleProfile(profiles, { width: 2200, height: 900 })).toBeUndefined()
  })

  it('相近尺寸更新原档案，明显不同尺寸新增档案', () => {
    const updated = upsertDisplayScaleProfile(
      [{ width: 1920, height: 1080, percent: 84 }],
      { width: 1900, height: 1060, percent: 86 },
    )
    expect(updated).toEqual([{ width: 1900, height: 1060, percent: 86 }])
    expect(upsertDisplayScaleProfile(updated, {
      width: 3360,
      height: 1890,
      percent: 108,
    })).toEqual([
      { width: 1900, height: 1060, percent: 86 },
      { width: 3360, height: 1890, percent: 108 },
    ])
  })
})

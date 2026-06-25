/**
 * 自适应策略摘要（P8）——校验响应式策略统一命名完整、describeResponsive 分类正确、
 * 列数按断点推导无误。把"散落在注释里的响应式口径"变成可测的单一事实源。
 */
import { describe, expect, it } from 'vitest'
import { RESPONSIVE_PROFILES, columnsAt, describeResponsive } from '../responsive'
import { PAGE_REGISTRY, getPageLayout } from '../pageRegistry'
import type { PageLayout } from '../schema'

describe('自适应策略摘要（P8）', () => {
  it('三类策略命名完整且有说明', () => {
    for (const key of ['single-column', 'safe-reflow', 'mixed-panel'] as const) {
      expect(RESPONSIVE_PROFILES[key].label).toBeTruthy()
      expect(RESPONSIVE_PROFILES[key].desc).toBeTruthy()
    }
  })

  it('注册表每个页面的 responsiveProfile 都在统一命名表内', () => {
    for (const entry of PAGE_REGISTRY) {
      expect(RESPONSIVE_PROFILES[entry.responsiveProfile], `${entry.pageKey} profile 未登记`).toBeTruthy()
    }
  })

  it('单列页（board）：三档恒 1 列，主表归入不可重排（grow）', () => {
    const layout = getPageLayout('board')
    const s = describeResponsive(layout, 'single-column')
    expect(s.tiers.map((t) => t.columns)).toEqual([1, 1, 1])
    expect(s.reflowableSlots).toEqual([])
    const locked = s.lockedSlots.find((x) => x.id === 'table')
    expect(locked?.growMain).toBe(true)
  })

  it('嵌套/overlay slot 不进响应式摘要（只看顶层主区）', () => {
    // backtest：顶层主区只有 body（section），trades 为嵌套、settings 不存在于此页。
    const s = describeResponsive(getPageLayout('backtest'), 'mixed-panel')
    const ids = [...s.reflowableSlots, ...s.lockedSlots].map((x) => x.id)
    expect(ids).toContain('body')
    expect(ids).not.toContain('trades')
  })

  it('describeResponsive 正确分类可重排 slot 并按断点推导多档列数', () => {
    const layout: PageLayout = {
      pageKey: 't',
      archetype: 'dashboard',
      hasActionRegion: false,
      density: 'standard',
      responsive: { allowReflow: true, breakpoints: [{ minWidth: 0, columns: 1 }, { minWidth: 1024, columns: 2 }, { minWidth: 1440, columns: 3 }] },
      editable: [],
      slots: [
        { id: 'k1', component: 'kpi-grid', region: 'main', order: 1 },
        { id: 'c1', component: 'chart', region: 'main', order: 2 },
      ],
    }
    expect(columnsAt(layout, 800)).toBe(1)
    expect(columnsAt(layout, 1200)).toBe(2)
    expect(columnsAt(layout, 1500)).toBe(3)
    const s = describeResponsive(layout, 'safe-reflow')
    // kpi-grid / chart 目录默认 reflowable=true
    expect(s.reflowableSlots.map((x) => x.id).sort()).toEqual(['c1', 'k1'])
    expect(s.lockedSlots).toEqual([])
    // 设备档位 1100 / 1366 / 1440：按断点 [0→1,1024→2,1440→3] 推导 = [2,2,3]。
    expect(s.tiers.map((t) => t.columns)).toEqual([2, 2, 3])
  })
})

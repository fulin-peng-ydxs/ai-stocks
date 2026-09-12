/**
 * 自适应策略摘要（P8）——校验响应式策略统一命名完整、describeResponsive 分类正确、
 * 列数按断点推导无误。把"散落在注释里的响应式口径"变成可测的单一事实源。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
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

  it('目标响应式画像与实际 layout.responsive 基线不冲突', () => {
    for (const entry of PAGE_REGISTRY) {
      const layout = entry.layout
      if (entry.responsiveProfile === 'single-column') {
        expect(layout.responsive.allowReflow, `${entry.pageKey} 单列画像不得开启重排`).toBe(false)
        expect(
          layout.responsive.breakpoints.every((breakpoint) => breakpoint.columns === 1),
          `${entry.pageKey} 单列画像的所有断点都必须保持一列`,
        ).toBe(true)
      } else if (entry.responsiveProfile === 'safe-reflow') {
        expect(layout.responsive.allowReflow, `${entry.pageKey} 安全重排画像必须真实开启重排`).toBe(true)
      } else {
        expect(
          ['workbench', 'master-detail'].includes(layout.archetype),
          `${entry.pageKey} 混合面板画像只适用于工作台或主从原型`,
        ).toBe(true)
        expect(layout.responsive.allowReflow, `${entry.pageKey} 混合面板由成长/滚动承接，不启用多列重排`).toBe(false)
      }
    }
  })

  it('页面布局工作台把 profile 明确展示为目标策略', () => {
    const pageView = readFileSync(new URL('../../views/layout/LayoutPagesView.vue', import.meta.url), 'utf8')
    const preview = readFileSync(new URL('../components/LayoutPagePreview.vue', import.meta.url), 'utf8')
    expect(pageView).toContain('label="目标响应式策略"')
    expect(preview).toContain('目标 · {{ summary.profileLabel }}')
  })

  it('混合面板页（board）：三档保持单列布局契约，主从工作台归入不可重排', () => {
    const layout = getPageLayout('board')
    const s = describeResponsive(layout, 'mixed-panel')
    expect(s.tiers.map((t) => t.columns)).toEqual([1, 1, 1])
    expect(s.reflowableSlots).toEqual([])
    expect(s.lockedSlots.map((slot) => slot.id)).toContain('workspace')
  })

  it('股票主从工作台为可拖动三列布局，最小宽度覆盖列表、分隔条和分析区', () => {
    const workspace = readFileSync(
      new URL('../../components/MarketMasterDetailWorkspace.vue', import.meta.url),
      'utf8',
    )
    expect(workspace).toContain('const MASTER_MIN_WIDTH = 360')
    expect(workspace).toContain('const MASTER_RATIO_DEFAULT = 45')
    expect(workspace).toContain('const DETAIL_MIN_WIDTH = 240')
    expect(workspace).toContain('const COMPACT_MAX_WIDTH = 720')
    expect(workspace).toContain('closestMasterDetailRatioProfile')
    expect(workspace).toContain('grid-template-columns: minmax(360px, 45%) 12px minmax(240px, 1fr)')
    expect(workspace).toContain('min-width: 612px')

    const analysisPanel = readFileSync(
      new URL('../../components/StockAnalysisPanel.vue', import.meta.url),
      'utf8',
    )
    expect(analysisPanel).toContain('container-type: inline-size')
    expect(analysisPanel).toContain('@container (max-width: 700px)')
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

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
// @ts-expect-error ECharts 5.6 的运行时子模块没有对应 lib 路径类型声明。
import { buildTooltipMarkup, TooltipMarkupStyleCreator } from 'echarts/lib/component/tooltip/tooltipMarkup.js'
import GrowthChart from '@/components/GrowthChart.vue'
import type { GrowthPoint } from '@/api/training'

const chart = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }))
vi.mock('echarts', () => ({ init: vi.fn(() => chart) }))

interface GrowthOption {
  series: Array<{
    name: string
    data: Array<number | null>
    tooltip: { valueFormatter: (value: number | null) => string }
  }>
  yAxis: Array<{
    axisLabel: { formatter: (value: number) => string }
    axisPointer: { label: { formatter: (params: { value: number }) => string } }
  }>
}

let wrapper: VueWrapper | undefined
function render(point: Partial<GrowthPoint>): GrowthOption {
  wrapper = mount(GrowthChart, {
    props: { data: [{ id: 'growth-1', score: 85, total_return: 0.07,
      win_rate: null, grade: null, completed_at: null, ...point }] },
  })
  return chart.setOption.mock.calls.at(-1)![0] as GrowthOption
}

/** 沿 ECharts 轴悬浮的真实 markup 渲染入口验证，避免只断言 formatter 函数存在。 */
function tooltipHtml(option: GrowthOption): string {
  return buildTooltipMarkup({
    type: 'section', header: '#1', blocks: option.series.map(series => ({
      type: 'nameValue', name: series.name, value: series.data[0],
      valueFormatter: series.tooltip?.valueFormatter,
    })),
  }, new TooltipMarkupStyleCreator(), 'html', undefined, false, {})
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => wrapper?.unmount())

describe('成长曲线数值展示', () => {
  it('序列保留计算精度，悬浮收益率两位、评分一位，与两侧坐标轴一致', () => {
    const option = render({})
    expect(option.series[1]!.data[0]).toBe(0.07 * 100)
    expect(option.series[1]!.data[0]).not.toBe(7)
    const html = tooltipHtml(option)
    expect(html).toContain('>+7.00%<')
    expect(html).toContain('>85.0<')
    expect(html).not.toContain('7.000000000000001')
    expect(option.yAxis[0]!.axisLabel.formatter(85)).toBe('85.0')
    expect(option.yAxis[0]!.axisPointer.label.formatter({ value: 85 })).toBe('85.0')
    expect(option.yAxis[1]!.axisLabel.formatter(0.07 * 100)).toBe('+7.00%')
  })

  it.each([
    { score: 85.05, total_return: -0.07, scoreText: '85.1', returnText: '-7.00%' },
    { score: 0, total_return: -0, scoreText: '0.0', returnText: '0.00%' },
    { score: null, total_return: null, scoreText: '—', returnText: '—' },
    { score: NaN, total_return: Infinity, scoreText: '—', returnText: '—' },
  ])('悬浮分别处理评分和收益率的边界：$score / $total_return', point => {
    const html = tooltipHtml(render(point))
    expect(html).toContain(`>${point.scoreText}<`)
    expect(html).toContain(`>${point.returnText}<`)
    expect(html).not.toMatch(/NaN|Infinity|-0\.00%/)
  })
})

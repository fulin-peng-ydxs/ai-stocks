import { describe, expect, it } from 'vitest'
import { graphic, Model } from 'echarts'
import { marketAxisPointerLabel } from '@/components/chartAxisLabel'

// 直接验证补丁所在的模块入口，防止依赖重装后标签几何回退。
const helperModule = 'echarts/lib/component/axisPointer/viewHelper.js'
const { buildLabelElOption } = await import(helperModule) as typeof import(
  '../../../node_modules/echarts/types/src/component/axisPointer/viewHelper'
)

describe('彩色光标标签几何', () => {
  it.each(['right', 'left'] as const)('按真实富文本宽度贴合 %s 侧锚点', (align) => {
    const label = marketAxisPointerLabel({
      up: '#f66055', down: '#1ec96e', label: '#6e7078',
      tooltipBackground: '#fff', tooltipBorder: '#ddd',
    }, (value) => `${value.toFixed(2)}%`)
    const pointer = new Model({ value: 12.34, label: {
      ...label, fontSize: 12, padding: [4, 8],
    } })
    const axisModel = {
      axis: {
        type: 'value', dim: 'y', index: 0,
        scale: { parse: Number, getLabel: ({ value }: { value: number }) => String(value) },
      },
    }
    type Args = Parameters<typeof buildLabelElOption>
    const result = {} as Args[0]
    buildLabelElOption(result, axisModel as unknown as Args[1], pointer as unknown as Args[2], {
      getWidth: () => 800, getHeight: () => 400,
    } as Args[3], { position: [400, 200], align, verticalAlign: 'middle' })
    const rendered = result.label!
    const width = new graphic.Text({ style: rendered.style }).getBoundingRect().width
    expect(rendered.style!.text).toBe('{u|12.34%}')
    expect(rendered.x! + (align === 'right' ? width : 0)).toBeCloseTo(400, 1)
  })
})

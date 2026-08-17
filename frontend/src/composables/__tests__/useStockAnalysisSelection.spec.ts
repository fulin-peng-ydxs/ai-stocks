import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useStockAnalysisSelection } from '@/composables/useStockAnalysisSelection'

describe('useStockAnalysisSelection', () => {
  it('统一维护当前观察、对比队列、上限和移除回退', async () => {
    const onLimitReached = vi.fn()
    const source = ref([
      { code: '000001.SZ', name: '平安银行', last_date: '2026-08-14' },
      { code: '600000.SH', name: '浦发银行', last_date: '2026-08-13' },
    ])
    const selection = useStockAnalysisSelection(source, { maxItems: 2, onLimitReached })

    expect(selection.activeItem.value?.code).toBe('000001.SZ')
    selection.togglePinned(source.value[0]!)
    selection.select(source.value[1]!)
    expect(selection.items.value.map((item) => item.code)).toEqual(['600000.SH', '000001.SZ'])
    expect(selection.activeItem.value?.last_date).toBe('2026-08-13')

    expect(selection.togglePinned({ code: '300001.SZ', name: '特锐德', last_date: '2026-08-12' })).toBe(false)
    expect(onLimitReached).toHaveBeenCalledWith(2)

    selection.remove('600000.SH')
    expect(selection.activeCode.value).toBe('000001.SZ')

    source.value = [{ code: '300001.SZ', name: '特锐德', last_date: '2026-08-12' }]
    await nextTick()
    expect(selection.activeCode.value).toBe('300001.SZ')
    expect(selection.isPinned('000001.SZ')).toBe(true)

    selection.clear()
    expect(selection.items.value.map((item) => item.code)).toEqual(['300001.SZ'])
  })

  it('激活队列中已有项只移动高亮,队列顺序不变', () => {
    const source = ref([
      { code: 'A', name: '甲' },
      { code: 'B', name: '乙' },
      { code: 'C', name: '丙' },
    ])
    const selection = useStockAnalysisSelection(source, { maxItems: 6 })

    selection.togglePinned(source.value[0]!)
    selection.togglePinned(source.value[1]!)
    selection.togglePinned(source.value[2]!)
    expect(selection.items.value.map((item) => item.code)).toEqual(['A', 'B', 'C'])

    selection.activate('C')
    expect(selection.activeCode.value).toBe('C')
    expect(selection.items.value.map((item) => item.code)).toEqual(['A', 'B', 'C'])
  })
})

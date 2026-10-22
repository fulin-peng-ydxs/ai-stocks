// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { getPublicDictItems } from '@/api/dict'
import { provideTradeDisciplineCategories, tradeConditionMeta } from '../useTradeDisciplineCategories'

vi.mock('@/api/dict', () => ({ getPublicDictItems: vi.fn() }))

describe('交易纪律分类字典', () => {
  it('合并并发加载，失败与兜底显示错误，重试恢复候选并过滤保留编码', async () => {
    const api = vi.mocked(getPublicDictItems)
    api.mockRejectedValueOnce(new Error('offline'))
    let dictionary!: ReturnType<typeof provideTradeDisciplineCategories>
    const wrapper = mount(defineComponent({ setup() { dictionary = provideTradeDisciplineCategories(); return () => h('div') } }))
    await Promise.all([dictionary.load(), dictionary.load()])
    expect(api).toHaveBeenCalledTimes(1)
    expect(dictionary.error.value).toBe(true)
    api.mockResolvedValueOnce({ fallback: true, items: [], type_code: 'test', version: 'builtin' })
    await dictionary.load()
    expect(dictionary.error.value).toBe(true)
    api.mockResolvedValueOnce({ fallback: false, items: [
      { code: 'earnings', label: '业绩条件' }, { code: 'notes', label: '保留分类' },
    ] as any, type_code: 'test', version: '1' })
    await dictionary.load()
    await flushPromises()
    expect(dictionary.error.value).toBe(false)
    expect(dictionary.loading.value).toBe(false)
    expect(dictionary.categories.value).toEqual([{ value: 'earnings', label: '业绩条件' }])
    expect(tradeConditionMeta(dictionary.categories.value).stockConditions.collapseSections.map(item => item.key))
      .toEqual(['basic', 'risk', 'technical', 'earnings', 'notes'])
    wrapper.unmount()
  })
})

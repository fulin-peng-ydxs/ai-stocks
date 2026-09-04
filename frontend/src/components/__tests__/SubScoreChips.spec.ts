// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SubScoreChips from '@/components/SubScoreChips.vue'

describe('SubScoreChips', () => {
  it('统一渲染评分等级，省略提示交给全局自动机制', () => {
    const wrapper = mount(SubScoreChips, {
      props: {
        scoreKeys: ['high', 'mid', 'low'],
        scores: { high: 97, mid: 73, low: 32 },
        labelOf: (key) => ({
          high: '放量突破(固定20×2)',
          mid: '距离年高',
          low: '换手健康',
        })[key] || key,
      },
    })
    const chips = wrapper.findAll('.sub-score-chip')

    expect(chips.map((chip) => chip.classes())).toEqual([
      ['sub-score-chip', 'hi'],
      ['sub-score-chip', 'mid'],
      ['sub-score-chip', 'lo'],
    ])
    expect(chips[0].text()).toBe('放量突破(固定20×2)97')
    expect(chips[0].attributes('title')).toBeUndefined()

    expect(chips[0].attributes('title')).toBeUndefined()
  })
})

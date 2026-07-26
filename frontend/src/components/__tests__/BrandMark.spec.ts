// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BrandMark from '../BrandMark.vue'

describe('BrandMark 品牌一致性', () => {
  it('登录页与工作台共用单一外观，不暴露场景变体', () => {
    const wrapper = mount(BrandMark, { props: { tone: 'light' } })

    expect(wrapper.attributes('role')).toBe('img')
    expect(wrapper.attributes('aria-label')).toBe('复盘啦')
    expect(wrapper.classes()).toEqual(['brand-mark', 'brand-mark--light'])
    expect(wrapper.html()).not.toContain('brand-mark--shell')
    expect(wrapper.html()).not.toContain('brand-mark--login')
  })

  it('图标内部标记消费共享中性高亮色，不残留偏暖白色', () => {
    const wrapper = mount(BrandMark, { props: { tone: 'dark' } })

    expect(wrapper.findAll('[stroke="var(--shell-control-mark)"]')).toHaveLength(2)
    expect(wrapper.findAll('[fill="var(--shell-control-mark)"]')).toHaveLength(2)
    expect(wrapper.html()).not.toContain('#fff7f4')
  })
})

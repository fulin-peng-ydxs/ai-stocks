// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import ScoreGradeTag from '@/components/ScoreGradeTag.vue'

describe('ScoreGradeTag', () => {
  it.each([
    ['主升浪核心', 'danger'],
    ['龙头候选', 'warning'],
    ['观察', 'success'],
    ['未知评级', 'info'],
  ])('将 %s 统一映射为 %s 标签', (grade, type) => {
    const wrapper = mount(ScoreGradeTag, {
      props: { grade },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.text()).toBe(grade)
    expect(wrapper.get('.el-tag').classes()).toContain(`el-tag--${type}`)
    expect(wrapper.get('.el-tag').classes()).toContain('el-tag--small')
    expect(wrapper.find('.app-table-tag-shell').exists()).toBe(true)
  })
})

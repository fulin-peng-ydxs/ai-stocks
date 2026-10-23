// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import BorderStatePreview from '../components/BorderStatePreview.vue'

describe('真实边界状态样板', () => {
  it('错误/禁用使用真实表单分支，结果内容替换保持同一外框', async () => {
    const wrapper = mount(BorderStatePreview, { global: { plugins: [ElementPlus] } })
    const checks = wrapper.findAll('.el-checkbox input')
    await checks[1].setValue(true)
    expect(wrapper.findAll('.el-form-item.is-error')).toHaveLength(4)
    await checks[0].setValue(true)
    expect(wrapper.find('.el-range-editor.is-disabled').exists()).toBe(true)
    expect(wrapper.find('.el-textarea.is-disabled').exists()).toBe(true)
    expect(wrapper.find('.seg-btn.active').attributes('disabled')).toBeDefined()
    const frame = wrapper.find('.app-table-card').element
    await wrapper.get('input[type="radio"][value="error"]').setValue(true)
    expect(wrapper.find('.app-state-block--error').exists()).toBe(true)
    expect(wrapper.find('.app-table-card').element).toBe(frame)
    wrapper.unmount()
  })
})

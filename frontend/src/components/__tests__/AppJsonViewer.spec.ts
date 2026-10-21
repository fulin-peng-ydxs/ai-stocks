// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppJsonViewer from '../AppJsonViewer.vue'

describe('只读原始数据查看器', () => {
  it('默认只展开根字段，按需展开数组和对象，保留零、布尔值及空值', async () => {
    const wrapper = mount(AppJsonViewer, { props: { source: JSON.stringify({ zero: 0, flag: false,
      empty: null, items: [{ missing: '09:31' }], blank: {} }) } })
    await flushPromises()
    expect(wrapper.text()).toContain('zero:0')
    expect(wrapper.text()).toContain('flag:false')
    expect(wrapper.text()).toContain('empty:null')
    expect(wrapper.text()).toContain('数组 · 1 项')
    expect(wrapper.text()).not.toContain('09:31')
    const items = wrapper.findAll('.el-tree-node__content').find(node => node.text().startsWith('items:'))!
    await items.trigger('click')
    await flushPromises()
    const first = wrapper.findAll('.el-tree-node__content').find(node => node.text().startsWith('0:'))!
    await first.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('missing:"09:31"')
    expect(wrapper.find('[role="tree"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('更换记录清除原树，旧文本和无效 JSON 保留原文', async () => {
    const wrapper = mount(AppJsonViewer, { props: { source: '{"old":1}' } })
    await wrapper.setProps({ source: '{"new":2}' })
    await flushPromises()
    expect(wrapper.text()).toContain('new:2')
    expect(wrapper.text()).not.toContain('old:')
    await wrapper.setProps({ source: '历史诊断：<script>alert(1)</script>' })
    expect(wrapper.get('pre').text()).toBe('历史诊断：<script>alert(1)</script>')
    expect(wrapper.find('script').exists()).toBe(false)
    wrapper.unmount()
  })
  it('深层数组未展开时不装载，保留标点键名及字符串原值', async () => {
    const wrapper = mount(AppJsonViewer, { props: { source: JSON.stringify({
      'a.b': { '<b>': 'hello\nworld' }, a: { b: 4 }, large: Array.from({ length: 5000 }, (_, i) => i),
    }) } })
    await flushPromises()
    expect(wrapper.findAll('[role="treeitem"]').length).toBe(4)
    expect(wrapper.text()).toContain('数组 · 5000 项')
    expect(wrapper.find('b').exists()).toBe(false)
    wrapper.unmount()
  })
})

// @vitest-environment jsdom
import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PageSegmented from '@/components/PageSegmented.vue'
import LayoutPagePreview from '../components/LayoutPagePreview.vue'
import { getPageLayout, type ResponsiveProfile } from '../pageRegistry'
import type { PageLayout } from '../schema'

function mountPreview(layout: PageLayout, profile: ResponsiveProfile) {
  return shallowMount(LayoutPagePreview, {
    props: { layout, profile },
    global: { stubs: { 'el-tag': true } },
  })
}

describe('LayoutPagePreview', () => {
  it('单列页面隐藏无效宽度切换并把浮层纳入同一结构图', () => {
    const wrapper = mountPreview(getPageLayout('board'), 'mixed-panel')

    expect(wrapper.text()).toContain('三档宽度均为 1 列，无需切换')
    expect(wrapper.findComponent(PageSegmented).exists()).toBe(false)
    expect(wrapper.find('.region-off-flow').exists()).toBe(true)
    expect(wrapper.find('.preview-side').exists()).toBe(false)
  })

  it('列数确有变化时显示带宽度和列数的明确选择项', () => {
    const layout: PageLayout = {
      pageKey: 'preview-test',
      archetype: 'dashboard',
      hasActionRegion: false,
      density: 'standard',
      responsive: {
        allowReflow: true,
        breakpoints: [
          { minWidth: 0, columns: 1 },
          { minWidth: 1200, columns: 2 },
          { minWidth: 1400, columns: 3 },
        ],
      },
      editable: [],
      slots: [{ id: 'chart', component: 'chart', region: 'main', order: 1 }],
    }
    const wrapper = mountPreview(layout, 'safe-reflow')

    const selector = wrapper.findComponent(PageSegmented)
    expect(selector.exists()).toBe(true)
    expect(selector.props('options')).toEqual([
      { label: '小屏 1100px · 1列', value: 'small' },
      { label: '笔记本 1366px · 2列', value: 'laptop' },
      { label: '桌面 1440px · 3列', value: 'desktop' },
    ])
    expect(wrapper.text()).toContain('仅查看响应式变化，不会修改页面配置')
  })

  it('点击结构块持续聚焦并把选择交给配置检查器', async () => {
    const wrapper = mountPreview(getPageLayout('board'), 'mixed-panel')
    const slot = wrapper.find('button.slot-box')

    await slot.trigger('click')
    await slot.trigger('click')

    expect(slot.classes()).toContain('active')
    expect(wrapper.emitted('focus-slot')).toHaveLength(2)
  })
})

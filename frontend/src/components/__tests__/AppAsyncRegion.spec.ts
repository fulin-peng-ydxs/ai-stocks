// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'

const AppStateBlockStub = {
  props: ['state', 'title', 'description', 'retry'],
  emits: ['retry'],
  template: '<div class="state" :data-state="state">{{ title }}{{ description }}</div>',
}

function mountRegion(props: Record<string, unknown>, attrs: Record<string, unknown> = {}) {
  return mount(AppAsyncRegion, {
    props: {
      loading: false,
      hasContent: false,
      ...props,
    },
    attrs,
    slots: {
      default: '<div class="content">图表内容</div>',
    },
    global: {
      stubs: { AppStateBlock: AppStateBlockStub },
      directives: { loading: {} },
    },
  })
}

describe('AppAsyncRegion', () => {
  it('把调用方已有的区域布局 class 透传到唯一根容器', () => {
    const wrapper = mountRegion({ hasContent: true }, { class: 'sector-detail' })

    expect(wrapper.classes()).toEqual(expect.arrayContaining(['app-async-region', 'sector-detail']))
  })

  it('无旧内容首次加载使用骨架状态', () => {
    const wrapper = mountRegion({ loading: true, loadingTitle: '正在加载走势…' })

    expect(wrapper.attributes('data-loading-mode')).toBe('initial')
    expect(wrapper.find('[data-state="loading"]').text()).toContain('正在加载走势')
    expect(wrapper.find('.content').exists()).toBe(false)
  })

  it('已有内容刷新时保留内容并启用刷新遮罩模式', () => {
    const wrapper = mountRegion({ loading: true, hasContent: true })

    expect(wrapper.attributes('data-loading-mode')).toBe('refresh')
    expect(wrapper.find('.content').text()).toBe('图表内容')
    expect(wrapper.find('.state').exists()).toBe(false)
  })

  it('首次就绪后刷新保留同一个内容节点，失败立即撤下旧内容', async () => {
    const wrapper = mountRegion({ loading: true })
    await wrapper.setProps({ loading: false, hasContent: true })
    const content = wrapper.get('.content').element
    await wrapper.setProps({ loading: true })
    expect(wrapper.get('.content').element).toBe(content)
    await wrapper.setProps({ loading: false })
    expect(wrapper.get('.content').element).toBe(content)
    await wrapper.setProps({ error: '刷新失败' })
    expect(wrapper.find('.content').exists()).toBe(false)
    expect(wrapper.get('[data-state="error"]').text()).toContain('刷新失败')
  })

  it('错误接管旧内容，空结果进入统一空态', async () => {
    const wrapper = mountRegion({ hasContent: true, error: '请求失败', errorTitle: '走势加载失败' })

    expect(wrapper.find('[data-state="error"]').text()).toContain('走势加载失败请求失败')
    expect(wrapper.find('.content').exists()).toBe(false)

    await wrapper.setProps({ hasContent: false, error: '', emptyTitle: '暂无走势' })
    expect(wrapper.find('[data-state="empty"]').text()).toContain('暂无走势')
  })
})

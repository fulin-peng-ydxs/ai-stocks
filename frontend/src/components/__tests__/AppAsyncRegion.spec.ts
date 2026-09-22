// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'

const AppStateBlockStub = {
  props: ['state', 'title', 'description', 'retry'],
  emits: ['retry'],
  template: '<div class="state" :data-state="state">{{ title }}{{ description }}</div>',
}

function mountRegion(props: Record<string, unknown>) {
  return mount(AppAsyncRegion, {
    props: {
      loading: false,
      hasContent: false,
      ...props,
    },
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
  it('仅在显式声明 fill 时占满父级可用高度', () => {
    const natural = mountRegion({ loading: false, hasContent: true })
    const filled = mountRegion({ loading: false, hasContent: true, fill: true })

    expect(natural.classes()).not.toContain('app-async-region--fill')
    expect(filled.classes()).toContain('app-async-region--fill')
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

  it('错误接管旧内容，空结果进入统一空态', async () => {
    const wrapper = mountRegion({ hasContent: true, error: '请求失败', errorTitle: '走势加载失败' })

    expect(wrapper.find('[data-state="error"]').text()).toContain('走势加载失败请求失败')
    expect(wrapper.find('.content').exists()).toBe(false)

    await wrapper.setProps({ hasContent: false, error: '', emptyTitle: '暂无走势' })
    expect(wrapper.find('[data-state="empty"]').text()).toContain('暂无走势')
  })
})

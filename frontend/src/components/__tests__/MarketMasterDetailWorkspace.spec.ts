// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'

function pointerEvent(type: string, pointerId: number, clientX: number): Event {
  const event = new Event(type)
  Object.defineProperties(event, {
    pointerId: { value: pointerId },
    clientX: { value: clientX },
  })
  return event
}

describe('MarketMasterDetailWorkspace', () => {
  it('compact 模式只渲染列表并隐藏无效的分析收展入口', () => {
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        compact: true,
        eyebrow: 'TEST',
        title: '测试列表',
      },
      slots: {
        list: '<div data-testid="list-slot">列表</div>',
        analysis: '<div data-testid="analysis-slot">分析</div>',
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.get('[data-testid="list-slot"]').text()).toBe('列表')
    expect(wrapper.find('[data-testid="analysis-slot"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-hide-analysis"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-show-analysis"]').exists()).toBe(false)
    expect(wrapper.classes()).toContain('market-master-detail--list-only')
  })

  it('抽屉默认宽度单向投影到会话，键盘拖动不反写 props', async () => {
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterWidth: 480,
      },
      slots: {
        list: '<div>列表</div>',
        analysis: '<div data-testid="analysis-slot">分析</div>',
      },
      global: { plugins: [ElementPlus] },
    })

    const separator = wrapper.get('[role="separator"]')
    expect(separator.attributes('aria-orientation')).toBe('vertical')
    expect(separator.attributes('aria-valuenow')).toBe('480')

    await separator.trigger('keydown', { key: 'ArrowRight' })
    expect(separator.attributes('aria-valuenow')).toBe('496')
    expect(wrapper.props('defaultMasterWidth')).toBe(480)

    await wrapper.setProps({ defaultMasterWidth: 520 })
    await nextTick()
    expect(separator.attributes('aria-valuenow')).toBe('520')
  })

  it('指针拖动按详情最小宽度钳制，卸载时清理全局拖动态', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = () => ({ width: 1100 } as DOMRect)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterWidth: 480,
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })

    const separator = wrapper.get('[role="separator"]')
    await separator.trigger('pointerdown', { pointerId: 7, clientX: 480 })
    window.dispatchEvent(pointerEvent('pointermove', 7, 900))
    await nextTick()

    expect(separator.attributes('aria-valuemax')).toBe('848')
    expect(separator.attributes('aria-valuenow')).toBe('848')
    expect(document.body.classList.contains('market-master-detail-is-resizing')).toBe(true)
    wrapper.unmount()
    HTMLElement.prototype.getBoundingClientRect = originalRect
    expect(document.body.classList.contains('market-master-detail-is-resizing')).toBe(false)
  })

  it('未配置个人默认值时使用可用空间内的最大列表宽度并上报会话值', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = () => ({ width: 1100 } as DOMRect)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: { analysisVisible: true, eyebrow: 'TEST', title: '测试列表' },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()

    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('848')
    expect(wrapper.emitted('masterWidthChange')?.at(-1)).toEqual([848])

    wrapper.unmount()
    HTMLElement.prototype.getBoundingClientRect = originalRect
  })
})

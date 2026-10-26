// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, Teleport } from 'vue'
import PageDrawerSurface from '@/components/PageDrawerSurface.vue'
import PageSegmented from '@/components/PageSegmented.vue'

describe('PageDrawerSurface', () => {
  it.each(['standard', 'compact'] as const)('%s 抽屉中的嵌套和传送分段统一 fill，外部兄弟不受影响', (titleSize) => {
    const target = document.createElement('div')
    document.body.appendChild(target)
    const NestedField = defineComponent({
      setup: () => () => h(PageSegmented, {
        modelValue: 'a',
        options: [{ label: '选项一', value: 'a' }, { label: '选项二', value: 'b' }],
        fill: false,
      }),
    })
    const wrapper = mount(defineComponent({
      setup: () => () => h('div', [
        h(NestedField),
        h(PageDrawerSurface, { title: '设置', titleSize }, {
          default: () => [h(NestedField), h(Teleport, { to: target }, h(NestedField))],
        }),
      ]),
    }))
    try {
      const segments = wrapper.findAllComponents(PageSegmented)
      expect(segments).toHaveLength(3)
      expect(segments[0].classes()).not.toContain('page-segmented--fill')
      for (const segment of segments.slice(1)) {
        expect(segment.classes()).toContain('page-segmented--fill')
        expect(segment.get('button').attributes('aria-pressed')).toBe('true')
      }
      expect(target.querySelector('.page-segmented--fill')).not.toBeNull()
    } finally {
      wrapper.unmount()
      target.remove()
    }
  })

  it('统一标题、副标题、正文、footer 和关闭入口', async () => {
    const wrapper = mount(PageDrawerSurface, {
      props: {
        title: '视觉环境',
        subtitle: '调整界面比例、阅读光线与导航方式',
        closeLabel: '关闭视觉环境',
      },
      slots: {
        'title-suffix': '<span class="suffix">已修改</span>',
        actions: '<button class="extra-action">附加动作</button>',
        default: '<div class="content">正文</div>',
        footer: '<button class="footer-action">恢复默认</button>',
      },
      global: { stubs: { ElIcon: true } },
    })

    expect(wrapper.get('.page-drawer-surface__title').classes()).toContain('app-drawer-title')
    expect(wrapper.get('.page-drawer-surface').classes()).not.toContain('is-title-compact')
    expect(wrapper.get('.app-drawer-subtitle').text()).toContain('调整界面比例')
    expect(wrapper.get('.suffix').text()).toBe('已修改')
    expect(wrapper.get('.content').text()).toBe('正文')
    expect(wrapper.get('.footer-action').text()).toBe('恢复默认')

    await wrapper.get('button[aria-label="关闭视觉环境"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('局部工具只切换共享标题档，不创建第二套外壳', () => {
    const wrapper = mount(PageDrawerSurface, {
      props: {
        title: '图表操作',
        titleSize: 'compact',
        bodyScroll: false,
        bodyLayout: 'fill',
      },
      global: { stubs: { ElIcon: true } },
    })

    expect(wrapper.get('.page-drawer-surface__title').classes())
      .toContain('app-drawer-title--compact')
    expect(wrapper.get('.page-drawer-surface').classes()).toContain('is-title-compact')
    expect(wrapper.get('.page-drawer-surface__body').classes()).toContain('is-scroll-disabled')
    expect(wrapper.get('.page-drawer-surface__body').classes()).toContain('is-fill')
  })
})

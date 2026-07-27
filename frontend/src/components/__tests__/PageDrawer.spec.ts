// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import PageDrawer from '@/components/PageDrawer.vue'
import { PAGE_DRAWER_WIDTHS } from '@/components/pageDrawerSize'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'

describe('PageDrawer 页面边界', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('把遮罩挂到当前 LayoutHost，而不是 body', async () => {
    const Host = defineComponent({
      components: { LayoutHost, PageDrawer },
      setup() {
        return { layout: getPageLayout('board'), visible: ref(true) }
      },
      template: `
        <LayoutHost :layout="layout">
          <template #main><div>页面内容</div></template>
          <template #overlays>
            <PageDrawer v-model="visible" title="页面详情" size="xl">
              <div>抽屉内容</div>
            </PageDrawer>
          </template>
        </LayoutHost>
      `,
    })

    const wrapper = mount(Host, {
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    const page = wrapper.get('.v-page').element
    const overlay = document.querySelector('.el-overlay.page-drawer-modal')
    expect(overlay).not.toBeNull()
    expect(page.contains(overlay)).toBe(true)
    expect(overlay?.parentElement).not.toBe(document.body)
    expect((document.querySelector('.el-drawer') as HTMLElement)?.style.width)
      .toBe(PAGE_DRAWER_WIDTHS.xl)

    wrapper.unmount()
  })

  it('挂载后更新 modelValue 会同步打开和关闭真实抽屉', async () => {
    const Host = defineComponent({
      components: { LayoutHost, PageDrawer },
      setup() {
        return { layout: getPageLayout('board'), visible: ref(false) }
      },
      template: `
        <LayoutHost :layout="layout">
          <template #main><div>页面内容</div></template>
          <template #overlays>
            <PageDrawer v-model="visible" title="动态抽屉">
              <div>抽屉内容</div>
            </PageDrawer>
          </template>
        </LayoutHost>
      `,
    })

    const wrapper = mount(Host, {
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    const vm = wrapper.vm as unknown as { visible: boolean }

    vm.visible = true
    await nextTick()
    await nextTick()
    expect(document.querySelector<HTMLElement>('.el-overlay.page-drawer-modal')?.style.display)
      .not.toBe('none')

    vm.visible = false
    await nextTick()
    await nextTick()
    expect(document.querySelector<HTMLElement>('.el-overlay.page-drawer-modal')?.style.display)
      .toBe('none')

    wrapper.unmount()
  })

  it('在 LayoutHost 外使用时开发环境给出回退提示', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const wrapper = mount(PageDrawer, {
      props: { modelValue: false },
      global: { plugins: [ElementPlus] },
    })

    expect(warn).toHaveBeenCalledWith(
      '[PageDrawer] 未找到 LayoutHost 页面容器，抽屉将回退到 body。',
    )

    wrapper.unmount()
  })

  it('抽屉宽度只由稳定语义档位定义，宽内容档位保留受控响应式', () => {
    expect(PAGE_DRAWER_WIDTHS).toEqual({
      sm: '320px',
      md: '360px',
      lg: '440px',
      xl: '560px',
      wide: 'clamp(560px, 46%, 760px)',
    })
  })
})

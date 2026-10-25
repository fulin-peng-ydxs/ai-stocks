// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
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
    expect(overlay?.classList.contains('page-drawer-modal--title-standard')).toBe(true)
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
      props: { modelValue: false, title: '预览抽屉' },
      global: { plugins: [ElementPlus] },
    })

    expect(warn).toHaveBeenCalledWith(
      '[PageDrawer] 未找到 LayoutHost 页面容器，抽屉将回退到 body。',
    )

    wrapper.unmount()
  })

  it('抽屉宽度只由稳定语义档位定义，宽内容档位保留受控响应式', () => {
    expect(PAGE_DRAWER_WIDTHS).toEqual({
      xs: '280px',
      sm: '320px',
      md: '360px',
      lg: '440px',
      xl: '560px',
      xxl: 'clamp(640px, 60%, 820px)',
      wide: 'clamp(560px, 46%, 760px)',
      full: '100%',
    })
  })

  it('标题默认消费标准档，并允许局部工具抽屉声明紧凑档', async () => {
    const wrapper = mount(PageDrawer, {
      attachTo: document.body,
      props: { modelValue: true, title: '局部工具', titleSize: 'compact' },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    expect(document.querySelector('.el-overlay.page-drawer-modal--title-compact')).not.toBeNull()

    wrapper.unmount()
  })

  it('所有抽屉默认通过共享 surface 统一遮罩和内容宿主', async () => {
    const wrapper = mount(PageDrawer, {
      attachTo: document.body,
      props: { modelValue: true, title: '统一抽屉' },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    expect(document.querySelector('.el-overlay.page-drawer-modal--surface')).not.toBeNull()
    expect(document.querySelector('.el-drawer.page-drawer--surface')).not.toBeNull()

    wrapper.unmount()
  })

  it('应用级抽屉仍复用统一外壳，但覆盖整个应用视口', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const wrapper = mount(PageDrawer, {
      attachTo: document.body,
      props: { modelValue: true, title: '用户中心', boundary: 'app', size: 'lg' },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    await nextTick()

    expect(warn).not.toHaveBeenCalled()
    expect(document.querySelector('.el-overlay.page-drawer-modal--app')).not.toBeNull()
    expect(document.querySelector('.page-drawer-surface')).not.toBeNull()
    expect((document.querySelector('.el-drawer') as HTMLElement)?.style.width)
      .toBe(PAGE_DRAWER_WIDTHS.lg)

    wrapper.unmount()
  })

  it('应用抽屉可通过共享密度类统一放大正文、控件和内距', async () => {
    const wrapper = mount(PageDrawer, {
      attachTo: document.body,
      props: { modelValue: true, title: '视觉环境', boundary: 'app' },
      attrs: { class: 'lh-density-comfortable' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    expect(document.querySelector('.el-drawer.lh-density-comfortable .page-drawer-surface'))
      .not.toBeNull()
    wrapper.unmount()
  })
  it('头部关闭经过 before-close，拒绝时保留抽屉，允许时再关闭', async () => {
    let done: (() => void) | undefined
    const beforeClose = vi.fn((allow: () => void) => { done = allow })
    const wrapper = mount(PageDrawer, {
      attachTo: document.body,
      props: { modelValue: true, title: '待保存内容', boundary: 'app' },
      attrs: { beforeClose },
      global: { plugins: [ElementPlus], stubs: { transition: false } },
    })
    await flushPromises()
    const close = document.querySelector<HTMLButtonElement>('button[aria-label="关闭待保存内容"]')!
    expect(close).not.toBeNull()
    close.click()
    await flushPromises()
    expect(beforeClose).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    done!()
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.emitted('update:modelValue')).toEqual([[false]]))
    wrapper.unmount()
  })

  it('show-close=false 同时隐藏自定义头部关闭入口', async () => {
    const wrapper = mount(PageDrawer, {
      attachTo: document.body,
      props: { modelValue: true, title: '处理中', boundary: 'app', showClose: false },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    expect(document.querySelector('.app-close-control')).toBeNull()
    expect(document.querySelector('.el-drawer__close-btn')).toBeNull()
    wrapper.unmount()
  })

})

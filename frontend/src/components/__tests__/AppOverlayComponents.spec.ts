// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AppDialog from '@/components/AppDialog.vue'
import AppDetailDrawer from '@/components/AppDetailDrawer.vue'
import AppDetailField from '@/components/AppDetailField.vue'
import AppDetailFields from '@/components/AppDetailFields.vue'
import { APP_DIALOG_WIDTHS } from '@/components/appDialogSize'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { getPageLayout } from '@/layout'

describe('统一弹窗与详情组件', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })
  it('AppDialog 使用语义宽度并挂载到当前 LayoutHost', async () => {
    const Host = defineComponent({
      components: { AppDialog, LayoutHost },
      setup: () => ({ layout: getPageLayout('board'), open: ref(true) }),
      template: `
        <LayoutHost :layout="layout">
          <template #main><div>页面内容</div></template>
          <template #overlays>
            <AppDialog v-model="open" title="短编辑" size="large">内容</AppDialog>
          </template>
        </LayoutHost>
      `,
    })
    const wrapper = mount(Host, { attachTo: document.body, global: { plugins: [ElementPlus] } })
    await nextTick()
    await nextTick()

    const overlay = document.querySelector('.el-overlay.app-dialog-modal')
    expect(overlay).not.toBeNull()
    expect(wrapper.get('.v-page').element.contains(overlay)).toBe(true)
    expect((document.querySelector('.el-dialog') as HTMLElement)?.style.getPropertyValue('--el-dialog-width'))
      .toBe(APP_DIALOG_WIDTHS.large)
    wrapper.unmount()
  })

  it('AppDetailDrawer 统一标题、状态和 footer', () => {
    const wrapper = mount(AppDetailDrawer, {
      props: {
        modelValue: true,
        title: '审计详情',
        subtitle: '查看本次操作上下文',
        state: 'empty',
        stateTitle: '暂无详情',
      },
      slots: { footer: '<button>关闭</button>' },
      global: {
        stubs: {
          PageDrawer: {
            props: ['modelValue', 'size', 'title', 'subtitle'],
            template: '<aside><header>{{ title }}{{ subtitle }}<slot name="title-suffix"/><slot name="header-actions"/></header><slot/><footer><slot name="footer"/></footer></aside>',
          },
          AppStateBlock: { props: ['title'], template: '<div class="state">{{ title }}</div>' },
        },
      },
    })

    expect(wrapper.text()).toContain('审计详情')
    expect(wrapper.text()).toContain('查看本次操作上下文')
    expect(wrapper.get('.state').text()).toBe('暂无详情')
    expect(wrapper.get('footer').text()).toBe('关闭')
  })

  it('详情字段统一空值、长字段和等宽值语义', () => {
    const wrapper = mount({
      components: { AppDetailFields, AppDetailField },
      template: `
        <AppDetailFields :columns="2">
          <AppDetailField label="名称" value="策略 A" />
          <AppDetailField label="路径" :value="null" span="full" mono />
        </AppDetailFields>
      `,
    })

    expect(wrapper.text()).toContain('名称')
    expect(wrapper.text()).toContain('策略 A')
    expect(wrapper.text()).toContain('—')
    expect(wrapper.find('.app-detail-field--full').exists()).toBe(true)
    expect(wrapper.find('.app-detail-field__value--mono').exists()).toBe(true)
  })
})

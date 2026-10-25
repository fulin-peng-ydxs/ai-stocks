// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SettingsGroup from '@/components/SettingsGroup.vue'

const TreeFixture = defineComponent({
  components: { SettingsGroup },
  template: `
    <SettingsGroup title="父级" :level="1">
      <SettingsGroup title="子级一" :level="2">
        <SettingsGroup title="孙级" :level="3">孙级内容</SettingsGroup>
      </SettingsGroup>
      <SettingsGroup title="子级二" :level="2">子级内容</SettingsGroup>
    </SettingsGroup>
  `,
})

function group(wrapper: ReturnType<typeof mount>, title: string) {
  return wrapper.find(`[data-settings-group-title="${title}"]`)
}

describe('SettingsGroup 递归分组控制', () => {
  it('按真实插槽父级计算层级，忽略子节点手工层级，固定组仍保持缩进', async () => {
    const wrapper = mount(defineComponent({
      components: { SettingsGroup },
      template: `<SettingsGroup title="根">
        <div><SettingsGroup title="固定子组" :level="9" :collapsible="false">
          <SettingsGroup title="孙组" :level="1">内容</SettingsGroup>
        </SettingsGroup></div>
      </SettingsGroup>`,
    }), { global: { stubs: { ElIcon: true } } })
    await nextTick()
    expect(group(wrapper, '根').attributes('data-settings-group-level')).toBe('1')
    expect(group(wrapper, '固定子组').attributes('data-settings-group-level')).toBe('2')
    expect(group(wrapper, '固定子组').classes()).toContain('sg-nested')
    expect(group(wrapper, '固定子组').get('.sg-head').attributes('role')).toBeUndefined()
    expect(group(wrapper, '孙组').attributes('data-settings-group-level')).toBe('3')
    // 批量操作越过不可折叠包装器，仅改变最近可折叠子组。
    await wrapper.get('button[aria-label="根：收起下级分组"]').trigger('click')
    expect(group(wrapper, '孙组').attributes('data-settings-group-open')).toBe('false')
    wrapper.unmount()
  })

  it('无标题包装器不占可见层级或缩进，动态子组移除后取消批量入口', async () => {
    const wrapper = mount(defineComponent({
      components: { SettingsGroup },
      setup: () => ({ visible: ref(true) }),
      template: `<SettingsGroup title="根">
        <SettingsGroup :level="9"><SettingsGroup v-if="visible" title="子组">内容</SettingsGroup></SettingsGroup>
      </SettingsGroup>`,
    }), { global: { stubs: { ElIcon: true } } })
    await nextTick()
    expect(wrapper.get('.sg-transparent').classes()).not.toContain('sg-nested')
    expect(group(wrapper, '子组').attributes('data-settings-group-level')).toBe('2')
    await wrapper.get('button[aria-label="根：收起下级分组"]').trigger('click')
    expect(group(wrapper, '子组').attributes('data-settings-group-open')).toBe('false')
    wrapper.vm.visible = false
    await nextTick()
    expect(wrapper.find('button[aria-label^="根："]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('每个存在下级的父节点都有自己的批量收起与展开入口', async () => {
    const wrapper = mount(TreeFixture, { global: { stubs: { ElIcon: true } } })
    await nextTick()
    await nextTick()

    expect(wrapper.find('button[aria-label="父级：收起下级分组"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="子级一：收起下级分组"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="子级二：收起下级分组"]').exists()).toBe(false)

    await wrapper.find('button[aria-label="子级一：收起下级分组"]').trigger('click')
    expect(group(wrapper, '子级一').find('.sg-body').isVisible()).toBe(true)
    expect(group(wrapper, '孙级').find('.sg-body').isVisible()).toBe(false)
    expect(wrapper.find('button[aria-label="子级一：展开下级分组"]').exists()).toBe(true)
  })

  it('父节点只控制直接子节点，重新展开时保留更深层原状态', async () => {
    const wrapper = mount(TreeFixture, { global: { stubs: { ElIcon: true } } })
    await nextTick()
    await nextTick()

    await wrapper.find('button[aria-label="子级一：收起下级分组"]').trigger('click')
    await wrapper.find('button[aria-label="父级：收起下级分组"]').trigger('click')

    expect(group(wrapper, '父级').find('.sg-body').isVisible()).toBe(true)
    expect(group(wrapper, '子级一').find('.sg-body').isVisible()).toBe(false)
    expect(group(wrapper, '子级二').find('.sg-body').isVisible()).toBe(false)

    await wrapper.find('button[aria-label="父级：展开下级分组"]').trigger('click')
    expect(group(wrapper, '子级一').attributes('data-settings-group-open')).toBe('true')
    expect(group(wrapper, '子级二').attributes('data-settings-group-open')).toBe('true')
    expect(group(wrapper, '孙级').attributes('data-settings-group-open')).toBe('false')
  })

  it('整体收起后操作下级时展开受控父组，并只切换直接子组', async () => {
    const wrapper = mount(defineComponent({
      components: { SettingsGroup, TreeFixture },
      setup: () => ({ open: ref(true) }),
      template: `
        <button class="bulk-close" @click="open = false">全部收起</button>
        <SettingsGroup title="受控父级" v-model="open"><TreeFixture /></SettingsGroup>
      `,
    }), {
      attachTo: document.body,
      global: { stubs: { ElIcon: true, ElCollapseTransition: { template: '<slot />' } } },
    })
    await nextTick()
    await nextTick()

    await wrapper.get('.bulk-close').trigger('click')
    expect(wrapper.get('[data-settings-group-title="受控父级"] > .sg-body').isVisible()).toBe(false)
    await wrapper.get('button[aria-label="受控父级：收起下级分组"]').trigger('click')
    expect(group(wrapper, '受控父级').attributes('data-settings-group-open')).toBe('true')
    expect(wrapper.get('[data-settings-group-title="受控父级"] > .sg-body').isVisible()).toBe(true)
    expect(group(wrapper, '父级').attributes('data-settings-group-open')).toBe('false')
    expect(group(wrapper, '子级一').attributes('data-settings-group-open')).toBe('true')

    await wrapper.get('.bulk-close').trigger('click')
    await wrapper.get('button[aria-label="受控父级：展开下级分组"]').trigger('click')
    expect(wrapper.get('[data-settings-group-title="受控父级"] > .sg-body').isVisible()).toBe(true)
    expect(group(wrapper, '父级').find('.sg-body').isVisible()).toBe(true)
    expect(group(wrapper, '孙级').attributes('data-settings-group-open')).toBe('true')
    wrapper.unmount()
  })

  it('嵌套分组自身收起后操作右侧按钮，也会露出该组内容', async () => {
    const wrapper = mount(TreeFixture, { global: { stubs: { ElIcon: true } } })
    await nextTick()
    await nextTick()
    await group(wrapper, '子级一').get('.sg-head').trigger('click')
    expect(group(wrapper, '子级一').attributes('data-settings-group-open')).toBe('false')
    await wrapper.get('button[aria-label="子级一：收起下级分组"]').trigger('click')
    expect(group(wrapper, '子级一').find('.sg-body').isVisible()).toBe(true)
    expect(group(wrapper, '孙级').attributes('data-settings-group-open')).toBe('false')
    wrapper.unmount()
  })
})

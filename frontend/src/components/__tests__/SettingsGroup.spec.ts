// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
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
})

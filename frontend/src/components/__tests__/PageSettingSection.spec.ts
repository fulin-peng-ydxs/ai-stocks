// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PageSettingSection from '@/components/PageSettingSection.vue'
import SettingsGroup from '@/components/SettingsGroup.vue'

const BusinessFixture = defineComponent({
  components: { PageSettingSection, SettingsGroup },
  template: `
    <SettingsGroup title="业务选项" :level="1">
      <PageSettingSection title="业务分区一">内容一</PageSettingSection>
      <PageSettingSection title="业务分区二">内容二</PageSettingSection>
    </SettingsGroup>
  `,
})

function group(wrapper: ReturnType<typeof mount>, title: string) {
  return wrapper.find(`[data-settings-group-title="${title}"]`)
}

describe('PageSettingSection 折叠树', () => {
  it('作为业务选项的直接子节点接受父级批量收起与展开', async () => {
    const wrapper = mount(BusinessFixture, { global: { stubs: { ElIcon: true } } })
    await nextTick()
    await nextTick()

    const collapse = wrapper.find('button[aria-label="业务选项：收起下级分组"]')
    expect(collapse.exists()).toBe(true)
    expect(group(wrapper, '业务分区一').find('.pss-body').isVisible()).toBe(true)

    await collapse.trigger('click')
    await nextTick()
    expect(group(wrapper, '业务选项').attributes('data-settings-group-open')).toBe('true')
    expect(group(wrapper, '业务分区一').attributes('data-settings-group-open')).toBe('false')
    expect(group(wrapper, '业务分区二').attributes('data-settings-group-open')).toBe('false')
    expect(group(wrapper, '业务分区一').find('.pss-body').attributes('style')).toContain('display: none')
    expect(group(wrapper, '业务分区二').find('.pss-body').attributes('style')).toContain('display: none')

    await wrapper.find('button[aria-label="业务选项：展开下级分组"]').trigger('click')
    await nextTick()
    expect(group(wrapper, '业务分区一').find('.pss-body').isVisible()).toBe(true)
    expect(group(wrapper, '业务分区二').find('.pss-body').isVisible()).toBe(true)
  })

  it('叶子业务分区不显示下级批量入口', async () => {
    const wrapper = mount(PageSettingSection, {
      props: { title: '叶子分区' },
      slots: { default: '内容' },
      global: { stubs: { ElIcon: true } },
    })
    await nextTick()

    expect(wrapper.find('button[aria-label="叶子分区：收起下级分组"]').exists()).toBe(false)
  })
})

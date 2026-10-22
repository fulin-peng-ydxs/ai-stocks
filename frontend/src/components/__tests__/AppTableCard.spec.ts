// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'
import ElementPlus from 'element-plus'
import AppTableCard from '@/components/AppTableCard.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'

const ResultRegion = defineComponent({
  components: { AppTableCard, AppDataTable, AppStateBlock },
  props: ['state', 'border'],
  emits: ['retry', 'page-change'],
  template: `
    <AppTableCard>
      <template #header>结果列表</template>
      <AppStateBlock v-if="state === 'error'" state="error" title="加载失败" retry @retry="$emit('retry')" />
      <AppDataTable v-else :data="state === 'ready' ? [{ code: '000001' }] : []"
        :loading="state === 'loading'" :border="border" empty-text="暂无结果"
        :pagination="{ currentPage: 1, pageSize: 20, total: state === 'ready' ? 40 : 0 }"
        @page-change="$emit('page-change', $event)" />
    </AppTableCard>`,
})

describe('AppTableCard', () => {
  it('同一外框承接加载、空态、数据、分页和错误重试，列线配置不改变外框', async () => {
    const wrapper = mount(ResultRegion, {
      props: { state: 'loading', border: false },
      global: { plugins: [ElementPlus] },
    })
    const frame = wrapper.find('.app-table-card').element
    expect(wrapper.find('.el-card__header').text()).toBe('结果列表')
    expect(wrapper.find('[data-testid="app-data-table-initial-loading"]').exists()).toBe(true)
    expect(wrapper.find('.app-data-table__pager').exists()).toBe(false)

    await wrapper.setProps({ state: 'empty' })
    expect(wrapper.text()).toContain('暂无结果')
    await wrapper.setProps({ state: 'ready', border: true })
    expect(wrapper.find('.el-table--border').exists()).toBe(true)
    expect(wrapper.find('.app-data-table__pager').exists()).toBe(true)
    await wrapper.find('.btn-next').trigger('click')
    expect(wrapper.emitted('page-change')?.[0]).toEqual([2])

    await wrapper.setProps({ state: 'error' })
    expect(wrapper.find('.el-table').exists()).toBe(false)
    await wrapper.findAll('button').find((button) => button.text() === '重试')!.trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
    expect(wrapper.find('.app-table-card').element).toBe(frame)
    expect(wrapper.findAll('.app-table-card')).toHaveLength(1)
    wrapper.unmount()
  })
})

// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StockGroupFavoriteButton from '@/components/StockGroupFavoriteButton.vue'
import * as stockGroupApi from '@/api/stockGroup'

vi.mock('@/api/stockGroup', () => ({
  addMembers: vi.fn(),
  removeMembers: vi.fn(),
}))

function mountButton(active = false) {
  return mount(StockGroupFavoriteButton, {
    props: {
      groupId: 'grp-default',
      code: '000001.SZ',
      name: '平安银行',
      active,
      defaultDate: '2026-09-11',
    },
    global: {
      plugins: [ElementPlus],
      directives: { permission: {} },
    },
  })
}

describe('StockGroupFavoriteButton', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(stockGroupApi.addMembers).mockResolvedValue({ added: 1 })
    vi.mocked(stockGroupApi.removeMembers).mockResolvedValue({ msg: '已移除' })
  })

  it('空心星标把股票加入默认自选分组并回传激活态', async () => {
    const wrapper = mountButton()
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(stockGroupApi.addMembers).toHaveBeenCalledWith(
      'grp-default',
      ['000001.SZ'],
      '2026-09-11',
    )
    expect(wrapper.emitted('changed')).toEqual([[true]])
    expect(wrapper.get('button').attributes('aria-label')).toContain('加入自选分组')
  })

  it('实心星标把股票移出默认自选分组', async () => {
    const wrapper = mountButton(true)
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(stockGroupApi.removeMembers).toHaveBeenCalledWith('grp-default', ['000001.SZ'])
    expect(wrapper.emitted('changed')).toEqual([[false]])
    expect(wrapper.classes()).toContain('stock-group-favorite-button--active')
  })
})

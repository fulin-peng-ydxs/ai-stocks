// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AssetSearchDrawer from '@/components/asset-search/AssetSearchDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import type { ProfileSummary } from '@/components/asset-search/types'

const mineItem: ProfileSummary = {
  id: 'my_a',
  profile_ref: 'ref_my_a',
  name: '我的筛选方案A',
  version: 1,
  is_preset: false,
  visibility: 'private',
  source: 'mine',
  readonly: false,
  owner_label: null,
  updated_at: '2026-07-21 08:00:00',
}
const publicItem: ProfileSummary = {
  id: 'pub_b',
  profile_ref: 'ref_pub_b',
  name: '量价齐升·进攻型',
  version: 4,
  is_preset: false,
  visibility: 'public',
  source: 'public',
  readonly: true,
  owner_label: '其他租户用户',
  updated_at: '2026-07-25 11:00:00',
}

function mountSelect(extra: Record<string, unknown> = {}, permissions: string[] = ['screen-profile:save']) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'normal'
  auth.permissions = permissions
  const fetchMine = (extra.fetchMine as () => Promise<ProfileSummary[]>) ?? (async () => [mineItem])
  const wrapper = mount(AssetProfileSelect, {
    props: {
      modelValue: '',
      assetLabel: '筛选方案',
      fetchMine,
      browse: async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' }),
      copyItem: async () => ({ id: 'x', version: 1 }),
      copyPermission: 'screen-profile:save',
      ...extra,
    },
    attachTo: document.body,
    global: { plugins: [pinia, ElementPlus] },
  })
  return { wrapper, fetchMine }
}

async function flush(times = 4) {
  for (let i = 0; i < times; i += 1) await nextTick()
}

describe('AssetProfileSelect', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('挂载即加载「我的」列表并渲染下拉与搜索入口', async () => {
    const fetchMine = vi.fn(async () => [mineItem])
    const { wrapper } = mountSelect({ fetchMine })
    await flush()
    expect(fetchMine).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="asset-profile-select-search"]').exists()).toBe(true)
    // 下拉选项（el-select 下拉面板 teleport 到 body）
    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    expect(document.body.textContent).toContain('我的筛选方案A')
    wrapper.unmount()
  })

  it('「我的」为空时空态引导去系统内置搜索', async () => {
    const { wrapper } = mountSelect({ fetchMine: async () => [] })
    await flush()
    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    expect(document.body.textContent).toContain('暂无我的筛选方案')
    expect(document.body.textContent).toContain('去“系统内置”搜索复制')
    wrapper.unmount()
  })

  it('加载查看：临时只读项注入顶部、选中并发出 loaded，不进入「我的」', async () => {
    const fetchMine = vi.fn(async () => [mineItem])
    const { wrapper } = mountSelect({ fetchMine })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['ref_pub_b'])
    expect(wrapper.emitted('loaded')).toBeTruthy()
    // 临时项不进「我的」：fetchMine 不被重拉，「我的」仍只有 1 条
    expect(fetchMine).toHaveBeenCalledTimes(1)
    // 临时只读项出现在候选顶部（含来源徽标/只读）
    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const options = Array.from(document.querySelectorAll('.el-select-dropdown__item'))
    expect(options[0]?.textContent).toContain('量价齐升·进攻型')
    expect(options[0]?.textContent).toContain('全体公开')
    wrapper.unmount()
  })

  it('切换到其他对象即丢弃临时只读项', async () => {
    const { wrapper } = mountSelect()
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    await wrapper.setProps({ modelValue: 'ref_my_a' })
    await flush()
    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const options = Array.from(document.querySelectorAll('.el-select-dropdown__item'))
    expect(options).toHaveLength(1)
    expect(options[0]?.textContent).toContain('我的筛选方案A')
    wrapper.unmount()
  })

  it('复制成功：刷新「我的」、选中新资产并发出 copied', async () => {
    const copiedItem: ProfileSummary = {
      ...mineItem,
      id: 'new_id',
      profile_ref: 'ref_new',
      name: '量价齐升·进攻型 副本',
    }
    const fetchMine = vi.fn()
      .mockResolvedValueOnce([mineItem])
      .mockResolvedValueOnce([mineItem, copiedItem])
    const copyItem = vi.fn(async () => ({ id: 'new_id', profile_ref: 'ref_new', name: '量价齐升·进攻型 副本', version: 1 }))
    const { wrapper } = mountSelect({ fetchMine, copyItem })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('copied', { id: 'new_id', profile_ref: 'ref_new', name: '量价齐升·进攻型 副本', version: 1 }, publicItem)
    await flush()
    expect(fetchMine).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['ref_new'])
    expect(wrapper.emitted('copied')).toBeTruthy()
    wrapper.unmount()
  })

  it('列表加载失败显示内联错误态并可重试', async () => {
    const fetchMine = vi.fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce([mineItem])
    const { wrapper } = mountSelect({ fetchMine })
    await flush()
    expect(wrapper.text()).toContain('筛选方案加载失败')
    const retry = wrapper.findAll('button').find((b) => b.text().includes('重试'))
    expect(retry).toBeTruthy()
    await retry!.trigger('click')
    await flush()
    expect(fetchMine).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('list 形态渲染侧栏列表', async () => {
    const { wrapper } = mountSelect({ mode: 'list' })
    await flush()
    const list = wrapper.find('.asset-profile-select__list')
    expect(list.exists()).toBe(true)
    expect(list.text()).toContain('我的筛选方案A')
    wrapper.unmount()
  })

  it('无查看权限（viewPermission 不满足）时不渲染搜索入口与复制引导', async () => {
    const { wrapper } = mountSelect({ viewPermission: 'screen-profile:view' }, ['screen-profile:save'])
    await flush()
    // 当前角色仅 screen-profile:save，无 screen-profile:view → 搜索入口与空态引导都隐藏
    expect(wrapper.find('[data-testid="asset-profile-select-search"]').exists()).toBe(false)
    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    expect(document.body.textContent).not.toContain('去“系统内置”搜索复制')
    wrapper.unmount()
  })

  it('具备查看权限时正常渲染搜索入口', async () => {
    const { wrapper } = mountSelect(
      { viewPermission: 'screen-profile:view', fetchMine: async () => [mineItem] },
      ['screen-profile:save', 'screen-profile:view'],
    )
    await flush()
    expect(wrapper.find('[data-testid="asset-profile-select-search"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

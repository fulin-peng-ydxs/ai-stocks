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
      copyItem: async () => ({ id: 'x', name: '筛选方案 副本', version: 1 }),
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
    expect(document.body.querySelector('.asset-visibility-tag')).toBeNull()
    expect(document.body.querySelector('.system-builtin-tag')).toBeNull()
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

  it('加载查看：临时只读项注入顶部并发出 loaded，不改变选中、不进入「我的」', async () => {
    const fetchMine = vi.fn(async () => [mineItem])
    const { wrapper } = mountSelect({ fetchMine })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    // 「加载查看」= 临时只读预览对象：注入候选顶部 + emit loaded，**不联动 update:modelValue**。
    // 组件刻意不把临时项设为选中（规避 el-select 把 selectedItem 锁到非持久 tempItem 的更新循环）；
    // 是否载入展示由各页 loaded 回调在页面级状态完成。
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
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

  it('external 模式只通知父级，不向候选注入临时项', async () => {
    const { wrapper } = mountSelect({ loadedMode: 'external' })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()

    expect(wrapper.emitted('loaded')?.at(-1)).toEqual([publicItem])
    expect((wrapper.vm as unknown as { tempItem: ProfileSummary | null }).tempItem).toBeNull()
    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const options = Array.from(document.querySelectorAll('.el-select-dropdown__item'))
    expect(options).toHaveLength(1)
    expect(options[0]?.textContent).toContain('我的筛选方案A')
    wrapper.unmount()
  })

  it('clearTransient 同步清理组件内临时候选', async () => {
    const { wrapper } = mountSelect()
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    ;(wrapper.vm as unknown as { clearTransient: () => void }).clearTransient()
    await flush()
    expect((wrapper.vm as unknown as { tempItem: ProfileSummary | null }).tempItem).toBeNull()
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

  it('selectLoaded 模式把加载查看项设为稳定只读选项并直接选中', async () => {
    const { wrapper } = mountSelect({ selectLoaded: true })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()

    expect(wrapper.emitted('loaded')?.at(-1)).toEqual([publicItem])
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['ref_pub_b'])

    // 模拟父组件 v-model 回写；加载项必须仍是当前 option，而不是锁入一次性 tempItem。
    await wrapper.setProps({ modelValue: 'ref_pub_b' })
    await flush()
    expect((wrapper.vm as unknown as { selectedItem: ProfileSummary | null }).selectedItem)
      .toMatchObject({ profile_ref: 'ref_pub_b', readonly: true })

    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const options = Array.from(document.querySelectorAll('.el-select-dropdown__item'))
    expect(options[0]?.textContent).toContain('量价齐升·进攻型')
    expect(options[0]?.textContent).toContain('全体公开')
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
    // P2-2：复制后回写完整 summary（含 source/readonly/is_preset），父级据此并入
    expect(wrapper.emitted('copiedItem')?.at(-1)).toEqual([copiedItem])
    wrapper.unmount()
  })

  it('列表加载失败显示内联错误态并可重试', async () => {
    const fetchMine = vi.fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce([mineItem])
    const { wrapper } = mountSelect({ fetchMine })
    await flush()
    expect(wrapper.text()).toContain('筛选方案加载失败')
    expect(wrapper.emitted('loadFailed')?.at(-1)).toEqual(['boom'])
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

  it('list 行内×只移除临时预览，不影响我的方案或触发持久操作', async () => {
    const fetchMine = vi.fn(async () => [mineItem])
    const copyItem = vi.fn(async () => ({ id: 'copy', name: '副本', version: 1 }))
    const presetOwnerItem: ProfileSummary = {
      ...publicItem,
      id: 'preset_owner',
      profile_ref: 'ref_preset_owner',
      name: '本人名下系统内置方案',
      is_preset: true,
      source: 'preset',
      readonly: false,
      owner_label: '我',
    }
    const { wrapper } = mountSelect({ mode: 'list', fetchMine, copyItem })
    await flush()
    expect(wrapper.find('[data-testid="asset-profile-select-remove"]').exists()).toBe(false)

    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', presetOwnerItem)
    await flush()
    expect(wrapper.text()).toContain('本人名下系统内置方案')
    await wrapper.find('[data-testid="asset-profile-select-remove"]').trigger('click')
    await flush()

    expect(wrapper.emitted('tempRemoved')?.at(-1)).toEqual([presetOwnerItem])
    expect(wrapper.text()).not.toContain('本人名下系统内置方案')
    expect(wrapper.text()).toContain('我的筛选方案A')
    expect(fetchMine).toHaveBeenCalledTimes(1)
    expect(copyItem).not.toHaveBeenCalled()
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

  it('未传 defaultItemKey 时抽屉不渲染「设为默认」动作（仅榜单页生效）', async () => {
    const { wrapper } = mountSelect({
      browse: async () => ({ items: [publicItem], total: 1, page: 1, page_size: 20, source: 'preset' }),
    })
    await flush()
    await wrapper.find('[data-testid="asset-profile-select-search"]').trigger('click')
    await flush()
    // 默认场景未传 defaultItemKey：抽屉操作列不应出现「设为默认加载方案」
    const btn = document.querySelector<HTMLElement>('[data-testid="asset-profile-select-default"]')
    expect(btn).toBeNull()
    wrapper.unmount()
  })
})

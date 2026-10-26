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
import assetProfileSelectSource from '@/components/asset-search/AssetProfileSelect.vue?raw'

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

  it('图标搜索保留可访问名称、搜索事件和权限边界', async () => {
    const { wrapper } = mountSelect({ searchButton: 'icon', viewPermission: 'screen-profile:view' }, ['screen-profile:view'])
    await flush()
    const search = wrapper.get('[data-testid="asset-profile-select-search"]')
    expect(search.element.tagName).toBe('BUTTON')
    expect(search.attributes('aria-label')).toBe('搜索筛选方案')
    await search.trigger('click')
    await flush()
    expect(wrapper.findComponent(AssetSearchDrawer).props('modelValue')).toBe(true)
    wrapper.unmount()

    const denied = mountSelect({ searchButton: 'icon', viewPermission: 'screen-profile:view' }, [])
    await flush()
    expect(denied.wrapper.find('[data-testid="asset-profile-select-search"]').exists()).toBe(false)
    denied.wrapper.unmount()
  })

  it('横向模式固定为可压缩选择器加搜索按钮，避免窄宽度下按钮换行', async () => {
    const { wrapper } = mountSelect()
    await flush()

    const root = wrapper.find('[data-testid="asset-profile-select"]')
    expect(assetProfileSelectSource).toContain('display: inline-grid')
    expect(assetProfileSelectSource).toContain('grid-template-columns: minmax(0, 1fr) auto')
    expect(assetProfileSelectSource).not.toContain('flex-wrap: wrap')
    expect(root.find('[data-testid="asset-profile-select-select"]').exists()).toBe(true)
    expect(root.find('[data-testid="asset-profile-select-search"]').exists()).toBe(true)
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

  it('从选择器打开搜索抽屉前先收起下拉浮层，避免两个浮层重叠', async () => {
    const { wrapper } = mountSelect({ fetchMine: async () => [] })
    await flush()
    const select = wrapper.findComponent({ name: 'ElSelect' })
    const blur = vi.spyOn(select.vm as unknown as { blur: () => void }, 'blur')

    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const emptySearch = document.querySelector<HTMLElement>('[data-testid="asset-profile-select-empty-search"]')
    expect(emptySearch).not.toBeNull()
    emptySearch!.click()
    await flush()

    expect(blur).toHaveBeenCalledTimes(1)
    expect(wrapper.findComponent(AssetSearchDrawer).props('modelValue')).toBe(true)
    wrapper.unmount()
  })

  it('首次加载失败时错误态接管选择器，不与空选择框并存', async () => {
    const fetchMine = vi.fn().mockRejectedValueOnce(new Error('网络异常'))
    const { wrapper } = mountSelect({ fetchMine })
    await flush()

    expect(wrapper.text()).toContain('筛选方案加载失败')
    expect(wrapper.find('[data-testid="asset-profile-select-select"]').exists()).toBe(false)
    expect(wrapper.find('.app-state-block__inline-error').exists()).toBe(true)
    expect(wrapper.findAll('button').filter((button) => button.text() === '重试')).toHaveLength(1)
    wrapper.unmount()
  })

  it('已有方案刷新失败时保留 ready 内容并降级为持久提示', async () => {
    const fetchMine = vi.fn()
      .mockResolvedValueOnce([mineItem])
      .mockRejectedValueOnce(new Error('网络异常'))
    const { wrapper } = mountSelect({ fetchMine })
    await flush()
    await (wrapper.vm as unknown as { reload: () => Promise<ProfileSummary[] | null> }).reload()
    await flush()

    expect(wrapper.find('[data-testid="asset-profile-select-select"]').exists()).toBe(true)
    expect(wrapper.find('.app-status-notice').exists()).toBe(true)
    expect(wrapper.text()).toContain('当前继续使用已加载的方案')
    expect(wrapper.find('.app-state-block--error').exists()).toBe(false)
    wrapper.unmount()
  })

  it('加载查看：临时只读项注入顶部并发出 loaded，不改变选中、不进入「我的」', async () => {
    const fetchMine = vi.fn(async () => [mineItem])
    const { wrapper } = mountSelect({ fetchMine })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    // 「加载查看」= 临时只读预览对象：注入候选顶部 + emit loaded，**不联动 update:modelValue**。
    // 默认只保留会话候选，不直接改变页面的选中上下文；
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

  it('external 模式保留候选供再次加载，不把公开 ref 写入 mine 选值', async () => {
    const { wrapper } = mountSelect({ loadedMode: 'external' })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()

    expect(wrapper.emitted('loaded')?.at(-1)).toEqual([publicItem])
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const options = Array.from(document.querySelectorAll('.el-select-dropdown__item'))
    expect(options).toHaveLength(2)
    expect(options[0]?.textContent).toContain(publicItem.name)
    wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', mineItem.profile_ref)
    await flush()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([mineItem.profile_ref])
    wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', publicItem.profile_ref)
    await flush()
    expect(wrapper.emitted('loaded')).toHaveLength(2)
    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    wrapper.unmount()
  })

  it('clearTransient 可按 key 移除外部快照候选，重置时清空所有候选', async () => {
    const { wrapper } = mountSelect()
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', { ...publicItem, id: 'other', profile_ref: 'ref_other' })
    await flush()
    wrapper.vm.clearTransient(publicItem.profile_ref)
    await flush()
    expect((wrapper.vm as unknown as { loadedItems: ProfileSummary[] }).loadedItems.map(item => item.profile_ref))
      .toEqual(['ref_other'])
    ;(wrapper.vm as unknown as { clearTransient: () => void }).clearTransient()
    await flush()
    expect((wrapper.vm as unknown as { loadedItems: ProfileSummary[] }).loadedItems).toEqual([])
    wrapper.unmount()
  })

  it.each(['select', 'list'] as const)('%s 模式切换和清空保留多个已加载方案，重复加载按 ref 更新去重', async (mode) => {
    const { wrapper } = mountSelect({ mode })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    const preset = { ...publicItem, id: 'preset', profile_ref: 'ref_preset', is_preset: true, source: 'preset' }
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', preset)
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', { ...publicItem, version: 5 })
    await flush()
    await wrapper.setProps({ modelValue: 'ref_my_a' })
    await wrapper.setProps({ modelValue: '' })
    await flush()
    if (mode === 'select') await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const options = Array.from(document.querySelectorAll(mode === 'select'
      ? '.el-select-dropdown__item' : '.asset-profile-select__item'))
    expect(options).toHaveLength(3)
    expect(options[0]?.textContent).toContain(publicItem.name)
    expect((wrapper.vm as unknown as { loadedItems: ProfileSummary[] }).loadedItems[0].version).toBe(5)
    expect(wrapper.emitted('ready')?.at(-1)).toEqual([[mineItem]])
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
    await wrapper.setProps({ modelValue: mineItem.profile_ref })
    wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', publicItem.profile_ref)
    await flush()
    expect(wrapper.emitted('loaded')).toHaveLength(2)
    expect(wrapper.emitted('loaded')?.at(-1)).toEqual([publicItem])
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([publicItem.profile_ref])
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
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('copied', { id: 'new_id', profile_ref: 'ref_new', name: '量价齐升·进攻型 副本', version: 1 }, publicItem)
    await flush()
    expect(fetchMine).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['ref_new'])
    expect(wrapper.emitted('copied')).toBeTruthy()
    // P2-2：复制后回写完整 summary（含 source/readonly/is_preset），父级据此并入
    expect(wrapper.emitted('copiedItem')?.at(-1)).toEqual([copiedItem])
    expect((wrapper.vm as unknown as { loadedItems: ProfileSummary[] }).loadedItems).toEqual([publicItem])
    wrapper.unmount()
  })

  it('列表加载失败显示内联错误态并可重试', async () => {
    const fetchMine = vi.fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce([mineItem])
    const { wrapper } = mountSelect({ fetchMine, mode: 'list' })
    await flush()
    expect(wrapper.text()).toContain('筛选方案加载失败')
    expect(wrapper.text()).not.toContain('暂无我的筛选方案')
    expect(wrapper.emitted('loadFailed')?.at(-1)).toEqual(['筛选方案加载失败'])
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

  it('列表支持 Enter/Space 选择，加载期间禁止键盘和点击选择', async () => {
    let finish: (() => void) | undefined
    const fetchMine = vi.fn(async () => [mineItem])
    const { wrapper } = mountSelect({ mode: 'list', fetchMine })
    await flush()
    const row = wrapper.get('.asset-profile-select__item-label')
    expect(row.attributes('tabindex')).toBe('0')
    await row.trigger('keydown', { key: 'Enter' })
    await row.trigger('keydown', { key: ' ' })
    expect(wrapper.emitted('update:modelValue')).toEqual([['ref_my_a'], ['ref_my_a']])
    await wrapper.setProps({ modelValue: 'ref_my_a' })
    expect(row.attributes('aria-pressed')).toBe('true')

    fetchMine.mockImplementationOnce(() => new Promise((resolve) => {
      finish = () => resolve([mineItem])
    }))
    const pending = wrapper.vm.reload()
    await flush()
    expect(row.attributes('tabindex')).toBe('-1')
    await row.trigger('keydown', { key: 'Enter' })
    await row.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toHaveLength(2)
    finish!()
    await pending
    wrapper.unmount()
  })

  it('临时项的独立子操作不通过键盘冒泡选择父项', async () => {
    const { wrapper } = mountSelect({ mode: 'list' })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', publicItem)
    await flush()
    const close = wrapper.get('[data-testid="asset-profile-select-remove"]')
    await close.trigger('keydown', { key: 'Enter' })
    await close.trigger('keydown', { key: ' ' })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
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

    expect(wrapper.emitted('tempRemoved')?.at(-1)).toEqual([presetOwnerItem, false])
    expect(wrapper.text()).not.toContain('本人名下系统内置方案')
    expect(wrapper.text()).toContain('我的筛选方案A')
    expect(fetchMine).toHaveBeenCalledTimes(1)
    expect(copyItem).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each(['select', 'list'] as const)('%s 移除未选中预览保留当前选择及其他候选，移除当前项才清空选中', async (mode) => {
    const { wrapper } = mountSelect({ mode, modelValue: mineItem.profile_ref })
    await flush()
    const preset = { ...publicItem, id: 'preset', profile_ref: 'ref_preset', name: '系统方案', is_preset: true }
    const drawer = wrapper.findComponent(AssetSearchDrawer)
    drawer.vm.$emit('load', publicItem)
    drawer.vm.$emit('load', preset)
    await flush()
    if (mode === 'select') await wrapper.find('[data-testid="asset-profile-select-select"]').trigger('click')
    await flush()
    const removePublic = document.querySelector<HTMLElement>(`[aria-label="从列表移除「${publicItem.name}」"]`)
    removePublic!.click()
    await flush()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.emitted('tempRemoved')?.at(-1)).toEqual([publicItem, false])
    await wrapper.setProps({ modelValue: preset.profile_ref })
    document.querySelector<HTMLElement>('[aria-label="从列表移除「系统方案」"]')!.click()
    await flush()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([''])
    expect(wrapper.emitted('tempRemoved')?.at(-1)).toEqual([preset, true])
    expect((wrapper.vm as unknown as { loadedItems: ProfileSummary[] }).loadedItems).toEqual([])
    wrapper.unmount()
  })

  it('会话项与 mine 的相同 ref 只显示一次，自己的方案不显示移除预览入口', async () => {
    const fetchMine = vi.fn().mockResolvedValueOnce([mineItem]).mockResolvedValueOnce([])
    const { wrapper } = mountSelect({ mode: 'list', fetchMine })
    await flush()
    wrapper.findComponent(AssetSearchDrawer).vm.$emit('load', mineItem)
    await flush()
    expect(wrapper.findAll('.asset-profile-select__item')).toHaveLength(1)
    expect(wrapper.find('[data-testid="asset-profile-select-remove"]').exists()).toBe(false)
    await wrapper.vm.reload()
    await flush()
    expect(wrapper.findAll('.asset-profile-select__item')).toHaveLength(0)
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

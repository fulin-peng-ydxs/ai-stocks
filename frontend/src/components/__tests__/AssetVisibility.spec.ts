// @vitest-environment jsdom
import { nextTick } from 'vue'
import AppHoverInfo from '../AppHoverInfo'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import AssetVisibilityTag from '@/components/AssetVisibilityTag.vue'
import { permission } from '@/directives/permission'
import { useAuthStore } from '@/stores/auth'

function mountActions(role: string, permissions: string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = permissions
  return mount(AssetVisibilityActions, {
    props: {
      visibility: 'tenant',
      readonly: true,
      copyVisible: true,
      copyPermission: 'screen-profile:save',
      reuseVisible: true,
      reusePermission: 'backtest:run',
    },
    global: { plugins: [pinia, ElementPlus], directives: { permission } },
  })
}

describe('AssetVisibilityTag', () => {
  it('展示公开来源和 owner 提示', async () => {
    const w = mount(AssetVisibilityTag, {
      props: { mode: 'source', source: 'tenant', ownerLabel: 'owner_a', readonly: true },
      global: { plugins: [ElementPlus] },
    })
    expect(w.text()).toContain('租户公开')
    await nextTick()
    const hint = w.findComponent(AppHoverInfo).vm.$attrs.content as string
    expect(hint).toContain('owner_a')
    expect(hint).toContain('只读')
    expect(w.find('.asset-visibility-tag').attributes('title')).toBeUndefined()
    w.unmount()
  })

  it('展示公开范围和只读标签', () => {
    const w = mount(AssetVisibilityActions, {
      props: { visibility: 'public', readonly: true },
      global: { plugins: [ElementPlus], directives: { permission } },
    })
    expect(w.text()).toContain('全体公开')
    expect(w.text()).toContain('只读')
  })
})

describe('AssetProfileLabel', () => {
  it('统一展示方案名称、版本和归属标签', async () => {
    const w = mount(AssetProfileLabel, {
      props: {
        name: '趋势评分',
        version: 3,
        source: 'tenant',
        ownerLabel: 'owner_a',
        readonly: true,
      },
      global: { plugins: [ElementPlus] },
    })
    expect(w.text()).toBe('趋势评分v3租户公开')
    await nextTick()
    const hint = w.findComponent(AppHoverInfo).vm.$attrs.content as string
    expect(hint).toContain('owner_a')
    expect(hint).toContain('只读')
    expect(w.find('.asset-visibility-tag').attributes('title')).toBeUndefined()
    w.unmount()
  })
})

describe('AssetVisibilityActions', () => {
  it('复制和复用按钮按权限显示', () => {
    const w = mountActions('normal', ['screen-profile:save'])
    expect(w.text()).toContain('复制为我的方案')
    expect(w.text()).not.toContain('复用参数')
  })

  it('system 角色不依赖 permissions 也显示受控动作', () => {
    const w = mountActions('system', [])
    expect(w.text()).toContain('复制为我的方案')
    expect(w.text()).toContain('复用参数')
  })

  it('发布权限被撤销后，owner 仍可打开下拉收回已发布资产', () => {
    const w = mount(AssetVisibilityActions, {
      props: {
        visibility: 'public',
        readonly: false,
        canPublishTenant: false,
        canPublishPublic: false,
      },
      global: { plugins: [ElementPlus], directives: { permission } },
    })
    expect(w.find('.el-dropdown').exists()).toBe(true)
  })

  it('私有资产且无发布权限时不显示无效下拉', () => {
    const w = mount(AssetVisibilityActions, {
      props: {
        visibility: 'private',
        readonly: false,
        canPublishTenant: false,
        canPublishPublic: false,
      },
      global: { plugins: [ElementPlus], directives: { permission } },
    })
    expect(w.find('.el-dropdown').exists()).toBe(false)
  })
})

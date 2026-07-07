// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import AssetVisibilityActions from '@/components/AssetVisibilityActions.vue'
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
  it('展示公开来源和 owner 提示', () => {
    const w = mount(AssetVisibilityTag, {
      props: { mode: 'source', source: 'tenant', ownerLabel: 'owner_a', readonly: true },
      global: { plugins: [ElementPlus] },
    })
    expect(w.text()).toContain('租户公开')
    expect(w.find('.asset-visibility-tag').attributes('title')).toContain('owner_a')
    expect(w.find('.asset-visibility-tag').attributes('title')).toContain('只读')
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
})

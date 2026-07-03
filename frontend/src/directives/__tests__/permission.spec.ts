// @vitest-environment jsdom
// v-permission 指令 DOM 级测试（T15 / Codex 整改 P2#6）：无码移除元素、有码/ system 保留。
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { permission } from '@/directives/permission'
import { useAuthStore } from '@/stores/auth'

function mountGated(role: string, permissions: string[], code: string | string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = permissions
  return mount(
    {
      props: ['code'],
      template: '<div><button v-permission="code" class="gated">动作</button></div>',
    },
    { props: { code }, global: { plugins: [pinia], directives: { permission } } },
  )
}

describe('v-permission 指令', () => {
  it('无对应功能码 → 移除元素', () => {
    const w = mountGated('normal', ['user:list'], 'user:create')
    expect(w.find('.gated').exists()).toBe(false)
  })
  it('有对应功能码 → 保留元素', () => {
    const w = mountGated('normal', ['user:create'], 'user:create')
    expect(w.find('.gated').exists()).toBe(true)
  })
  it('system 恒保留（即便 permissions 为空）', () => {
    const w = mountGated('system', [], 'user:create')
    expect(w.find('.gated').exists()).toBe(true)
  })
  it('多码取并：含其一即保留', () => {
    const w = mountGated('normal', ['role:list'], ['user:create', 'role:list'])
    expect(w.find('.gated').exists()).toBe(true)
  })
  it('多码全缺 → 移除', () => {
    const w = mountGated('normal', ['x'], ['user:create', 'role:list'])
    expect(w.find('.gated').exists()).toBe(false)
  })
})

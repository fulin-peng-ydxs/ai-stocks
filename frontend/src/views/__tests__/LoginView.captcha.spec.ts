// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref, type Component } from 'vue'
import LoginView from '@/views/LoginView.vue'
import { setRuntimePresetSources } from '@/layout'

const replace = vi.fn()
const login = vi.fn()
const register = vi.fn()
const themeMocks = vi.hoisted(() => ({
  carryCurrentThemeIntoSession: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ replace }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/composables/useTheme', () => ({
  useTheme: () => ({ isDark: ref(false) }),
  toggleTheme: vi.fn(),
  carryCurrentThemeIntoSession: themeMocks.carryCurrentThemeIntoSession,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ login, register }),
}))

vi.mock('@/api/auth', () => ({
  getPublicConfig: vi.fn(),
  getCaptcha: vi.fn(),
  sendEmailCode: vi.fn(),
}))

import * as authApi from '@/api/auth'

beforeEach(() => {
  vi.clearAllMocks()
  setRuntimePresetSources([
    {
      key: 'balanced',
      name: '澄空蓝',
      description: '默认预设',
      config: { values: {} },
    },
  ])
  ;(authApi.getCaptcha as ReturnType<typeof vi.fn>).mockResolvedValue({
    captcha_id: 'captcha-1',
    svg: '<svg viewBox="0 0 100 36"></svg>',
  })
})

describe('LoginView captcha', () => {
  it('只有一个研究空间预设时不显示空操作切换按钮', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: false,
      captcha_after_fails: 3,
      appearance_presets: [
        {
          key: 'balanced',
          name: '澄空蓝',
          description: '默认预设',
          config: { values: {} },
        },
      ],
    })

    const wrapper = mount(LoginView as Component)
    await flushPromises()

    expect(wrapper.find('.login-preset').exists()).toBe(false)
  })

  it('多个研究空间预设时保留切换入口并显示当前预设名称', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: false,
      captcha_after_fails: 3,
      appearance_presets: [
        {
          key: 'balanced',
          name: '澄空蓝',
          description: '默认预设',
          config: { values: {} },
        },
        {
          key: 'custom-gold',
          name: '曜金',
          description: '暖色预设',
          config: { values: {} },
        },
      ],
    })

    const wrapper = mount(LoginView as Component)
    await flushPromises()

    expect(wrapper.get('.login-preset').attributes('aria-label')).toContain('当前澄空蓝')
  })

  it('图形验证码开启后进入登录页直接展示验证码', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: true,
      captcha_after_fails: 3,
    })

    const wrapper = mount(LoginView as Component)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(authApi.getCaptcha).toHaveBeenCalledTimes(1)
    expect(wrapper.find('input[placeholder="图形验证码"]').exists()).toBe(true)
  })

  it('后端返回图形验证码错误时立即拉取并展示验证码', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: true,
      captcha_after_fails: 3,
    })
    login.mockRejectedValueOnce({ response: { data: { msg: '请输入正确的图形验证码' } } })

    const wrapper = mount(LoginView as Component)
    await flushPromises()
    await wrapper.find('input[placeholder="账号 / 邮箱"]').setValue('admin')
    await wrapper.find('input[placeholder="密码"]').setValue('bad-pass')
    await wrapper.find('input[placeholder="图形验证码"]').setValue('AB12')
    await wrapper.find('button.login-primary').trigger('click')
    await flushPromises()

    expect(authApi.getCaptcha).toHaveBeenCalledTimes(2)
    expect(wrapper.find('input[placeholder="图形验证码"]').exists()).toBe(true)
  })

  it('登录成功前锁定登录页当前主题，进入工作台后不被旧远端模式覆盖', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: false,
      captcha_after_fails: 3,
    })
    login.mockResolvedValueOnce(undefined)

    const wrapper = mount(LoginView as Component)
    await flushPromises()
    await wrapper.find('input[placeholder="账号 / 邮箱"]').setValue('debug_normal')
    await wrapper.find('input[placeholder="密码"]').setValue('test-password')
    await wrapper.find('button.login-primary').trigger('click')
    await flushPromises()

    expect(themeMocks.carryCurrentThemeIntoSession).toHaveBeenCalledTimes(1)
    expect(login).toHaveBeenCalled()
    expect(replace).toHaveBeenCalled()
  })
})

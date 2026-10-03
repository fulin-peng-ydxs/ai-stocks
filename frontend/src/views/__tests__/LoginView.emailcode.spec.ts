// @vitest-environment jsdom
// 覆盖本次新增的「邮箱验证码发送」交互：成功→倒计时+成功提示，失败→字段内联报错（不弹全局 toast）。
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { ref, type Component } from 'vue'
import LoginView from '@/views/LoginView.vue'

const replace = vi.fn()
const login = vi.fn()
const register = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ replace }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/composables/useTheme', () => ({
  useTheme: () => ({ isDark: ref(false) }),
  toggleTheme: vi.fn(),
  carryCurrentThemeIntoSession: vi.fn(),
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

async function mountRegister(): Promise<VueWrapper> {
  ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
    require_email_code: true,
    login_captcha_enabled: false,
    captcha_after_fails: 3,
  })
  const wrapper = mount(LoginView as Component)
  await flushPromises()
  // 切到注册标签，验证码字段随之出现
  const tabs = wrapper.findAll('.login-tab')
  await tabs[1].trigger('click')
  await wrapper.vm.$nextTick()
  expect(wrapper.find('.login-field .field-label').text()).toBe('账号')
  await wrapper.find('input[name="email"]').setValue('user@ex.com')
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  // 组件卸载触发 onUnmounted 清理倒计时定时器，避免悬挂
})

describe('LoginView 邮箱验证码发送', () => {
  it('发送成功后进入倒计时并展示成功提示', async () => {
    ;(authApi.sendEmailCode as ReturnType<typeof vi.fn>).mockResolvedValue(null)
    const wrapper = await mountRegister()

    await wrapper.find('.login-emailcode .send').trigger('click')
    await flushPromises()

    expect(authApi.sendEmailCode).toHaveBeenCalledWith('user@ex.com')
    // 成功提示内联展示（非顶部 toast）
    expect(wrapper.find('.field-hint').text()).toContain('验证码已发送')
    // 进入倒计时：按钮文案变为「Ns 后重发」，且置灰禁用
    const send = wrapper.find('.login-emailcode .send')
    expect(send.text()).toMatch(/\d+s 后重发/)
    expect(send.classes()).toContain('disabled')
    // 无字段错误
    expect(wrapper.find('.field-error').exists()).toBe(false)
    wrapper.unmount()
  })

  it('发送失败时在验证码框下内联报错，不进入倒计时', async () => {
    ;(authApi.sendEmailCode as ReturnType<typeof vi.fn>).mockRejectedValue({
      uiMessage: '验证码发送过于频繁，请稍后再试',
    })
    const wrapper = await mountRegister()

    await wrapper.find('.login-emailcode .send').trigger('click')
    await flushPromises()

    // 错误就地展示在字段下方
    expect(wrapper.find('.field-error').text()).toContain('验证码发送过于频繁')
    // 未进入倒计时：按钮仍为「发送验证码」
    expect(wrapper.find('.login-emailcode .send').text()).toContain('发送验证码')
    wrapper.unmount()
  })

  it('未填邮箱直接发送时提示先填邮箱，不调用接口', async () => {
    ;(authApi.sendEmailCode as ReturnType<typeof vi.fn>).mockResolvedValue(null)
    const wrapper = await mountRegister()
    await wrapper.find('input[name="email"]').setValue('')

    await wrapper.find('.login-emailcode .send').trigger('click')
    await flushPromises()

    expect(authApi.sendEmailCode).not.toHaveBeenCalled()
    expect(wrapper.find('.field-error').text()).toContain('请先填写邮箱')
    wrapper.unmount()
  })
})

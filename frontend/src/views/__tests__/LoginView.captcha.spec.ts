// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import ElementPlus from 'element-plus'
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

const wrappers: ReturnType<typeof mount>[] = []
function mountLogin() {
  const wrapper = mount(LoginView as Component, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  return wrapper
}
afterEach(() => { for (const wrapper of wrappers.splice(0)) wrapper.unmount() })

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
  it.each([
    ['查询失败 SQL: SELECT password FROM users', '账号或密码错误'],
    ['认证失败 https://upstream.invalid/login', '账号或密码错误'],
    ['账号已被禁用', '账号已被禁用'],
  ])('登录字段反馈过滤技术错误，业务原因仍可展示：%s', async (msg, expected) => {
    vi.mocked(authApi.getPublicConfig).mockResolvedValue({ require_email_code: false, login_captcha_enabled: false, captcha_after_fails: 3, auto_scale_exponent: 0.1, appearance_presets: [] })
    login.mockRejectedValueOnce({ response: { data: { msg } } })
    const wrapper = mountLogin()
    await flushPromises()
    await wrapper.get('input[name="account"]').setValue('debug_normal')
    await wrapper.get('input[name="password"]').setValue('test-password')
    await wrapper.get('button.login-primary').trigger('click')
    await flushPromises()
    expect(login).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain(expected)
    if (msg !== expected) expect(wrapper.text()).not.toContain(msg)
    expect(wrapper.get('button.login-primary').attributes('disabled')).toBeUndefined()
  })

  it('注册失败与验证码发送失败均过滤技术原文，并允许重新提交', async () => {
    vi.mocked(authApi.getPublicConfig).mockResolvedValue({ require_email_code: true, login_captcha_enabled: false, captcha_after_fails: 3, auto_scale_exponent: 0.1, appearance_presets: [] })
    const failure = { uiMessage: '请求失败 SQL: SELECT secret FROM users' }
    register.mockRejectedValueOnce(failure)
    vi.mocked(authApi.sendEmailCode).mockRejectedValueOnce(failure)
    const wrapper = mountLogin()
    await flushPromises()
    await wrapper.get('button.login-link').trigger('click')
    await wrapper.get('input[name="account"]').setValue('debug_normal')
    await wrapper.get('input[name="password"]').setValue('test-password')
    await wrapper.get('input[name="confirm"]').setValue('test-password')
    await wrapper.get('input[name="email"]').setValue('debug@example.com')
    await wrapper.get('input[name="emailCode"]').setValue('123456')
    await wrapper.get('button.login-primary').trigger('click')
    await flushPromises()
    expect(register).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('操作失败，请稍后重试')
    expect(wrapper.text()).not.toContain('SELECT')
    expect(wrapper.get('button.login-primary').attributes('disabled')).toBeUndefined()
    await wrapper.get('input[name="email"]').setValue('debug@example.com')
    await wrapper.get('button.send').trigger('click')
    await flushPromises()
    expect(authApi.sendEmailCode).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('验证码发送失败，请稍后重试')
    expect(wrapper.text()).not.toContain('SELECT')
    expect(wrapper.get('button.send').attributes('disabled')).toBeUndefined()
  })

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

    const wrapper = mountLogin()
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

    const wrapper = mountLogin()
    await flushPromises()

    expect(wrapper.get('.login-preset').attributes('aria-label')).toContain('当前澄空蓝')
  })

  it('创建账户与返回登录使用可键盘操作的标准链接按钮', async () => {
    vi.mocked(authApi.getPublicConfig).mockResolvedValue({ require_email_code: true, login_captcha_enabled: false, captcha_after_fails: 3, auto_scale_exponent: 0.1, appearance_presets: [] })
    const wrapper = mountLogin()
    await flushPromises()
    expect(wrapper.get('button.login-link').classes()).toEqual(expect.arrayContaining(['el-button--primary', 'is-link']))
    await wrapper.get('button.login-link').trigger('click')
    expect(wrapper.find('input[name="email"]').exists()).toBe(true)
    expect(wrapper.get('button.login-link').text()).toBe('已有账户，返回登录')
    await wrapper.get('button.login-link').trigger('click')
    expect(wrapper.find('input[name="email"]').exists()).toBe(false)
  })

  it('发送验证码区分加载与倒计时禁用，失败后可重试且不会重复发送', async () => {
    vi.mocked(authApi.getPublicConfig).mockResolvedValue({ require_email_code: true, login_captcha_enabled: false, captcha_after_fails: 3, auto_scale_exponent: 0.1, appearance_presets: [] })
    let rejectSend!: (error: unknown) => void
    vi.mocked(authApi.sendEmailCode).mockImplementationOnce(() => new Promise((_, reject) => { rejectSend = reject }))
    const wrapper = mountLogin()
    await flushPromises()
    await wrapper.get('button.login-link').trigger('click')
    await wrapper.get('input[name="email"]').setValue('test@example.com')
    await wrapper.get('button.send').trigger('click')
    expect(wrapper.get('button.send').classes()).toContain('is-loading')
    await wrapper.get('button.send').trigger('click')
    expect(authApi.sendEmailCode).toHaveBeenCalledTimes(1)
    rejectSend({ uiMessage: '发送失败，请重试' })
    await flushPromises()
    expect(wrapper.get('button.send').classes()).not.toContain('is-loading')
    expect(wrapper.get('button.send').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('发送失败，请重试')
    vi.mocked(authApi.sendEmailCode).mockResolvedValueOnce(null)
    await wrapper.get('button.send').trigger('click')
    await flushPromises()
    expect(wrapper.get('button.send').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button.send').classes()).not.toContain('is-loading')
    expect(wrapper.get('button.send').text()).toContain('后重发')
  })

  it('图形验证码开启后进入登录页直接展示验证码', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: true,
      captcha_after_fails: 3,
    })

    const wrapper = mountLogin()
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(authApi.getCaptcha).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.login-field .field-label').text()).toBe('账号 / 邮箱')
    expect(wrapper.find('input[name="captchaCode"]').exists()).toBe(true)
  })

  it('后端返回图形验证码错误时立即拉取并展示验证码', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: true,
      captcha_after_fails: 3,
    })
    login.mockRejectedValueOnce({ response: { data: { msg: '请输入正确的图形验证码' } } })

    const wrapper = mountLogin()
    await flushPromises()
    await wrapper.find('input[name="account"]').setValue('admin')
    await wrapper.find('input[name="password"]').setValue('bad-pass')
    await wrapper.find('input[name="captchaCode"]').setValue('AB12')
    await wrapper.find('button.login-primary').trigger('click')
    await flushPromises()

    expect(authApi.getCaptcha).toHaveBeenCalledTimes(2)
    expect(wrapper.find('input[name="captchaCode"]').exists()).toBe(true)
  })

  it('登录成功前锁定登录页当前主题，进入工作台后不被旧远端模式覆盖', async () => {
    ;(authApi.getPublicConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      require_email_code: true,
      login_captcha_enabled: false,
      captcha_after_fails: 3,
    })
    login.mockResolvedValueOnce(undefined)

    const wrapper = mountLogin()
    await flushPromises()
    await wrapper.find('input[name="account"]').setValue('debug_normal')
    await wrapper.find('input[name="password"]').setValue('test-password')
    await wrapper.find('button.login-primary').trigger('click')
    await flushPromises()

    expect(themeMocks.carryCurrentThemeIntoSession).toHaveBeenCalledTimes(1)
    expect(login).toHaveBeenCalled()
    expect(replace).toHaveBeenCalled()
  })
})

<script setup lang="ts">
import AppHoverInfo from '@/components/AppHoverInfo'
// 登录 / 注册页：金融科技视觉与明暗双主题，认证流程由公开配置动态控制。
// 全屏独立壳（App.vue 按 meta.fullscreen 脱离主框架单独渲染），不套用布局 archetype、不走 LayoutHost。
// 契约：用 position:fixed;inset:0 全屏（禁 vh 高度、禁手写 .v-page/.v-grow，过 layout-contract.spec.ts）。
import { computed, onMounted, onUnmounted, reactive, ref, type CSSProperties } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  carryCurrentThemeIntoSession,
  toggleTheme,
  useTheme,
} from '@/composables/useTheme'
import {
  getLoginSurfaceSpec,
  rgbaFromHex,
  setRuntimePresetSources,
  useLayoutPreset,
} from '@/layout'
import { useAuthStore } from '@/stores/auth'
import { getCaptcha, getPublicConfig, sendEmailCode } from '@/api/auth'
import { setAutoScaleResponsiveExponent } from '@/composables/useDisplayScale'
import BrandMark from '@/components/BrandMark.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const { isDark } = useTheme()
const { activePresetKey, options: presetOptions, setLayoutPreset } = useLayoutPreset()
const activePresetLabel = computed(() =>
  presetOptions.value.find((option) => option.value === activePresetKey.value)?.label ?? '澄空蓝')
const loginSurfaceStyle = computed<CSSProperties>(() => {
  const spec = getLoginSurfaceSpec(isDark.value ? 'dark' : 'light')
  return {
    '--login-page-bg': spec.pageBg,
    '--login-panel-bg': spec.sidebarBg,
    '--login-panel-deep': spec.sidebarBg,
    '--login-card-bg': rgbaFromHex(spec.cardBg, spec.cardAlpha),
    '--login-card-opaque-bg': spec.surfaceBg,
  } as CSSProperties
})

type Mode = 'login' | 'register'
const mode = ref<Mode>('login')

// 公开配置（无需 token）：是否要邮箱验证码 / 是否启用图形验证码 / 图形码强制阈值。
// 挂载时拉取，失败用保守默认；开关开启即展示图形码，阈值仍作为后端强制校验兜底。
const cfg = reactive({ requireEmailCode: true, loginCaptchaEnabled: false, captchaAfterFails: 3 })

const form = reactive({
  account: '',
  password: '',
  confirm: '',
  email: '',
  emailCode: '',
  captchaCode: '',
})
const showPwd = ref(false)
const loading = ref(false)

// 字段级错误态：账号/密码等各输入框下方就地展开报错；form 为不归属单字段的整体错误（如账密不匹配）。
// 不再用顶部全局 toast（见 DESIGN.md「error 不只依赖全局 toast」）。
const errors = reactive({
  account: '', password: '', confirm: '', email: '', emailCode: '', captcha: '', form: '',
})
function clearErrors() {
  errors.account = ''
  errors.password = ''
  errors.confirm = ''
  errors.email = ''
  errors.emailCode = ''
  errors.captcha = ''
  errors.form = ''
}
// 从被拦截器跳过全局 toast 的错误里取可读文案（interceptor 已挂 uiMessage）。
function pickMessage(e: unknown): string {
  const err = e as { uiMessage?: string; response?: { data?: { msg?: string } }; message?: string }
  return err?.uiMessage || err?.response?.data?.msg || ''
}
// 把后端错误文案按关键字落到对应字段；无法归属的进 form 整体错误。
function mapAuthError(msg: string, fallbackField: 'password' | 'form') {
  if (!msg) { errors.form = '操作失败，请稍后重试'; return }
  if (msg.includes('账号已存在') || msg.includes('账号')) errors.account = msg
  else if (msg.includes('邮箱已被注册') || msg.includes('邮箱格式') || (msg.includes('邮箱') && !msg.includes('验证码'))) errors.email = msg
  else if (msg.includes('验证码')) errors.emailCode = msg
  else if (msg.includes('密码')) errors.password = msg
  else errors[fallbackField] = msg
}

// 图形验证码：后端启用即在登录页展示；登录失败后刷新，避免复用已消费的验证码。
const captchaId = ref('')
const captchaSvg = ref('')
const needCaptcha = ref(false)
const loginFails = ref(0)

// 邮箱验证码发送倒计时（秒）+ 在途加载态 + 成功提示
const emailCountdown = ref(0)
const emailSending = ref(false)
const emailHint = ref('')
let emailTimer: ReturnType<typeof setInterval> | undefined

// 启动 60s 倒计时：启动前先清旧定时器，杜绝多次点击叠加多个 interval 导致「倒计时飞快」。
function startEmailCountdown() {
  if (emailTimer) clearInterval(emailTimer)
  emailCountdown.value = 60
  emailTimer = setInterval(() => {
    emailCountdown.value -= 1
    if (emailCountdown.value <= 0 && emailTimer) {
      clearInterval(emailTimer)
      emailTimer = undefined
    }
  }, 1000)
}

async function loadPublicConfig(syncCaptcha = true) {
  try {
    const c = await getPublicConfig()
    cfg.requireEmailCode = c.require_email_code
    cfg.loginCaptchaEnabled = c.login_captcha_enabled
    cfg.captchaAfterFails = c.captcha_after_fails
    setAutoScaleResponsiveExponent(c.auto_scale_exponent)
    if (c.appearance_presets?.length) setRuntimePresetSources(c.appearance_presets)
    if (!cfg.loginCaptchaEnabled) {
      needCaptcha.value = false
      captchaId.value = ''
      captchaSvg.value = ''
      form.captchaCode = ''
    } else if (syncCaptcha && mode.value === 'login' && !needCaptcha.value) {
      await refreshCaptcha()
    }
  } catch {
    // 公开配置拉取失败不阻断登录：保守保留默认（要邮箱码、不强制图形码）
  }
}

onMounted(async () => {
  await loadPublicConfig()
})

onUnmounted(() => {
  if (emailTimer) clearInterval(emailTimer)
})

function setMode(m: Mode) {
  mode.value = m
  clearErrors()
  emailHint.value = ''
  if (m === 'login' && cfg.loginCaptchaEnabled && !needCaptcha.value) {
    void refreshCaptcha()
  }
}

function cyclePreset() {
  const current = presetOptions.value.findIndex((option) => option.value === activePresetKey.value)
  const next = presetOptions.value[(current + 1) % presetOptions.value.length]
  if (next) setLayoutPreset(next.value)
}

async function refreshCaptcha() {
  try {
    const c = await getCaptcha()
    captchaId.value = c.captcha_id
    captchaSvg.value = c.svg
    needCaptcha.value = true
  } catch {
    // 验证码接口异常由拦截器提示
  }
}

async function onLogin() {
  await loadPublicConfig()
  clearErrors()
  if (!form.account) errors.account = '请输入账号'
  if (!form.password) errors.password = '请输入密码'
  if (errors.account || errors.password) return
  if (needCaptcha.value && !form.captchaCode) {
    errors.captcha = '请输入图形验证码'
    return
  }
  loading.value = true
  try {
    carryCurrentThemeIntoSession()
    await auth.login(form.account.trim(), form.password, {
      captchaId: needCaptcha.value ? captchaId.value : undefined,
      captchaCode: needCaptcha.value ? form.captchaCode.trim() : undefined,
    })
    const redirect = (route.query.redirect as string) || '/'
    await router.replace(redirect)
  } catch (error) {
    // 登录失败：就地内联报错（不弹全局 toast）；累计失败达阈值且后端启用才显示图形码
    const msg = pickMessage(error)
    form.captchaCode = ''
    if (msg.includes('图形验证码')) {
      errors.captcha = msg
      await refreshCaptcha()
      return
    }
    // 账密/锁定类错误归为整体错误，展示在提交按钮上方
    errors.form = msg || '账号或密码错误'
    loginFails.value += 1
    if (needCaptcha.value || (cfg.loginCaptchaEnabled && loginFails.value >= cfg.captchaAfterFails)) {
      await refreshCaptcha()
    }
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  clearErrors()
  if (!form.account) errors.account = '请输入账号'
  if (!form.password) errors.password = '请输入密码'
  if (form.password && form.password !== form.confirm) errors.confirm = '两次输入的密码不一致'
  if (cfg.requireEmailCode) {
    if (!form.email) errors.email = '请填写邮箱'
    if (!form.emailCode) errors.emailCode = '请填写邮箱验证码'
  }
  if (errors.account || errors.password || errors.confirm || errors.email || errors.emailCode) return
  loading.value = true
  try {
    carryCurrentThemeIntoSession()
    await auth.register({
      account: form.account.trim(),
      password: form.password,
      email: form.email.trim() || undefined,
      email_code: form.emailCode.trim() || undefined,
    })
    await router.replace('/') // 注册后已自动登录
  } catch (error) {
    // 注册失败：把后端文案映射到对应字段（账号已存在/邮箱已被注册/验证码错/密码强度等）
    mapAuthError(pickMessage(error), 'form')
  } finally {
    loading.value = false
  }
}

async function onSendEmailCode() {
  errors.emailCode = ''
  emailHint.value = ''
  if (!form.email) {
    errors.email = '请先填写邮箱'
    return
  }
  if (emailCountdown.value > 0 || emailSending.value) return
  emailSending.value = true
  try {
    await sendEmailCode(form.email.trim())
    emailHint.value = '验证码已发送，请查收邮箱'
    startEmailCountdown()
  } catch (error) {
    // 发送失败（限流/发信异常等）就地展示在验证码框下方
    errors.emailCode = pickMessage(error) || '验证码发送失败，请稍后重试'
  } finally {
    emailSending.value = false
  }
}

function onSubmit() {
  return mode.value === 'login' ? onLogin() : onRegister()
}
</script>

<template>
  <div
    class="login-shell"
    role="region"
    aria-label="登录页"
    :class="[`preset-${activePresetKey}`, { 'is-register': mode === 'register', 'is-dark': isDark }]"
    :style="loginSurfaceStyle"
  >
    <section class="login-brand" data-testid="login-brand-surface">
      <header class="login-brand-head">
        <div class="login-brand-id">
          <div class="login-logo">
            <BrandMark :tone="isDark ? 'dark' : 'light'" />
          </div>
          <ul class="login-brand-points">
            <li>龙头梯队识别</li>
            <li>盘感训练</li>
            <li>点时回测验证</li>
          </ul>
        </div>
      </header>

      <div class="market-stage" aria-hidden="true">
        <div class="market-orbit orbit-one" />
        <div class="market-orbit orbit-two" />
        <svg class="market-track" viewBox="0 0 900 430" preserveAspectRatio="none">
          <defs>
            <linearGradient id="track-gradient" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stop-color="currentColor" stop-opacity="0" />
              <stop offset="0.36" stop-color="currentColor" stop-opacity=".42" />
              <stop offset="1" stop-color="currentColor" stop-opacity="1" />
            </linearGradient>
            <filter id="track-glow" x="-20%" y="-40%" width="140%" height="180%">
              <feGaussianBlur stdDeviation="7" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <linearGradient id="track-area-gradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="currentColor" stop-opacity=".16" />
              <stop offset="0.72" stop-color="currentColor" stop-opacity=".04" />
              <stop offset="1" stop-color="currentColor" stop-opacity="0" />
            </linearGradient>
          </defs>
          <path class="market-track-echo" d="M-20 378C96 362 150 392 226 350C302 308 348 336 414 300C488 260 524 296 586 238C644 186 700 226 760 164C808 114 852 132 920 78" />
          <path class="market-track-area" d="M-20 350C80 334 128 366 205 320C284 273 324 305 390 268C466 226 497 265 558 204C614 148 675 193 733 126C782 70 832 92 920 30L920 440L-20 440Z" />
          <path class="market-track-shadow" d="M-20 350C80 334 128 366 205 320C284 273 324 305 390 268C466 226 497 265 558 204C614 148 675 193 733 126C782 70 832 92 920 30" />
          <path class="market-track-line" d="M-20 350C80 334 128 366 205 320C284 273 324 305 390 268C466 226 497 265 558 204C614 148 675 193 733 126C782 70 832 92 920 30" />
          <circle class="market-track-node node-one" cx="390" cy="268" r="5" />
          <circle class="market-track-node node-two" cx="558" cy="204" r="5" />
          <circle class="market-track-node node-three" cx="733" cy="126" r="7" />
        </svg>
        <div class="market-readout readout-one">
          <span class="mr-label">龙头梯队</span>
          <span class="mr-value">42<i>只</i></span>
          <span class="mr-delta up">▲ 6</span>
        </div>
        <div class="market-readout readout-two">
          <span class="mr-label">晋级率</span>
          <span class="mr-value">38.2<i>%</i></span>
          <span class="mr-delta up">▲ 2.1</span>
        </div>
        <div class="market-readout readout-three">
          <span class="mr-label">趋势强度</span>
          <span class="mr-value">71</span>
          <span class="mr-delta down">▼ 3</span>
        </div>
      </div>

      <div class="login-brand-copy">
        <h1>看见趋势，<br /><em>先于共识。</em></h1>
        <p>为趋势交易者构建的每日复盘与龙头研究系统。</p>
      </div>

      <div class="market-ticker" aria-hidden="true">
        <div class="market-ticker-track">
          <div class="ticker-group">
            <span class="t-item"><em>SH 000001</em>上证指数<b class="up">3,247.18 ▲0.42%</b></span>
            <span class="t-item"><em>SZ 399001</em>深证成指<b class="up">10,562.4 ▲0.68%</b></span>
            <span class="t-item"><em>SZ 399006</em>创业板指<b class="down">2,118.9 ▼0.15%</b></span>
            <span class="t-item"><em>SH 000688</em>科创 50<b class="up">986.52 ▲1.03%</b></span>
            <span class="t-item">龙头梯队<b class="up">42只 ▲6</b></span>
            <span class="t-item">晋级率<b class="up">38.2% ▲2.1</b></span>
            <span class="t-item">趋势强度<b class="down">71 ▼3</b></span>
          </div>
          <div class="ticker-group">
            <span class="t-item"><em>SH 000001</em>上证指数<b class="up">3,247.18 ▲0.42%</b></span>
            <span class="t-item"><em>SZ 399001</em>深证成指<b class="up">10,562.4 ▲0.68%</b></span>
            <span class="t-item"><em>SZ 399006</em>创业板指<b class="down">2,118.9 ▼0.15%</b></span>
            <span class="t-item"><em>SH 000688</em>科创 50<b class="up">986.52 ▲1.03%</b></span>
            <span class="t-item">龙头梯队<b class="up">42只 ▲6</b></span>
            <span class="t-item">晋级率<b class="up">38.2% ▲2.1</b></span>
            <span class="t-item">趋势强度<b class="down">71 ▼3</b></span>
          </div>
        </div>
      </div>

    </section>

    <section class="login-auth" data-testid="login-auth-surface">
      <div class="login-controls">
        <button
          v-if="presetOptions.length > 1"
          class="login-preset"
          type="button"
          :aria-label="`切换研究空间，当前${activePresetLabel}`"
          @click="cyclePreset"
        >
          <i /><span>{{ activePresetLabel }}</span>
        </button>
        <AppHoverInfo content="切换黑/白主题">
          <button tabindex="0" class="login-theme" type="button" aria-label="切换主题" @click="toggleTheme">
            <svg v-if="isDark" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4" />
              <circle cx="12" cy="12" r="4" />
            </svg>
            <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" />
            </svg>
          </button>
        </AppHoverInfo>
      </div>

      <div class="login-card" data-testid="login-card-surface">
        <div class="login-card-title">
          <h2>{{ mode === 'login' ? '欢迎回来' : '创建研究账户' }}</h2>
          <p>{{ mode === 'login' ? '进入你的市场研究工作台' : '开启专业、专注的每日复盘' }}</p>
        </div>

        <div class="login-tabs" role="tablist" aria-label="账户操作">
          <button class="login-tab" :class="{ active: mode === 'login' }" type="button" role="tab"
                  :aria-selected="mode === 'login'" @click="setMode('login')">登录账户</button>
          <button class="login-tab" :class="{ active: mode === 'register' }" type="button" role="tab"
                  :aria-selected="mode === 'register'" @click="setMode('register')">注册账户</button>
        </div>

        <div class="login-field-block">
          <label class="login-field" :class="{ 'is-error': errors.account }">
            <span class="field-label">{{ mode === 'login' ? '账号 / 邮箱' : '账号' }}</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 4-6 8-6s8 2 8 6" />
            </svg>
            <input v-model="form.account" name="account" type="text"
                   autocomplete="username" @input="errors.account = ''; errors.form = ''" @keyup.enter="onSubmit" />
          </label>
          <p v-if="errors.account" class="field-error">{{ errors.account }}</p>
        </div>

        <div class="login-field-block">
          <label class="login-field" :class="{ 'is-error': errors.password }">
            <span class="field-label">密码</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
            <input v-model="form.password" name="password" :type="showPwd ? 'text' : 'password'"
                   :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
                   @input="errors.password = ''; errors.form = ''" @keyup.enter="onSubmit" />
            <svg class="eye" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" @click="showPwd = !showPwd">
              <path v-if="showPwd" d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z" />
              <path v-else d="M3 3l18 18M10.6 5.1A9.6 9.6 0 0 1 12 5c6 0 10 7 10 7a17 17 0 0 1-3.3 3.9M6.6 6.6A17 17 0 0 0 2 12s4 7 10 7a9.6 9.6 0 0 0 3.4-.6" />
              <circle v-if="showPwd" cx="12" cy="12" r="3" />
            </svg>
          </label>
          <p v-if="errors.password" class="field-error">{{ errors.password }}</p>
        </div>

        <div v-if="mode === 'register'" class="login-field-block">
          <label class="login-field" :class="{ 'is-error': errors.confirm }">
            <span class="field-label">确认密码</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
            <input v-model="form.confirm" name="confirm" type="password" autocomplete="new-password"
                   @input="errors.confirm = ''" @keyup.enter="onSubmit" />
          </label>
          <p v-if="errors.confirm" class="field-error">{{ errors.confirm }}</p>
        </div>

        <div v-if="mode === 'register'" class="login-field-block">
          <label class="login-field" :class="{ 'is-error': errors.email }">
            <span class="field-label">邮箱</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" />
            </svg>
            <input v-model="form.email" name="email" type="email" autocomplete="email"
                   @input="errors.email = ''" @keyup.enter="onSubmit" />
          </label>
          <p v-if="errors.email" class="field-error">{{ errors.email }}</p>
        </div>

        <div v-if="mode === 'register' && cfg.requireEmailCode" class="login-field-block">
          <label class="login-field login-emailcode" :class="{ 'is-error': errors.emailCode }">
            <span class="field-label">邮箱验证码</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" />
            </svg>
            <input v-model="form.emailCode" name="emailCode" type="text" autocomplete="one-time-code"
                   @input="errors.emailCode = ''" @keyup.enter="onSubmit" />
            <span class="send" :class="{ disabled: emailCountdown > 0 || emailSending }"
                  role="button" @click="onSendEmailCode">
              <i v-if="emailSending" class="send-spinner" aria-hidden="true" />
              {{ emailSending ? '发送中…' : emailCountdown > 0 ? `${emailCountdown}s 后重发` : '发送验证码' }}
            </span>
          </label>
          <p v-if="errors.emailCode" class="field-error">{{ errors.emailCode }}</p>
          <p v-else-if="emailHint" class="field-hint">{{ emailHint }}</p>
        </div>

        <template v-if="mode === 'login' && needCaptcha">
          <div class="login-field-block">
            <div class="login-captcha-row">
              <label class="login-field dashed" :class="{ 'is-error': errors.captcha }">
                <span class="field-label">图形验证码</span>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 3v18M3 12h18" />
                </svg>
                <input v-model="form.captchaCode" name="captchaCode" type="text"
                       @input="errors.captcha = ''" @keyup.enter="onSubmit" />
              </label>
              <AppHoverInfo content="点击刷新">
                <div tabindex="0" class="login-captcha-img" v-html="captchaSvg" role="button" @click="refreshCaptcha" @keydown.enter.prevent="refreshCaptcha" @keydown.space.prevent="refreshCaptcha" />
              </AppHoverInfo>
            </div>
            <p v-if="errors.captcha" class="field-error">{{ errors.captcha }}</p>
          </div>
        </template>

        <p v-if="errors.form" class="login-form-error" role="alert">{{ errors.form }}</p>

        <button v-if="mode === 'login'" class="login-primary" type="button" :disabled="loading" @click="onLogin">
          {{ loading ? '登 录 中…' : '登 录' }}
        </button>
        <button v-else class="login-primary" type="button" :disabled="loading" @click="onRegister">
          {{ loading ? '注 册 中…' : '注 册' }}
        </button>

        <div v-if="mode === 'login'" class="login-rowbetween">
          <span class="login-security"><i />安全加密连接</span>
          <button class="login-link" type="button" @click="setMode('register')">创建账户</button>
        </div>
        <div v-else class="login-rowbetween login-rowend">
          <button class="login-link" type="button" @click="setMode('login')">已有账户，返回登录</button>
        </div>

        <div class="login-footnote">复盘啦 · EOD 趋势龙头研究系统</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-shell {
  /* 登录与工作台消费同一组表面；运行时同源变量由 themeSurfaces.ts 注入。 */
  --login-page-bg: var(--app-surface-canvas);
  --login-panel-bg: var(--app-surface-navigation);
  --login-panel-deep: var(--app-surface-navigation);
  --login-grid: color-mix(in srgb, var(--login-accent) 7%, transparent);
  --login-card-bg: var(--app-surface-container);
  --login-card-opaque-bg: var(--app-surface-container);
  --login-card-edge: var(--app-border-default);
  --login-border: var(--app-border-default);
  --login-border-focus: var(--el-color-primary);
  --login-border-dash: var(--app-border-strong);
  --login-input-bg: var(--app-surface-control);
  --login-text: var(--el-text-color-primary, #17181c);
  --login-text-sub: var(--el-text-color-regular, #44464d);
  --login-text-muted: var(--el-text-color-secondary, #6e7078);
  --login-accent: var(--el-color-primary);
  --login-accent-strong: var(--el-color-primary-dark-2, #1264d9);
  --login-accent-readable: var(--login-accent-strong);
  --login-accent-text: #ffffff;
  --login-captcha-bg: var(--app-surface-section);
  --login-toggle-bg: var(--app-surface-control);
  --login-divider: var(--app-border-default);
  --login-shadow: var(--shell-surface-shadow, rgba(20, 24, 32, 0.1));
  --login-brand-text: var(--el-text-color-primary, #17181c);
  --login-brand-accent: var(--login-accent);
  --login-brand-sub: var(--el-text-color-regular, #44464d);
  --login-brand-muted: var(--el-text-color-secondary, #6e7078);
  --login-track: color-mix(in srgb, var(--login-accent) 84%, white 16%);
  --login-track-glow: color-mix(in srgb, var(--login-accent) 25%, transparent);
  --login-danger: var(--el-color-danger, #d9363e);
  --login-danger-ring: color-mix(in srgb, var(--login-danger) 16%, transparent);
  --login-danger-bg: var(--app-surface-danger);
  --login-success: var(--el-color-success, #168f63);

  position: fixed;
  inset: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(430px, 1fr);
  background: var(--login-page-bg);
  color: var(--login-text);
  font-family: var(--app-font-family-base);
  transition: background 0.3s, color 0.3s;
}
.login-shell.is-dark {
  --login-accent-readable: var(--el-color-primary-light-3, #77adff);
  --login-input-bg: var(--app-surface-control);
  --login-toggle-bg: var(--app-surface-control);
}

.login-brand {
  position: relative;
  min-width: 0;
  padding: 38px clamp(36px, 5cqw, 76px) 34px;
  background: var(--login-panel-bg);
  color: var(--login-brand-text);
  overflow: hidden;
}
.login-brand::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(var(--login-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--login-grid) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(90deg, rgba(0, 0, 0, 0.35), #000 55%, rgba(0, 0, 0, 0.25));
}
.login-brand::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 1px;
  height: 100%;
  background: linear-gradient(transparent, color-mix(in srgb, var(--login-track) 48%, transparent), transparent);
}
.login-brand-head {
  position: relative;
  z-index: 3;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-4);
}
.login-brand-id {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}
.login-logo {
  display: flex;
  align-items: center;
}
.market-stage {
  position: absolute;
  z-index: 1;
  inset: 18% -4% 12% 7%;
}
.market-orbit {
  position: absolute;
  border-radius: 50%;
  border: 1px solid color-mix(in srgb, var(--login-accent) 10%, transparent);
  transform: rotate(-19deg);
}
.orbit-one { width: 520px; height: 220px; right: 5%; top: 18%; }
.orbit-two { width: 680px; height: 320px; right: -9%; top: 8%; }
.market-track {
  position: absolute;
  inset: 8% 0 0;
  width: 100%;
  height: 78%;
  color: var(--login-track);
  overflow: visible;
}
.market-track-shadow {
  fill: none;
  stroke: var(--login-track-glow);
  stroke-width: 14;
  filter: url(#track-glow);
}
/* 趋势实体感：曲线下的渐变面积 + 一条平行虚影，让轨迹从「一根虚线」变成「一片趋势」 */
.market-track-area {
  fill: url(#track-area-gradient);
  stroke: none;
  color: var(--login-track);
}
.market-track-echo {
  fill: none;
  stroke: color-mix(in srgb, var(--login-track) 20%, transparent);
  stroke-width: 1.2;
  stroke-linecap: round;
  stroke-dasharray: 2 7;
}
.market-track-line {
  fill: none;
  stroke: url(#track-gradient);
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-dasharray: 8 8;
  animation: track-flow 18s linear infinite;
}
.market-track-node {
  fill: color-mix(in srgb, var(--login-track) 68%, white 32%);
  stroke: color-mix(in srgb, var(--login-track) 22%, transparent);
  stroke-width: 10;
}
.market-index {
  position: absolute;
  padding: 5px 8px;
  border-left: 1px solid color-mix(in srgb, var(--login-track) 45%, transparent);
  color: var(--login-brand-muted);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-icon-size-xs);
  letter-spacing: 0.12em;
}
.index-one { left: 38%; top: 64%; }
.index-two { left: 58%; top: 43%; }
.index-three { right: 7%; top: 19%; }

/* 数据标注：挂在轨迹节点旁，沿用 market-index 的 tick 线语言，但承载真实指标，与场景同源而非浮层 */
.market-readout {
  position: absolute;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  padding-left: 13px;
  border-left: 1px solid color-mix(in srgb, var(--login-track) 52%, transparent);
}
.market-readout::before {
  content: '';
  position: absolute;
  left: -3px;
  top: 3px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--login-accent);
  box-shadow: 0 0 8px color-mix(in srgb, var(--login-accent) 56%, transparent);
}
.readout-one { left: 37.5%; top: 41%; }
.readout-two { left: 57.5%; top: 31%; }
.readout-three { left: 79%; top: 6%; }
.mr-label {
  color: var(--login-brand-muted);
  font-size: var(--app-font-size-caption);
  letter-spacing: 0.14em;
}
.mr-value {
  color: var(--login-brand-text);
  font-family: var(--app-font-family-mono);
  font-size: clamp(24px, 1.9cqw, 30px);
  font-weight: var(--app-font-weight-section);
  line-height: var(--app-line-height-solid);
  font-variant-numeric: tabular-nums;
}
.mr-value > i {
  margin-left: 2px;
  color: var(--login-brand-muted);
  font-size: var(--app-font-size-micro);
  font-style: normal;
  font-weight: var(--app-font-weight-regular);
}
.mr-delta {
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-caption);
  letter-spacing: 0.04em;
}
.mr-delta.up { color: var(--login-accent); }
.mr-delta.down { color: var(--login-danger); }


/* 行情跑马灯：横穿左栏底部的数据带，把横向的「虚」填实，与底部留白融合 */
.market-ticker {
  position: absolute;
  z-index: 2;
  left: 0;
  right: 0;
  bottom: 0;
  border-top: 1px solid var(--login-divider);
  background: color-mix(in srgb, var(--login-panel-bg) 78%, var(--login-accent) 3%);
  overflow: hidden;
  mask-image: linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent);
}
.market-ticker-track {
  display: flex;
  width: max-content;
  animation: ticker-scroll 34s linear infinite;
}
.ticker-group {
  display: flex;
  align-items: center;
  flex: none;
}
.t-item {
  display: inline-flex;
  align-items: baseline;
  gap: var(--app-space-2);
  padding: 9px 26px;
  color: var(--login-brand-muted);
  font-size: var(--app-font-size-table);
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.t-item em {
  color: var(--login-track);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-icon-size-xs);
  font-style: normal;
  letter-spacing: 0.1em;
}
.t-item b {
  font-family: var(--app-font-family-mono);
  font-weight: var(--app-font-weight-section);
  font-variant-numeric: tabular-nums;
}
.t-item b.up { color: var(--login-accent); }
.t-item b.down { color: var(--login-danger); }
@keyframes ticker-scroll { to { transform: translateX(-50%); } }

.login-brand-copy {
  position: absolute;
  z-index: 2;
  left: clamp(36px, 5cqw, 76px);
  bottom: 132px;
}
.login-brand-copy h1 {
  margin: 0 0 16px;
  color: var(--login-brand-text);
  font-family: 'Songti SC', STSong, 'SimSun', serif;
  font-size: clamp(42px, 4.5cqw, 70px);
  font-weight: var(--app-font-weight-section);
  letter-spacing: 0.02em;
  line-height: 1.18;
}
.login-brand-copy h1 em { color: var(--login-brand-accent); font-style: normal; }
.login-brand-copy p {
  margin: 0;
  color: var(--login-brand-sub);
  font-size: var(--app-font-size-body);
  letter-spacing: 0.06em;
}
/* 品牌能力卖点：挂在「复盘啦」字标下方，与左下主视觉分离，避免扎堆 */
.login-brand-points {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.login-brand-points li {
  position: relative;
  padding-left: 18px;
  color: var(--login-brand-muted);
  font-size: var(--app-font-size-table);
  letter-spacing: 0.08em;
}
.login-brand-points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 8px;
  height: 8px;
  border: 1px solid var(--login-track);
  border-radius: 50%;
  transform: translateY(-50%);
  box-shadow: inset 0 0 0 2px var(--login-card-opaque-bg);
  background: var(--login-accent);
}

.login-auth {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  padding: 72px clamp(34px, 4cqw, 64px) 48px;
  overflow-y: auto;
  background:
    radial-gradient(circle at 85% 0, color-mix(in srgb, var(--login-accent) 12%, transparent), transparent 28%),
    var(--login-page-bg);
}
.login-controls {
  position: absolute;
  z-index: 2;
  top: 28px;
  right: 32px;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.login-theme {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid var(--login-border);
  background: var(--login-toggle-bg);
  color: var(--login-text-sub);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.2s, color 0.2s, transform 0.2s;
}
.login-preset {
  height: 38px;
  padding: 0 13px;
  border: 1px solid var(--login-border);
  border-radius: 999px;
  background: var(--login-toggle-bg);
  color: var(--login-text-sub);
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
  cursor: pointer;
  font-size: var(--app-font-size-micro);
  letter-spacing: .08em;
}
.login-preset i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--login-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--login-accent) 13%, transparent);
}
.login-preset:hover { color: var(--login-text); border-color: var(--login-accent); }
.login-theme:hover { color: var(--login-accent); border-color: var(--login-accent); transform: rotate(8deg); }
.login-theme:focus-visible,
.login-preset:focus-visible,
.login-tab:focus-visible,
.login-link:focus-visible,
.login-primary:focus-visible { outline: 2px solid var(--login-accent); outline-offset: 3px; }
.login-card {
  position: relative;
  width: 100%;
  max-width: 480px;
  margin: auto;
  padding: 36px 38px 30px;
  border: 1px solid var(--login-card-edge);
  border-radius: 20px;
  background: var(--login-card-bg);
  box-shadow: 0 30px 80px var(--login-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.38);
  backdrop-filter: blur(18px);
}
.login-card::before {
  content: '';
  position: absolute;
  top: -1px;
  left: 36px;
  width: 76px;
  height: 2px;
  background: linear-gradient(90deg, var(--login-accent), transparent);
}
.login-card-title h2 {
  margin: 0 0 6px;
  color: var(--login-text);
  font-family: 'Songti SC', STSong, 'SimSun', serif;
  font-size: 29px;
  font-weight: var(--app-font-weight-section);
  letter-spacing: 0.04em;
}
.login-card-title p { margin: 0; color: var(--login-text-muted); font-size: var(--app-font-size-body); }
.login-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--app-space-1);
  margin: 26px 0 22px;
  padding: 4px;
  border: 1px solid var(--login-divider);
  border-radius: 10px;
  background: var(--app-surface-container);
}
.login-tab {
  height: 36px;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--login-text-muted);
  font: inherit;
  font-size: var(--app-font-size-body);
  cursor: pointer;
  transition: background 0.2s, color 0.2s, box-shadow 0.2s;
}
.login-tab.active {
  color: var(--login-text);
  background: var(--login-input-bg);
  box-shadow: 0 3px 12px rgba(32, 50, 60, 0.08);
  font-weight: var(--app-font-weight-section);
}
.login-field-block {
  margin-bottom: 13px;
}
.login-field {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  height: 60px;
  padding: 18px 14px 0;
  border: 1px solid var(--login-border);
  border-radius: 10px;
  background: var(--login-input-bg);
  color: var(--login-text-muted);
  font-size: var(--app-font-size-body);
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.login-field:focus-within {
  border-color: var(--login-border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--login-accent) 13%, transparent);
  background: var(--app-surface-control);
}
.is-dark .login-field:focus-within { background: var(--login-input-bg); }
/* 错误态：红边 + 红聚焦环，与 field-error 文案配合就地报错 */
.login-field.is-error {
  border-color: var(--login-danger);
}
.login-field.is-error:focus-within {
  border-color: var(--login-danger);
  box-shadow: 0 0 0 3px var(--login-danger-ring);
}
.login-field.is-error .field-label { color: var(--login-danger); }
.field-error {
  margin: 6px 2px 0;
  color: var(--login-danger);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-compact);
}
.field-hint {
  margin: 6px 2px 0;
  color: var(--login-success);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-compact);
}
/* 不归属单字段的整体错误（如账密不匹配/锁定），展示在提交按钮上方 */
.login-form-error {
  margin: 2px 0 0;
  padding: 9px 12px;
  border: 1px solid var(--app-border-danger);
  border-radius: 9px;
  background: var(--login-danger-bg);
  color: var(--login-danger);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-comfy);
}
.field-label {
  position: absolute;
  top: 6px;
  left: 40px;
  color: var(--login-text-muted);
  font-family: var(--app-font-family-base);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
  letter-spacing: 0.04em;
}
.login-field svg {
  flex: none;
  opacity: 0.8;
}
.login-field input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--login-text);
  font-size: var(--app-font-size-body);
  line-height: var(--app-line-height-table);
}
.login-field input:-webkit-autofill,
.login-field input:-webkit-autofill:hover,
.login-field input:-webkit-autofill:focus,
.login-field input:-webkit-autofill:active {
  -webkit-text-fill-color: var(--login-text);
  caret-color: var(--login-text);
  -webkit-box-shadow: 0 0 0 1000px transparent inset;
  -webkit-background-clip: text;
  transition: background-color 9999s ease-out 0s;
}
.login-field .eye {
  cursor: pointer;
}
.login-emailcode .send {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  color: var(--login-accent);
  font-size: var(--app-font-size-table);
  cursor: pointer;
  white-space: nowrap;
}
.login-emailcode .send.disabled {
  color: var(--login-text-muted);
  cursor: not-allowed;
}
.send-spinner {
  width: 12px;
  height: 12px;
  border: 1.5px solid var(--app-border-default);
  border-top-color: var(--login-accent);
  border-radius: 50%;
  animation: login-spin 0.7s linear infinite;
}
@keyframes login-spin { to { transform: rotate(360deg); } }
.login-captcha-row {
  display: flex;
  gap: var(--app-space-2);
}
.login-captcha-row .login-field {
  flex: 1;
  margin-bottom: 0;
  border-style: dashed;
  border-color: var(--login-border-dash);
}
.login-captcha-img {
  width: 104px;
  height: 60px;
  border-radius: 10px;
  overflow: hidden;
  background: var(--login-captcha-bg);
  border: 1px solid var(--login-border);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex: none;
}
.login-captcha-img :deep(svg) {
  width: 100%;
  height: 100%;
}
.login-primary {
  width: 100%;
  height: 48px;
  margin-top: 10px;
  border: 1px solid var(--login-accent-strong);
  border-radius: 10px;
  background: linear-gradient(135deg, var(--login-accent), var(--login-accent-strong));
  color: var(--login-accent-text);
  box-shadow: 0 10px 24px color-mix(in srgb, var(--login-accent) 25%, transparent);
  font-size: var(--app-font-size-body);
  font-weight: var(--app-font-weight-section);
  cursor: pointer;
  letter-spacing: 0.16em;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s, filter 0.2s, box-shadow 0.2s;
}
.login-primary:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.06); box-shadow: 0 13px 30px color-mix(in srgb, var(--login-accent) 32%, transparent); }
.login-primary:active:not(:disabled) { transform: translateY(0); }
.login-primary:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.login-rowbetween {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  font-size: var(--app-font-size-caption);
}
.login-rowend {
  justify-content: flex-end;
}
.login-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--login-accent-readable);
  font: inherit;
  cursor: pointer;
}
.login-link:hover { color: var(--login-accent); }
.login-security {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--login-text-muted);
}
.login-security i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--login-success);
  box-shadow: 0 0 0 3px rgba(67, 164, 122, 0.1);
}
.login-footnote {
  margin-top: 27px;
  padding-top: 18px;
  border-top: 1px solid var(--login-divider);
  color: var(--login-text-muted);
  font-size: var(--app-font-size-caption);
  letter-spacing: 0.1em;
  text-align: center;
}

@keyframes track-flow { to { stroke-dashoffset: -160; } }

@container app-viewport (max-width: 980px) {
  .login-shell {
    grid-template-columns: 1fr;
  }
  .login-brand {
    position: absolute;
    inset: 0;
    padding: 24px;
  }
  .login-brand::after { display: none; }
  .login-brand-head { align-items: flex-start; }
  .login-brand-copy,
  .login-brand-points,
  .market-readout,
  .market-ticker { display: none; }
  .market-stage { inset: 26% -35% 0 -20%; opacity: 0.38; }
  .login-auth {
    z-index: 2;
    padding: 92px 20px 30px;
    background: var(--login-page-bg);
  }
  .login-card { max-width: 430px; }
  .login-controls {
    position: fixed;
    top: 26px;
    right: 24px;
  }
  .login-theme,
  .login-preset {
    color: var(--login-text-sub);
    border-color: var(--login-border);
    background: var(--login-toggle-bg);
  }
}

@container app-viewport (max-width: 520px) {
  .login-brand { padding: 18px; }
  .login-auth { padding: 80px 12px 14px; }
  .login-card {
    padding: 28px 20px 24px;
    border-radius: 16px;
  }
  .login-card-title h2 { font-size: var(--app-font-size-kpi-lg); }
  .login-controls { top: 20px; right: 18px; }
}

@container app-viewport (max-height: 720px) and (min-width: 981px) {
  .login-auth { align-items: flex-start; padding-top: 48px; }
  .login-card { padding-top: 28px; padding-bottom: 24px; }
  .login-tabs { margin-top: 18px; margin-bottom: 16px; }
  .login-footnote { margin-top: 18px; padding-top: 14px; }
  .login-brand-copy { bottom: 92px; }
  .login-brand-points { display: none; }
  .market-readout { transform: scale(0.92); transform-origin: left top; }
}

@media (prefers-reduced-motion: reduce) {
  .market-track-line { animation: none; }
  .market-ticker-track { animation: none; }
  .send-spinner { animation-duration: 1.6s; }
  .login-theme,
  .login-primary { transition: none; }
}

@supports not (backdrop-filter: blur(18px)) {
  .login-card { background: var(--login-card-opaque-bg); }
}

@media (forced-colors: active) {
  .login-card,
  .login-field,
  .login-tabs { border: 1px solid CanvasText; }
  .login-security i { background: Highlight; }
}

@container app-viewport (max-width: 360px) {
  .login-card { padding-inline: 16px; }
  .login-captcha-img { width: 92px; }
  .login-rowbetween { gap: var(--app-space-2); }
  .login-footnote { letter-spacing: 0.04em; }
}

@container app-viewport (max-height: 620px) and (max-width: 980px) {
  .login-auth { align-items: flex-start; }
  .login-card { margin-top: 0; }
}

@media print {
  .login-theme { display: none; }
}

@media (hover: none) {
  .login-primary:hover:not(:disabled),
  .login-theme:hover { transform: none; }
}

@media (prefers-contrast: more) {
  .login-field,
  .login-tabs { border-color: var(--login-text-sub); }
}

</style>

<script setup lang="ts">
// 登录 / 注册页：金融科技视觉与明暗双主题，认证流程由公开配置动态控制。
// 全屏独立壳（App.vue 按 meta.fullscreen 脱离主框架单独渲染），不套用布局 archetype、不走 LayoutHost。
// 契约：用 position:fixed;inset:0 全屏（禁 vh 高度、禁手写 .v-page/.v-grow，过 layout-contract.spec.ts）。
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useTheme, toggleTheme } from '@/composables/useTheme'
import { useLayoutPreset } from '@/layout'
import { useAuthStore } from '@/stores/auth'
import { getCaptcha, getPublicConfig, sendEmailCode } from '@/api/auth'
import BrandMark from '@/components/BrandMark.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const { isDark } = useTheme()
const { activePresetKey, options: presetOptions, setLayoutPreset } = useLayoutPreset()
const activePresetLabel = computed(() =>
  presetOptions.value.find((option) => option.value === activePresetKey.value)?.label ?? '晨昏')

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

// 图形验证码：后端启用即在登录页展示；登录失败后刷新，避免复用已消费的验证码。
const captchaId = ref('')
const captchaSvg = ref('')
const needCaptcha = ref(false)
const loginFails = ref(0)

// 邮箱验证码发送倒计时（秒）
const emailCountdown = ref(0)
let emailTimer: ReturnType<typeof setInterval> | undefined

async function loadPublicConfig(syncCaptcha = true) {
  try {
    const c = await getPublicConfig()
    cfg.requireEmailCode = c.require_email_code
    cfg.loginCaptchaEnabled = c.login_captcha_enabled
    cfg.captchaAfterFails = c.captcha_after_fails
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
  if (!form.account || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  if (needCaptcha.value && !form.captchaCode) {
    ElMessage.warning('请输入图形验证码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.account.trim(), form.password, {
      captchaId: needCaptcha.value ? captchaId.value : undefined,
      captchaCode: needCaptcha.value ? form.captchaCode.trim() : undefined,
    })
    const redirect = (route.query.redirect as string) || '/'
    await router.replace(redirect)
  } catch (error) {
    // 登录失败：错误提示由拦截器统一弹出；累计失败达阈值(captchaAfterFails)且后端启用才显示图形码
    const msg = String((error as { response?: { data?: { msg?: string } } })?.response?.data?.msg ?? '')
    form.captchaCode = ''
    if (msg.includes('图形验证码')) {
      await refreshCaptcha()
      return
    }
    loginFails.value += 1
    if (needCaptcha.value || (cfg.loginCaptchaEnabled && loginFails.value >= cfg.captchaAfterFails)) {
      await refreshCaptcha()
    }
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  if (!form.account || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  if (form.password !== form.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  if (cfg.requireEmailCode && (!form.email || !form.emailCode)) {
    ElMessage.warning('请填写邮箱与邮箱验证码')
    return
  }
  loading.value = true
  try {
    await auth.register({
      account: form.account.trim(),
      password: form.password,
      email: form.email.trim() || undefined,
      email_code: form.emailCode.trim() || undefined,
    })
    await router.replace('/') // 注册后已自动登录
  } catch {
    // 错误提示由拦截器统一弹出
  } finally {
    loading.value = false
  }
}

async function onSendEmailCode() {
  if (!form.email) {
    ElMessage.warning('请先填写邮箱')
    return
  }
  if (emailCountdown.value > 0) return
  try {
    await sendEmailCode(form.email.trim())
    ElMessage.success('验证码已发送，请查收邮箱')
    emailCountdown.value = 60
    emailTimer = setInterval(() => {
      emailCountdown.value -= 1
      if (emailCountdown.value <= 0 && emailTimer) clearInterval(emailTimer)
    }, 1000)
  } catch {
    // 发送失败（限流等）由拦截器提示
  }
}

function onSubmit() {
  return mode.value === 'login' ? onLogin() : onRegister()
}
</script>

<template>
  <div
    class="login-shell"
    :class="[`preset-${activePresetKey}`, { 'is-register': mode === 'register', 'is-dark': isDark }]"
  >
    <section class="login-brand">
      <header class="login-brand-head">
        <div class="login-logo">
          <BrandMark variant="login" :tone="isDark ? 'dark' : 'light'" />
        </div>
        <div class="login-system-state"><span />SYSTEM ONLINE</div>
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
          </defs>
          <path class="market-track-shadow" d="M-20 350C80 334 128 366 205 320C284 273 324 305 390 268C466 226 497 265 558 204C614 148 675 193 733 126C782 70 832 92 920 30" />
          <path class="market-track-line" d="M-20 350C80 334 128 366 205 320C284 273 324 305 390 268C466 226 497 265 558 204C614 148 675 193 733 126C782 70 832 92 920 30" />
          <circle class="market-track-node node-one" cx="390" cy="268" r="5" />
          <circle class="market-track-node node-two" cx="558" cy="204" r="5" />
          <circle class="market-track-node node-three" cx="733" cy="126" r="7" />
        </svg>
        <span class="market-index index-one">SH · 000001</span>
        <span class="market-index index-two">TREND · LEADER</span>
        <span class="market-index index-three">EOD · SIGNAL</span>
      </div>

      <div class="login-brand-copy">
        <div class="login-eyebrow"><span>MARKET INTELLIGENCE</span><i /></div>
        <h1>看见趋势，<br /><em>先于共识。</em></h1>
        <p>为趋势交易者构建的每日复盘与龙头研究系统。</p>
      </div>

      <footer class="login-brandmeta">
        <span>沪深市场</span><i />
        <span>EOD 研究</span><i />
        <span>点时回测</span>
      </footer>
    </section>

    <section class="login-auth">
      <div class="login-controls">
        <button class="login-preset" type="button" :aria-label="`切换研究空间，当前${activePresetLabel}`" @click="cyclePreset">
          <i /><span>{{ activePresetLabel }}</span>
        </button>
        <button class="login-theme" type="button" aria-label="切换主题" title="切换黑/白主题" @click="toggleTheme">
          <svg v-if="isDark" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4" />
            <circle cx="12" cy="12" r="4" />
          </svg>
          <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" />
          </svg>
        </button>
      </div>

      <div class="login-card">
        <div class="login-card-kicker"><span>PRIVATE ACCESS</span><i>01</i></div>
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

        <label class="login-field">
          <span class="field-label">ACCOUNT</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 4-6 8-6s8 2 8 6" />
          </svg>
          <input v-model="form.account" type="text" :placeholder="mode === 'register' ? '账号' : '账号 / 邮箱'"
                 autocomplete="username" @keyup.enter="onSubmit" />
        </label>

        <label class="login-field">
          <span class="field-label">PASSWORD</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
          </svg>
          <input v-model="form.password" :type="showPwd ? 'text' : 'password'" placeholder="密码"
                 autocomplete="current-password" @keyup.enter="onSubmit" />
          <svg class="eye" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" @click="showPwd = !showPwd">
            <path v-if="showPwd" d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z" />
            <path v-else d="M3 3l18 18M10.6 5.1A9.6 9.6 0 0 1 12 5c6 0 10 7 10 7a17 17 0 0 1-3.3 3.9M6.6 6.6A17 17 0 0 0 2 12s4 7 10 7a9.6 9.6 0 0 0 3.4-.6" />
            <circle v-if="showPwd" cx="12" cy="12" r="3" />
          </svg>
        </label>

        <label v-if="mode === 'register'" class="login-field">
          <span class="field-label">CONFIRM</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
          </svg>
          <input v-model="form.confirm" type="password" placeholder="确认密码" autocomplete="new-password"
                 @keyup.enter="onSubmit" />
        </label>

        <label v-if="mode === 'register'" class="login-field">
          <span class="field-label">EMAIL</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" />
          </svg>
          <input v-model="form.email" type="email" placeholder="邮箱" autocomplete="email"
                 @keyup.enter="onSubmit" />
        </label>

        <label v-if="mode === 'register' && cfg.requireEmailCode" class="login-field login-emailcode">
          <span class="field-label">VERIFY</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" />
          </svg>
          <input v-model="form.emailCode" type="text" placeholder="邮箱验证码" @keyup.enter="onSubmit" />
          <span class="send" :class="{ disabled: emailCountdown > 0 }" @click="onSendEmailCode">
            {{ emailCountdown > 0 ? `${emailCountdown}s 后重发` : '发送验证码' }}
          </span>
        </label>

        <template v-if="mode === 'login' && needCaptcha">
          <div class="login-captcha-row">
            <label class="login-field dashed">
              <span class="field-label">CAPTCHA</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 3v18M3 12h18" />
              </svg>
              <input v-model="form.captchaCode" type="text" placeholder="图形验证码" @keyup.enter="onSubmit" />
            </label>
            <div class="login-captcha-img" title="点击刷新" v-html="captchaSvg" @click="refreshCaptcha" />
          </div>
        </template>

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
  --login-page-bg: #edf1f4;
  --login-panel-bg: #0b1c2b;
  --login-panel-deep: #06131f;
  --login-grid: rgba(126, 159, 179, 0.11);
  --login-card-bg: rgba(250, 252, 253, 0.86);
  --login-card-edge: rgba(255, 255, 255, 0.92);
  --login-border: #cbd4da;
  --login-border-focus: #9a7a43;
  --login-border-dash: #b8c4cb;
  --login-input-bg: rgba(255, 255, 255, 0.6);
  --login-text: #112533;
  --login-text-sub: #526773;
  --login-text-muted: #82939c;
  --login-accent: #b69254;
  --login-accent-strong: #876a3a;
  --login-accent-text: #fffdf8;
  --login-captcha-bg: #e9eef1;
  --login-toggle-bg: rgba(255, 255, 255, 0.58);
  --login-divider: rgba(76, 99, 111, 0.18);
  --login-shadow: rgba(16, 35, 46, 0.16);
  --login-panel-glow: rgba(39, 105, 126, 0.3);
  --login-brand-text: #f1f5f6;
  --login-brand-accent: #d2b579;
  --login-brand-sub: rgba(195, 214, 220, 0.62);
  --login-brand-muted: rgba(181, 204, 212, 0.42);
  --login-track: #c5a466;
  --login-track-glow: rgba(197, 164, 102, 0.22);
  --login-logo-start: #d0ab68;
  --login-logo-end: #9a7137;

  position: fixed;
  inset: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.38fr) minmax(430px, 0.82fr);
  background: var(--login-page-bg);
  color: var(--login-text);
  font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
  transition: background 0.3s, color 0.3s;
}
.login-shell.is-dark {
  --login-page-bg: #07131d;
  --login-card-bg: rgba(10, 27, 39, 0.9);
  --login-card-edge: rgba(142, 168, 181, 0.18);
  --login-border: #29404e;
  --login-border-focus: #c9a669;
  --login-border-dash: #36505e;
  --login-input-bg: rgba(4, 18, 28, 0.58);
  --login-text: #edf3f5;
  --login-text-sub: #9eb0b9;
  --login-text-muted: #657b87;
  --login-accent: #c5a466;
  --login-accent-strong: #a5834c;
  --login-captcha-bg: #0d2433;
  --login-toggle-bg: rgba(12, 33, 46, 0.78);
  --login-divider: rgba(139, 165, 178, 0.16);
  --login-shadow: rgba(0, 0, 0, 0.38);
}

.login-shell.preset-daylight {
  --login-page-bg: #edf3f5;
  --login-panel-bg: #e7eff1;
  --login-panel-deep: #d7e5e9;
  --login-grid: rgba(50, 101, 120, 0.1);
  --login-card-bg: rgba(251, 253, 253, 0.92);
  --login-border-focus: #2c708d;
  --login-accent: #397f99;
  --login-accent-strong: #245f78;
  --login-panel-glow: rgba(72, 137, 158, 0.18);
  --login-brand-text: #163443;
  --login-brand-accent: #2c708d;
  --login-brand-sub: rgba(46, 77, 89, 0.68);
  --login-brand-muted: rgba(54, 84, 96, 0.48);
  --login-track: #3b86a0;
  --login-track-glow: rgba(59, 134, 160, 0.2);
  --login-logo-start: #4b91a8;
  --login-logo-end: #286a84;
}

.login-shell.preset-daylight.is-dark {
  --login-page-bg: #18252c;
  --login-panel-bg: #1d3039;
  --login-panel-deep: #12242d;
  --login-card-bg: rgba(34, 50, 58, 0.92);
  --login-card-edge: rgba(156, 184, 195, 0.2);
  --login-border: #3c525c;
  --login-input-bg: rgba(255, 255, 255, 0.035);
  --login-text: #f5f9fa;
  --login-text-sub: #d1dfe4;
  --login-text-muted: #92a8b1;
}

.login-shell.preset-nocturne {
  --login-page-bg: #e8eef1;
  --login-panel-bg: #0a202c;
  --login-panel-deep: #061620;
  --login-card-bg: rgba(248, 250, 251, 0.92);
  --login-border-focus: #227f9d;
  --login-accent: #2c88a5;
  --login-accent-strong: #17667f;
  --login-panel-glow: rgba(41, 132, 159, 0.28);
  --login-brand-accent: #83c6d8;
  --login-track: #62bad2;
  --login-track-glow: rgba(98, 186, 210, 0.22);
  --login-logo-start: #69bed4;
  --login-logo-end: #2d819b;
}

.login-shell.preset-nocturne.is-dark {
  --login-page-bg: #071721;
  --login-panel-bg: #071b25;
  --login-panel-deep: #04131b;
  --login-card-bg: rgba(13, 34, 46, 0.94);
  --login-card-edge: rgba(132, 171, 187, 0.2);
  --login-border: #294a58;
  --login-border-focus: #62bad2;
  --login-input-bg: rgba(255, 255, 255, 0.035);
  --login-text: #f2f7f8;
  --login-text-sub: #bfd0d7;
  --login-text-muted: #8199a4;
  --login-accent: #62bad2;
  --login-accent-strong: #398ca7;
}

.login-brand {
  position: relative;
  min-width: 0;
  padding: 38px clamp(36px, 5vw, 76px) 34px;
  background:
    radial-gradient(circle at 72% 46%, var(--login-panel-glow), transparent 28%),
    linear-gradient(142deg, var(--login-panel-bg), var(--login-panel-deep));
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
  align-items: center;
  justify-content: space-between;
}
.login-logo {
  display: flex;
  align-items: center;
  --brand-word: var(--login-brand-text);
  --brand-word-stroke: rgba(11, 28, 43, 0.28);
  --brand-icon-start: var(--login-logo-start);
  --brand-icon-end: var(--login-logo-end);
  --shell-accent-soft: color-mix(in srgb, var(--login-track) 20%, transparent);
}
.login-system-state {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--login-brand-muted);
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 10px;
  letter-spacing: 0.14em;
}
.login-system-state span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #66c4a0;
  box-shadow: 0 0 10px rgba(102, 196, 160, 0.8);
}
.market-stage {
  position: absolute;
  z-index: 1;
  inset: 18% -4% 12% 7%;
}
.market-orbit {
  position: absolute;
  border-radius: 50%;
  border: 1px solid rgba(147, 176, 187, 0.1);
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
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 9px;
  letter-spacing: 0.12em;
}
.index-one { left: 38%; top: 64%; }
.index-two { left: 58%; top: 43%; }
.index-three { right: 7%; top: 19%; }
.login-brand-copy {
  position: absolute;
  z-index: 2;
  left: clamp(36px, 5vw, 76px);
  bottom: 112px;
}
.login-eyebrow {
  display: flex;
  align-items: center;
  gap: 15px;
  color: var(--login-track);
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 10px;
  letter-spacing: 0.18em;
}
.login-eyebrow i { width: 50px; height: 1px; background: color-mix(in srgb, var(--login-track) 56%, transparent); }
.login-brand-copy h1 {
  margin: 18px 0 16px;
  color: var(--login-brand-text);
  font-family: 'Songti SC', STSong, 'SimSun', serif;
  font-size: clamp(42px, 4.5vw, 70px);
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1.18;
}
.login-brand-copy h1 em { color: var(--login-brand-accent); font-style: normal; }
.login-brand-copy p {
  margin: 0;
  color: var(--login-brand-sub);
  font-size: 14px;
  letter-spacing: 0.06em;
}
.login-brandmeta {
  position: absolute;
  z-index: 3;
  left: clamp(36px, 5vw, 76px);
  right: clamp(36px, 5vw, 76px);
  bottom: 32px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--login-brand-muted);
  font-size: 11px;
  letter-spacing: 0.12em;
}
.login-brandmeta i { width: 3px; height: 3px; border-radius: 50%; background: var(--login-track); }

.login-auth {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  padding: 72px clamp(34px, 4vw, 64px) 48px;
  overflow-y: auto;
  background:
    radial-gradient(circle at 85% 0, rgba(182, 146, 84, 0.13), transparent 28%),
    var(--login-page-bg);
}
.login-controls {
  position: absolute;
  z-index: 2;
  top: 28px;
  right: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
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
  gap: 7px;
  cursor: pointer;
  font-size: 11px;
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
  max-width: 430px;
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
.login-card-kicker {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--login-accent-strong);
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 9px;
  letter-spacing: 0.18em;
}
.login-card-kicker i { color: var(--login-text-muted); font-style: normal; }
.login-card-title h2 {
  margin: 18px 0 6px;
  color: var(--login-text);
  font-family: 'Songti SC', STSong, 'SimSun', serif;
  font-size: 29px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.login-card-title p { margin: 0; color: var(--login-text-muted); font-size: 13px; }
.login-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin: 26px 0 22px;
  padding: 4px;
  border: 1px solid var(--login-divider);
  border-radius: 10px;
  background: rgba(112, 132, 142, 0.08);
}
.login-tab {
  height: 36px;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--login-text-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, box-shadow 0.2s;
}
.login-tab.active {
  color: var(--login-text);
  background: var(--login-input-bg);
  box-shadow: 0 3px 12px rgba(32, 50, 60, 0.08);
  font-weight: 650;
}
.login-field {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 54px;
  padding: 12px 14px 0;
  margin-bottom: 13px;
  border: 1px solid var(--login-border);
  border-radius: 10px;
  background: var(--login-input-bg);
  color: var(--login-text-muted);
  font-size: 14px;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.login-field:focus-within {
  border-color: var(--login-border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--login-accent) 13%, transparent);
  background: color-mix(in srgb, var(--login-input-bg) 82%, white 18%);
}
.is-dark .login-field:focus-within { background: var(--login-input-bg); }
.field-label {
  position: absolute;
  top: 7px;
  left: 40px;
  color: var(--login-text-muted);
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 8px;
  letter-spacing: 0.12em;
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
  font-size: 14px;
  line-height: 20px;
}
.login-field input::placeholder {
  color: var(--login-text-muted);
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
  color: var(--login-accent);
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.login-emailcode .send.disabled {
  color: var(--login-text-muted);
  cursor: not-allowed;
}
.login-captcha-row {
  display: flex;
  gap: 10px;
  margin-bottom: 8px;
}
.login-captcha-row .login-field {
  flex: 1;
  margin-bottom: 0;
  border-style: dashed;
  border-color: var(--login-border-dash);
}
.login-captcha-img {
  width: 104px;
  height: 54px;
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
  border: 1px solid color-mix(in srgb, var(--login-accent) 68%, black 32%);
  border-radius: 10px;
  background: linear-gradient(135deg, var(--login-accent), var(--login-accent-strong));
  color: var(--login-accent-text);
  box-shadow: 0 10px 24px color-mix(in srgb, var(--login-accent) 25%, transparent);
  font-size: 14px;
  font-weight: 650;
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
  font-size: 12px;
}
.login-rowend {
  justify-content: flex-end;
}
.login-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--login-accent-strong);
  font: inherit;
  cursor: pointer;
}
.login-link:hover { color: var(--login-accent); }
.login-security {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--login-text-muted);
}
.login-security i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #43a47a;
  box-shadow: 0 0 0 3px rgba(67, 164, 122, 0.1);
}
.login-footnote {
  margin-top: 27px;
  padding-top: 18px;
  border-top: 1px solid var(--login-divider);
  color: var(--login-text-muted);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-align: center;
}

@keyframes track-flow { to { stroke-dashoffset: -160; } }

@media (max-width: 980px) {
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
  .login-system-state { display: none; }
  .login-brand-copy,
  .login-brandmeta { display: none; }
  .market-stage { inset: 26% -35% 0 -20%; opacity: 0.38; }
  .login-auth {
    z-index: 2;
    padding: 92px 20px 30px;
    background: linear-gradient(rgba(4, 17, 27, 0.12), rgba(4, 17, 27, 0.5));
  }
  .login-card { max-width: 430px; }
  .login-controls {
    position: fixed;
    top: 26px;
    right: 24px;
  }
  .login-theme,
  .login-preset {
    color: #d9e5e9;
    border-color: rgba(220, 232, 236, 0.25);
    background: rgba(7, 27, 39, 0.62);
  }
}

@media (max-width: 520px) {
  .login-brand { padding: 18px; }
  .login-logo :deep(.brand-mark) { width: 154px; height: auto; }
  .login-auth { padding: 80px 12px 14px; }
  .login-card {
    padding: 28px 20px 24px;
    border-radius: 16px;
  }
  .login-card-title h2 { font-size: 26px; }
  .login-controls { top: 20px; right: 18px; }
}

@media (max-height: 720px) and (min-width: 981px) {
  .login-auth { align-items: flex-start; padding-top: 48px; }
  .login-card { padding-top: 28px; padding-bottom: 24px; }
  .login-tabs { margin-top: 18px; margin-bottom: 16px; }
  .login-footnote { margin-top: 18px; padding-top: 14px; }
  .login-brand-copy { bottom: 88px; }
}

@media (prefers-reduced-motion: reduce) {
  .market-track-line { animation: none; }
  .login-theme,
  .login-primary { transition: none; }
}

@supports not (backdrop-filter: blur(18px)) {
  .login-card { background: var(--login-page-bg); }
}

@media (forced-colors: active) {
  .login-card,
  .login-field,
  .login-tabs { border: 1px solid CanvasText; }
  .login-security i,
  .login-system-state span { background: Highlight; }
}

@media (max-width: 360px) {
  .login-card { padding-inline: 16px; }
  .login-captcha-img { width: 92px; }
  .login-rowbetween { gap: 10px; }
  .login-footnote { letter-spacing: 0.04em; }
}

@media (max-height: 620px) and (max-width: 980px) {
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

@media (max-width: 980px) and (prefers-color-scheme: light) {
  .login-shell:not(.is-dark) .login-card {
    background: rgba(248, 251, 252, 0.92);
  }
}
</style>

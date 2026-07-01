<script setup lang="ts">
// 登录 / 注册页（stage2·T8）：科技风 + 黑白双主题，视觉原型见 agent-works/multi-tenant-rbac/prototypes/login.html。
// 全屏独立壳（App.vue 按 meta.fullscreen 脱离主框架单独渲染），不套用布局 archetype、不走 LayoutHost。
// 契约：用 position:fixed;inset:0 全屏（禁 vh 高度、禁手写 .v-page/.v-grow，过 layout-contract.spec.ts）。
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useTheme, toggleTheme } from '@/composables/useTheme'
import { useAuthStore } from '@/stores/auth'
import { getCaptcha, getPublicConfig, sendEmailCode } from '@/api/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const { isDark } = useTheme()

type Mode = 'login' | 'register'
const mode = ref<Mode>('login')

// 公开配置（无需 token）：是否要邮箱验证码 / 是否启用图形验证码。挂载时拉取，失败用保守默认。
const cfg = reactive({ requireEmailCode: true, loginCaptchaEnabled: false })

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

// 图形验证码：仅当后端启用且本地已发生登录失败时出现（原型「登录失败达阈值后出现」）。
const captchaId = ref('')
const captchaSvg = ref('')
const needCaptcha = ref(false)
const loginFails = ref(0)

// 邮箱验证码发送倒计时（秒）
const emailCountdown = ref(0)
let emailTimer: ReturnType<typeof setInterval> | undefined

onMounted(async () => {
  try {
    const c = await getPublicConfig()
    cfg.requireEmailCode = c.require_email_code
    cfg.loginCaptchaEnabled = c.login_captcha_enabled
  } catch {
    // 公开配置拉取失败不阻断登录：保守保留默认（要邮箱码、不强制图形码）
  }
})

function setMode(m: Mode) {
  mode.value = m
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
    router.replace(redirect)
  } catch {
    // 登录失败：错误提示由拦截器统一弹出；累计失败，达阈值+后端启用则显示图形验证码
    loginFails.value += 1
    form.captchaCode = ''
    if (cfg.loginCaptchaEnabled) await refreshCaptcha()
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
    router.replace('/') // 注册后已自动登录
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
  <div class="login-shell" :class="{ 'is-register': mode === 'register', 'is-dark': isDark }">
    <!-- 左 · 品牌视觉区（科技风：动态网格 + 标语） -->
    <section class="login-brand">
      <div class="login-logo">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 18 L9 11 L13 14 L20 5" />
          <circle cx="9" cy="11" r="1.4" fill="currentColor" />
          <circle cx="13" cy="14" r="1.4" fill="currentColor" />
        </svg>
        复盘啦
      </div>
      <div class="login-sys">EOD 趋势龙头研究系统</div>
      <div class="login-pulse" aria-hidden="true" />
      <div class="login-tagline">数据驱动的<br />每日复盘</div>
      <div class="login-brandmeta"><span class="bar" /> 多租户 SaaS · v0.x</div>
    </section>

    <!-- 右 · 认证区 -->
    <section class="login-auth">
      <button class="login-theme" type="button" aria-label="切换主题" title="切换黑/白主题" @click="toggleTheme">
        <svg v-if="isDark" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4" />
          <circle cx="12" cy="12" r="4" />
        </svg>
        <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" />
        </svg>
      </button>

      <div class="login-card">
        <div class="login-tabs">
          <div class="login-tab" :class="{ active: mode === 'login' }" @click="setMode('login')">登录</div>
          <div class="login-tab" :class="{ active: mode === 'register' }" @click="setMode('register')">注册</div>
        </div>

        <!-- 账号 / 邮箱 -->
        <label class="login-field">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 4-6 8-6s8 2 8 6" />
          </svg>
          <input v-model="form.account" type="text" placeholder="账号 / 邮箱" autocomplete="username"
                 @keyup.enter="onSubmit" />
        </label>

        <!-- 密码 -->
        <label class="login-field">
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

        <!-- 确认密码（仅注册） -->
        <label v-if="mode === 'register'" class="login-field">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
          </svg>
          <input v-model="form.confirm" type="password" placeholder="确认密码" autocomplete="new-password"
                 @keyup.enter="onSubmit" />
        </label>

        <!-- 邮箱验证码（仅注册且后端要求） -->
        <label v-if="mode === 'register' && cfg.requireEmailCode" class="login-field login-emailcode">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" />
          </svg>
          <input v-model="form.emailCode" type="text" placeholder="邮箱验证码" @keyup.enter="onSubmit" />
          <span class="send" :class="{ disabled: emailCountdown > 0 }" @click="onSendEmailCode">
            {{ emailCountdown > 0 ? `${emailCountdown}s 后重发` : '发送验证码' }}
          </span>
        </label>

        <!-- 图形验证码（仅登录，后端启用且已失败后出现） -->
        <template v-if="mode === 'login' && needCaptcha">
          <div class="login-captcha-row">
            <label class="login-field dashed">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 3v18M3 12h18" />
              </svg>
              <input v-model="form.captchaCode" type="text" placeholder="图形验证码" @keyup.enter="onSubmit" />
            </label>
            <!-- 后端返回 SVG 字符串，点击刷新 -->
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
          <span class="login-link" title="占位，后续开放">忘记密码？</span>
          <span class="login-link" @click="setMode('register')">没有账号？去注册</span>
        </div>
        <div v-else class="login-rowbetween login-rowend">
          <span class="login-link" @click="setMode('login')">已有账号？去登录</span>
        </div>

        <!-- 第三方登录占位（R6：置灰 + 敬请期待） -->
        <div class="login-divider"><span class="line" />第三方登录（敬请期待）<span class="line" /></div>
        <div class="login-socials">
          <div class="login-social" title="手机登录（敬请期待）">手机</div>
          <div class="login-social" title="邮箱登录（敬请期待）">邮箱</div>
          <div class="login-social" title="微信登录（敬请期待）">微信</div>
          <div class="login-social" title="QQ 登录（敬请期待）">QQ</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* 黑白双主题：:root 语汇（浅色）挂在 .login-shell 上，html.dark 时整体覆盖为深色。
   对应视觉原型 prototypes/login.html 的 :root(浅) / [data-theme=dark](深)；前端切主题走 useTheme() 的 html.dark。 */
.login-shell {
  --login-page-bg: #ffffff;
  --login-panel-bg: #f3f7fc;
  --login-grid: #e6eef8;
  --login-card-bg: #ffffff;
  --login-border: #dbe5f0;
  --login-border-dash: #cdd9e8;
  --login-input-bg: #fafcfe;
  --login-text: #0c2c4f;
  --login-text-sub: #5b7799;
  --login-text-muted: #8aa3c2;
  --login-brand: #185fa5;
  --login-accent: #2f81f7;
  --login-accent-text: #ffffff;
  --login-captcha-bg: #eef4fb;
  --login-toggle-bg: #f3f7fc;
  --login-divider: #e2eaf3;

  position: fixed;
  inset: 0;
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  background: var(--login-page-bg);
  color: var(--login-text);
  font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
  transition: background 0.2s, color 0.2s;
}
/* 深色主题：以自身 .is-dark 类切换（绑定 useTheme 的 isDark），完全 scoped、不依赖祖先 html.dark 匹配 */
.login-shell.is-dark {
  --login-page-bg: #0b1220;
  --login-panel-bg: #0d1526;
  --login-grid: #15233f;
  --login-card-bg: #0b1220;
  --login-border: #24344f;
  --login-border-dash: #24344f;
  --login-input-bg: #0f1a2c;
  --login-text: #e6f0ff;
  --login-text-sub: #9db4d6;
  --login-text-muted: #5e779c;
  --login-brand: #5cc8ff;
  --login-accent: #2f81f7;
  --login-accent-text: #ffffff;
  --login-captcha-bg: #13233c;
  --login-toggle-bg: #111c30;
  --login-divider: #1c2942;
}

/* 左 · 品牌视觉区 */
.login-brand {
  position: relative;
  padding: 40px;
  background-color: var(--login-panel-bg);
  background-image:
    linear-gradient(var(--login-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--login-grid) 1px, transparent 1px);
  background-size: 28px 28px;
  border-right: 1px solid var(--login-divider);
  overflow: hidden;
}
.login-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: 600;
  color: var(--login-brand);
}
.login-sys {
  margin-top: 12px;
  color: var(--login-text-sub);
  font-size: 14px;
}
.login-pulse {
  position: absolute;
  right: -60px;
  top: 90px;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  border: 1px solid var(--login-grid);
  opacity: 0.6;
}
.login-pulse::after {
  content: '';
  position: absolute;
  inset: 40px;
  border-radius: 50%;
  border: 1px solid var(--login-grid);
}
.login-tagline {
  position: absolute;
  left: 40px;
  bottom: 84px;
  font-size: 26px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--login-text);
}
.login-brandmeta {
  position: absolute;
  left: 40px;
  bottom: 36px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--login-text-muted);
  font-size: 13px;
}
.login-brandmeta .bar {
  width: 28px;
  height: 3px;
  border-radius: 2px;
  background: var(--login-accent);
}

/* 右 · 认证区 */
.login-auth {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: var(--login-card-bg);
}
.login-theme {
  position: absolute;
  top: 24px;
  right: 28px;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1px solid var(--login-border);
  background: var(--login-toggle-bg);
  color: var(--login-text-sub);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-card {
  width: 100%;
  max-width: 380px;
}
.login-tabs {
  display: flex;
  gap: 24px;
  margin-bottom: 22px;
  font-size: 16px;
}
.login-tab {
  padding-bottom: 8px;
  color: var(--login-text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.login-tab.active {
  color: var(--login-text);
  font-weight: 600;
  border-bottom-color: var(--login-accent);
}
.login-field {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 42px;
  padding: 0 12px;
  margin-bottom: 14px;
  border: 1px solid var(--login-border);
  border-radius: 6px;
  background: var(--login-input-bg);
  color: var(--login-text-muted);
  font-size: 14px;
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
}
.login-field input::placeholder {
  color: var(--login-text-muted);
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
  margin-bottom: 6px;
}
.login-captcha-row .login-field {
  flex: 1;
  margin-bottom: 0;
  border-style: dashed;
  border-color: var(--login-border-dash);
}
.login-captcha-img {
  width: 104px;
  height: 42px;
  border-radius: 6px;
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
  height: 44px;
  margin-top: 8px;
  border: none;
  border-radius: 6px;
  background: var(--login-accent);
  color: var(--login-accent-text);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  letter-spacing: 4px;
  text-indent: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-primary:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.login-rowbetween {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  font-size: 13px;
}
.login-rowend {
  justify-content: flex-end;
}
.login-link {
  color: var(--login-text-sub);
  cursor: pointer;
}
.login-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--login-text-muted);
  font-size: 12px;
  margin: 22px 0 14px;
}
.login-divider .line {
  flex: 1;
  height: 1px;
  background: var(--login-divider);
}
.login-socials {
  display: flex;
  gap: 12px;
  justify-content: center;
}
.login-social {
  width: 44px;
  height: 44px;
  border-radius: 8px;
  border: 1px solid var(--login-border);
  background: var(--login-input-bg);
  color: var(--login-text-muted);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: not-allowed;
}

/* 窄屏退化：单列，品牌区收成顶部条 */
@media (max-width: 768px) {
  .login-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
  .login-brand {
    padding: 18px 24px;
  }
  .login-tagline,
  .login-brandmeta,
  .login-pulse,
  .login-sys {
    display: none;
  }
}
</style>

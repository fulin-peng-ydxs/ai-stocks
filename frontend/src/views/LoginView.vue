<script setup lang="ts">
// 登录页（stage2·T7 最小可用骨架）：账密登录 → 写登录态 → 回跳。
// 注：T8 将按 prototypes/login.html 科技风 + 黑白双主题重做布局；此处先打通登录闭环。
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const account = ref('')
const password = ref('')
const loading = ref(false)

async function onLogin() {
  if (!account.value || !password.value) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(account.value.trim(), password.value)
    const redirect = (route.query.redirect as string) || '/'
    router.replace(redirect)
  } catch {
    // 错误提示由 http 拦截器统一弹出（401/429 等）
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-shell">
    <div class="login-card">
      <h1 class="login-title">复盘啦 · 登录</h1>
      <el-input v-model="account" placeholder="账号 / 邮箱" size="large" class="login-field"
                @keyup.enter="onLogin" />
      <el-input v-model="password" type="password" placeholder="密码" size="large" show-password
                class="login-field" @keyup.enter="onLogin" />
      <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onLogin">
        登 录
      </el-button>
    </div>
  </div>
</template>

<style scoped>
/* 全屏壳：用 height:100% 继承链（html,body=100%），不用 vh，避免踩 layout-contract 契约红线 */
.login-shell {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-bg-color-page);
}
.login-card {
  width: 360px;
  max-width: 90%;
  padding: 32px;
  border: 1px solid var(--chrome-border);
  border-radius: 12px;
  background: var(--chrome-bg-soft);
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.login-title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 600;
  text-align: center;
  color: var(--chrome-text-strong);
}
.login-field,
.login-btn {
  width: 100%;
}
</style>

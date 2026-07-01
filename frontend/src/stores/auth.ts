// 登录态 store（多租户 RBAC stage2·T7）：token / 用户 / 租户 / 角色。
// 事实源持久化在 localStorage（authToken.ts），store 提供内存态 + 动作；刷新页自动 hydrate。
// 菜单/功能码本阶段为空（§4.7 兼容策略：SideMenu 仍用静态 menuConfig），阶段三填充消费。
import { defineStore } from 'pinia'
import {
  clearAuth,
  readAuth,
  writeAuth,
  type AuthSnapshot,
} from '@/api/authToken'
import * as authApi from '@/api/auth'

interface AuthState extends AuthSnapshot {
  menus: unknown[]
  permissions: string[]
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    ...readAuth(), // 首次使用即从 localStorage 恢复（等价 loadFromStorage）
    menus: [],
    permissions: [],
  }),

  getters: {
    isLoggedIn: (s): boolean => !!s.accessToken,
    displayName: (s): string => s.user?.account ?? '',
    tenantId: (s): string => s.tenant?.id ?? '',
  },

  actions: {
    _persist() {
      writeAuth({
        accessToken: this.accessToken,
        refreshToken: this.refreshToken,
        user: this.user,
        tenant: this.tenant,
        role: this.role,
      })
    },

    _applyLogin(data: authApi.LoginResult) {
      this.accessToken = data.access_token
      this.refreshToken = data.refresh_token
      this.user = {
        id: data.user.id, account: data.user.account,
        email: data.user.email, status: data.user.status,
      }
      this.tenant = { id: data.user.tenant_id }
      this.role = data.user.role
      this._persist()
    },

    async login(account: string, password: string,
                 opts: { captchaId?: string; captchaCode?: string } = {}) {
      const data = await authApi.login({
        account, password, captcha_id: opts.captchaId, captcha_code: opts.captchaCode,
      })
      this._applyLogin(data)
      return data
    },

    async register(payload: { account: string; password: string; email?: string; email_code?: string }) {
      const data = await authApi.register(payload)
      this._applyLogin(data)   // 注册后自动登录
      return data
    },

    async fetchMe() {
      const me = await authApi.getMe()
      this.user = me.user
      this.tenant = me.tenant
      this.role = me.role
      this.menus = me.menus
      this.permissions = me.permissions
      this._persist()
      return me
    },

    async logout() {
      try {
        await authApi.logout(this.refreshToken || undefined)
      } catch {
        // 退出接口失败也强制前端清态（token 已本地失效即可）
      }
      this.clearLocal()
    },

    clearLocal() {
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
      this.tenant = null
      this.role = ''
      this.menus = []
      this.permissions = []
      clearAuth()
    },
  },
})

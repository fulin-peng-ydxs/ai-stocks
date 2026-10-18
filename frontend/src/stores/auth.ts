// 登录态 store（多租户 RBAC stage2·T7 / stage3·T15）：token / 用户 / 租户 / 角色 / 菜单 / 功能码。
// 事实源持久化在 localStorage（authToken.ts），store 提供内存态 + 动作；刷新页自动 hydrate。
// 阶段三（T15）：menus/permissions 由 /me 填充——SideMenu 消费 menus（后端数据化，fail-closed，
// 加载失败显错误态而非回退静态全量菜单，故原 components/menuConfig.ts 已删除）；
// v-permission/路由守卫消费 permissions/menus。
import { defineStore } from 'pinia'
import {
  clearAuth,
  getRefreshToken,
  readAuth,
  writeAuth,
  type AuthSnapshot,
} from '@/api/authToken'
import * as authApi from '@/api/auth'
import { useStockSet } from '@/stores/stockSet'
import { collectMenuPaths, firstMenuPath, type MenuTreeNode } from '@/utils/permission'

// /me 拉取状态：SideMenu/守卫据此区分「加载中」与「加载失败」，失败时 fail-closed（不露全量菜单）。
export type MenusStatus = 'idle' | 'loading' | 'ready' | 'error'

interface AuthState extends AuthSnapshot {
  menus: MenuTreeNode[]
  permissions: string[]
  menusStatus: MenusStatus
}

// /me 去重：多处（守卫每次导航 + App 挂载）并发调用只发一次请求。非响应式，置于模块作用域。
let inflightMe: Promise<authApi.MeResult> | null = null

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    ...readAuth(), // 首次使用即从 localStorage 恢复（等价 loadFromStorage）
    menus: [],
    permissions: [],
    menusStatus: 'idle',
  }),

  getters: {
    isLoggedIn: (s): boolean => !!s.accessToken,
    displayName: (s): string => s.user?.account ?? '',
    tenantId: (s): string => s.tenant?.id ?? '',
    isSystem: (s): boolean => s.role === 'system',
    // 授权可导航路由路径集合（守卫用）；首个叶子作为无权时安全落点。
    menuRoutePaths: (s): string[] => collectMenuPaths(s.menus),
    firstMenuPath: (s): string => firstMenuPath(s.menus),
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
      // 登录可能在同一 Tab 切换身份，禁止复用上一身份的列表/分组现场。
      useStockSet().resetSession(true)
      this.accessToken = data.access_token
      this.refreshToken = data.refresh_token
      this.user = {
        id: data.user.id, account: data.user.account,
        email: data.user.email, status: data.user.status,
      }
      this.tenant = { id: data.user.tenant_id }
      this.role = data.user.role
      this.menus = []
      this.permissions = []
      this.menusStatus = 'idle'
      inflightMe = null
      this._persist()
    },

    async login(account: string, password: string,
                 opts: { captchaId?: string; captchaCode?: string } = {}) {
      const data = await authApi.login({
        account, password, captcha_id: opts.captchaId, captcha_code: opts.captchaCode,
      })
      this._applyLogin(data)
      try {
        await this.fetchMe()
      } catch (e) {
        this.clearLocal()
        throw e
      }
      return data
    },

    async register(payload: { account: string; password: string; email?: string; email_code?: string }) {
      const data = await authApi.register(payload)
      this._applyLogin(data)   // 注册后自动登录
      try {
        await this.fetchMe()
      } catch (e) {
        this.clearLocal()
        throw e
      }
      return data
    },

    async fetchMe(options: { background?: boolean } = {}) {
      // 已就绪的菜单展示更新无需拆卸工作区；失败仍进入 error 并关闭受控页面。
      if (!options.background || this.menusStatus !== 'ready') this.menusStatus = 'loading'
      try {
        const me = await authApi.getMe()
        this.user = me.user
        this.tenant = me.tenant
        this.role = me.role
        this.menus = me.menus as MenuTreeNode[]
        this.permissions = me.permissions
        this.menusStatus = 'ready'
        this._persist()
        return me
      } catch (e) {
        this.menusStatus = 'error'   // fail-closed：SideMenu 显错误态、不回退全量菜单
        throw e
      }
    },

    /** 确保 /me 已加载（去重并发）：已就绪直接返回；否则复用在途请求或发起一次。 */
    async ensureLoaded() {
      if (this.menusStatus === 'ready') return
      if (!inflightMe) {
        inflightMe = this.fetchMe().finally(() => { inflightMe = null })
      }
      await inflightMe
    },

    /** 手动重试（SideMenu 加载失败态「重试」按钮）。 */
    retryMe() {
      return this.ensureLoaded()
    },

    async logout() {
      try {
        await authApi.logout(getRefreshToken() || undefined)
      } catch {
        // 退出接口失败也强制前端清态（token 已本地失效即可）
      }
      this.clearLocal()
    },

    clearLocal() {
      useStockSet().resetSession(true)
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
      this.tenant = null
      this.role = ''
      this.menus = []
      this.permissions = []
      this.menusStatus = 'idle'
      inflightMe = null
      clearAuth()
    },
  },
})

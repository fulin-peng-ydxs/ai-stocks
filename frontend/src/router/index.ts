import { createMemoryHistory, createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { h } from 'vue'
import { getAccessToken } from '@/api/authToken'
import { useAuthStore } from '@/stores/auth'
import { resolveMenuGuard } from '@/utils/permission'

const HomeRedirect = { name: 'HomeRedirect', setup: () => () => h('div') }

export const routes: RouteRecordRaw[] = [
  // 登录/注册页（stage2·T7）：全屏独立壳（meta.fullscreen）+ 公开（meta.public，免登录）
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true, fullscreen: true },
  },
  { path: '/', name: 'home', component: HomeRedirect },
  {
    path: '/board',
    name: 'board',
    component: () => import('@/views/BoardView.vue'),
    meta: { title: '每日榜单' },
  },
  { path: '/score-profiles', redirect: '/system/config/score' },
  // 系统管理父菜单（P9 IA 归位）：系统配置 + 布局配置（三孙工作区）统一收入 /system/* 下。
  // 旧路由 /config、/layout-config/* 直接废弃、不做重定向（单用户本地、无外部书签）。
  {
    path: '/system/config',
    redirect: '/system/config/score',
  },
  {
    path: '/system/config/score',
    name: 'config-score',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '评分规则', configTab: 'score' },
  },
  {
    path: '/system/config/trade',
    name: 'config-trade',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '买卖指标', configTab: 'trade' },
  },
  {
    path: '/system/config/tech',
    name: 'config-tech',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '技术指标', configTab: 'tech' },
  },
  {
    path: '/system/config/system',
    name: 'config-system',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '系统设置', configTab: 'system' },
  },
  // 系统管理 › 权限管理（阶段三 RBAC）：用户管理页（P4）。按钮走 v-permission，菜单/守卫按后端权限（T15）。
  {
    path: '/system/users',
    name: 'user-manage',
    component: () => import('@/views/system/UserManageView.vue'),
    meta: { title: '用户管理' },
  },
  {
    path: '/system/roles',
    name: 'role-manage',
    component: () => import('@/views/system/RoleManageView.vue'),
    meta: { title: '角色管理' },
  },
  {
    path: '/system/menus',
    name: 'menu-manage',
    component: () => import('@/views/system/MenuResourceView.vue'),
    meta: { title: '菜单与功能' },
  },
  {
    path: '/system/tenants',
    name: 'tenant-manage',
    component: () => import('@/views/system/TenantManageView.vue'),
    meta: { title: '租户管理' },
  },
  {
    path: '/system/audit',
    name: 'audit-log',
    component: () => import('@/views/system/AuditLogView.vue'),
    meta: { title: '审计日志' },
  },
  {
    path: '/system/dicts',
    name: 'data-dictionary',
    component: () => import('@/views/system/DataDictionaryView.vue'),
    meta: { title: '数据字典' },
  },
  { path: '/system/layout', redirect: '/system/layout/presets' },
  {
    path: '/system/layout/presets',
    name: 'layout-presets',
    component: () => import('@/views/layout/LayoutPresetsView.vue'),
    meta: { title: '预设管理' },
  },
  {
    path: '/system/layout/pages',
    name: 'layout-pages',
    component: () => import('@/views/layout/LayoutPagesView.vue'),
    meta: { title: '页面布局' },
  },
  {
    path: '/system/layout/components',
    name: 'layout-components',
    component: () => import('@/views/layout/LayoutComponentsView.vue'),
    meta: { title: '系统组件' },
  },
  {
    path: '/screen',
    name: 'screen',
    component: () => import('@/views/ScreenView.vue'),
    meta: { title: '策略筛选' },
  },
  {
    path: '/backtest',
    name: 'backtest',
    component: () => import('@/views/BacktestView.vue'),
    meta: { title: '回测' },
  },
  {
    path: '/training',
    name: 'training',
    component: () => import('@/views/TrainingView.vue'),
    meta: { title: '盘感训练' },
  },
  {
    path: '/stocks',
    name: 'stocks',
    component: () => import('@/views/StocksView.vue'),
    meta: { title: '个股查询' },
  },
  {
    path: '/stocks/:code',
    name: 'stock-detail',
    component: () => import('@/views/StockDetailView.vue'),
    meta: { title: '个股详情' },
  },
  { path: '/data', redirect: '/data/overview' },
  { path: '/data-hub', redirect: '/data/overview' },   // 数据总览页已下线，旧链接重定向到数据概览
  {
    path: '/data/overview',
    name: 'data-overview',
    component: () => import('@/views/data/OverviewView.vue'),
    meta: { title: '数据概览' },
  },
  {
    path: '/data/ingest',
    name: 'data-ingest',
    component: () => import('@/views/data/IngestView.vue'),
    meta: { title: '数据采集' },
  },
  {
    path: '/data/quality',
    name: 'data-quality',
    component: () => import('@/views/data/QualityView.vue'),
    meta: { title: '数据质量' },
  },
  {
    path: '/data/schedule',
    name: 'data-schedule',
    component: () => import('@/views/data/ScheduleView.vue'),
    meta: { title: '任务调度' },
  },
  {
    path: '/sectors',
    name: 'sectors',
    component: () => import('@/views/SectorsView.vue'),
    meta: { title: '板块行情' },
  },
  // 兜底：未匹配路径（含已废弃的 /config、/layout-config/* 旧链接与误输）回动态首页，避免空白页。
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: typeof window === 'undefined' ? createMemoryHistory() : createWebHistory(),
  routes,
})

// 全局守卫（stage2·T7 骨架 + stage3·T15 菜单权限）：
// ① 公开路由放行（已登录再进登录页回动态首页）；② 未登录访问受控路由跳登录（带 redirect）；
// ③ 已登录先确保 /me 就绪（fail-closed：菜单/权限加载后再放行），再按授权菜单校验目标路由——
//    system 恒过；非 system 命中授权叶子（或其子路由）放行，否则重定向到首个授权页（无安全落点则放行、
//    交由后端接口级守卫兜底，避免重定向死循环）。
router.beforeEach(async (to) => {
  const loggedIn = !!getAccessToken()
  if (to.meta.public) {
    if (to.path === '/login' && loggedIn) return { path: '/' }
    return true
  }
  if (!loggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  const auth = useAuthStore()
  // 确保菜单/权限已加载；401 由 http 拦截器统一清态处理，其余瞬时错误吞掉不阻断（下面走 fail-closed 决策）。
  try { await auth.ensureLoaded() } catch { /* 401 已由拦截器处理；瞬时错误由菜单空触发 fail-closed */ }
  // ensureLoaded 期间若发生 401 清态，token 已失效 → 跳登录。
  if (!getAccessToken()) return { path: '/login', query: { redirect: to.fullPath } }
  // 动态首页：按 /me 下发菜单树的第一个可导航叶子落点；菜单空时保守落到 SAFE_HOME(/board)。
  if (to.path === '/') return { path: auth.firstMenuPath || '/board' }
  // 菜单授权决策（fail-closed）：system 恒过；未授权（含 /me 失败致菜单空）→ 漏斗到安全落点，
  // 绝不放行到被请求的未授权页壳；已在落点则渲染首页壳（SideMenu 显错误/空态+重试）。
  return resolveMenuGuard(to.path, {
    isSystem: auth.isSystem,
    menuRoutePaths: auth.menuRoutePaths,
    firstMenuPath: auth.firstMenuPath,
  })
})

export default router

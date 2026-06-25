import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/board' },
  {
    path: '/board',
    name: 'board',
    component: () => import('@/views/BoardView.vue'),
    meta: { title: '每日榜单' },
  },
  // 系统管理父菜单（P9 IA 归位）：系统配置 + 布局配置（三孙工作区）统一收入 /system/* 下。
  // 旧路由 /config、/layout-config/* 直接废弃、不做重定向（单用户本地、无外部书签）。
  {
    path: '/system/config',
    name: 'config',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '配置管理' },
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
  // 兜底：未匹配路径（含已废弃的 /config、/layout-config/* 旧链接与误输）回首页，避免空白页。
  { path: '/:pathMatch(.*)*', redirect: '/board' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/board' },
  {
    path: '/board',
    name: 'board',
    component: () => import('@/views/BoardView.vue'),
    meta: { title: '每日榜单' },
  },
  {
    path: '/config',
    name: 'config',
    component: () => import('@/views/ConfigView.vue'),
    meta: { title: '配置管理' },
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
    meta: { title: '数据采集与任务' },
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
    meta: { title: '调度与数据源' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router

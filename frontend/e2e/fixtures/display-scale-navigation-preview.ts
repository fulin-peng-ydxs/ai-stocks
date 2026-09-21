import { createApp, defineComponent, h } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, useRoute } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '@/styles/global.css'
import TopNavigation from '@/components/TopNavigation.vue'
import { initDisplayScale, setCustomDisplayScalePercent } from '@/composables/useDisplayScale'
import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/board', component: { template: '<div />' } },
  { path: '/sectors', component: { template: '<div />' } },
]
const router = createRouter({ history: createMemoryHistory(), routes })
const pinia = createPinia()
const auth = useAuthStore(pinia)
auth.menusStatus = 'ready'
auth.menus = [{
  index: 'market',
  title: '市场研究',
  icon: 'TrendCharts',
  children: [
    { index: '/board', title: '每日榜单', icon: 'DataBoard' },
    { index: '/sectors', title: '板块行情', icon: 'Monitor' },
  ],
}]

const Preview = defineComponent({
  setup() {
    const route = useRoute()
    return () => h('main', { class: 'navigation-preview' }, [
      h(TopNavigation, { level: 'secondary' }),
      h('section', { class: 'navigation-preview__content' }, [
        h('output', { 'data-testid': 'current-route' }, route.path),
      ]),
    ])
  },
})

initDisplayScale()
setCustomDisplayScalePercent(73)
await router.push('/board')
await router.isReady()
createApp(Preview).use(pinia).use(router).use(ElementPlus).mount('#app')

const style = document.createElement('style')
style.textContent = `
  .navigation-preview { min-height: 100%; background: var(--el-bg-color-page); }
  .navigation-preview__content { padding: 24px; }
`
document.head.appendChild(style)

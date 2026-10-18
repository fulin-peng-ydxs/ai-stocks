import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn' // Element Plus 中文（日历/分页等）
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css' // 暗色主题变量
import './styles/global.css'

import App from './App.vue'
import router from './router'
import { permission } from './directives/permission'
import { initTheme } from './composables/useTheme'
import { initAppNavigation } from './composables/useAppNavigation'
import { initDisplayScale } from './composables/useDisplayScale'
import { initLayoutPreset } from './layout'
import { installElementPlusPopperContainer } from './utils/elementPlusPopperContainer'
import { installScrollbarPolicy } from './components/scroll/installScrollbarPolicy'

initTheme() // 挂载前确定主题，避免闪烁
initLayoutPreset() // 挂载前应用内置预设 token（首屏不闪烁）
initAppNavigation() // 挂载前恢复导航布局，避免侧栏/顶栏切换闪烁
initDisplayScale() // 挂载前恢复应用显示比例，避免首屏先按 100% 渲染后跳变

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.directive('permission', permission) // 全局 v-permission 按钮级权限指令（T15）

// 首次导航（含公开路由判定、失效 token 清理和 /me 鉴权）完成前不挂载应用。
// 否则刷新 /login 时，START_LOCATION 会被 App 误判为非 fullscreen，短暂渲染工作台壳。
void router.isReady().then(() => {
  app.mount('#app')
  const root = document.querySelector<HTMLElement>('#app')!
  const stopPoppers = installElementPlusPopperContainer(root)
  const stopScrollbars = installScrollbarPolicy(root)
  import.meta.hot?.dispose(() => { stopScrollbars(); stopPoppers() })
})

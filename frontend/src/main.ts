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
import { initLayoutPreset, setPresetOverrides } from './layout'
import { listLayoutPresets } from './api/layout'

initTheme() // 挂载前确定主题，避免闪烁
initLayoutPreset() // 挂载前应用内置预设 token（首屏不闪烁）

// P11：挂载后异步拉取后端预设配置覆盖，注入后重刷外观——让"预设管理页编辑"真正驱动运行时。
// 失败（离线/接口异常）静默回落内置预设，不阻塞首屏。
listLayoutPresets()
  .then(({ presets }) => {
    const map: Record<string, Record<string, string | number>> = {}
    for (const p of presets) {
      const values = p.config?.values
      if (values && Object.keys(values).length) map[p.key] = values as Record<string, string | number>
    }
    if (Object.keys(map).length) setPresetOverrides(map)
  })
  .catch(() => { /* 离线：仅用内置预设 */ })

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.directive('permission', permission) // 全局 v-permission 按钮级权限指令（T15）
app.mount('#app')

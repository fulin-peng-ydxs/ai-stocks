import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// 纯 TS 逻辑测试用默认 node 环境；组件/指令测试用 `// @vitest-environment jsdom` 逐文件切换。
// 需 vue 插件转换 .vue SFC（SideMenu 等组件测试）。不开 globals，测试显式 import vitest API。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.{test,spec}.ts'],
  },
})

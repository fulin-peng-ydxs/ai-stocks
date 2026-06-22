import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

// 布局校验器等为纯 TS 逻辑，无需 DOM，故用 node 环境；不开 globals，测试显式 import vitest API。
export default defineConfig({
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.{test,spec}.ts'],
  },
})

import { defineConfig } from 'vitest/config'
import base from './vitest.config'

// 复用全量 src 收集范围；CI 不允许聚焦测试或空集合冒充完整回归。
export default defineConfig({
  ...base,
  test: {
    ...base.test,
    allowOnly: false,
    passWithNoTests: false,
    retry: 0,
    maxWorkers: 2,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,vue}'],
      exclude: ['src/**/*.{test,spec}.ts', 'src/**/*.d.ts', 'src/**/__tests__/**'],
      reporter: ['json', 'json-summary', 'lcov', 'text-summary'],
    },
  },
})

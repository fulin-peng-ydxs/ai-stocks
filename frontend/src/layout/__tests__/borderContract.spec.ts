import { describe, expect, it } from 'vitest'
// @ts-expect-error 门禁是直接由 Node 执行的 ESM，复用同一检查器避免测试维护第二套规则。
import { inspectBorderStyles } from '../../../scripts/border-contract.mjs'

describe('边界角色门禁', () => {
  it('拦截普通面板游离圆角、直接颜色及页面输入状态覆盖', () => {
    expect(inspectBorderStyles('.panel { border-radius: 8px; border: 1px solid #aaa; }', 'views/Example.vue')).toHaveLength(2)
    expect(inspectBorderStyles('.page :deep(.el-range-editor.is-active) { box-shadow: none; }', 'views/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles('.panel { border-top-left-radius: 6px; }', 'components/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles('.panel { border-radius: var(--layout-card-radius) 8px; }', 'components/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles('.panel { border-radius: calc(var(--layout-card-radius) + 8px); }', 'components/Example.vue')).toHaveLength(1)
  })

  it('允许共享角色、圆形、胶囊及具名图形；例外不能扩散到同文件的普通面板', () => {
    const css = '.panel { border: 1px solid var(--app-border-default); border-radius: var(--layout-card-radius); } .dot { border-radius: 50%; } .pill { border-radius: 999px; }'
    expect(inspectBorderStyles(css, 'components/Example.vue')).toEqual([])
    expect(inspectBorderStyles('.panel { border-radius: var(--layout-card-radius, 10px); }', 'components/Example.vue')).toEqual([])
    expect(inspectBorderStyles('.navigation-preview { border-radius: 8px; }', 'App.vue')).toEqual([])
    expect(inspectBorderStyles('.ordinary-panel { border-radius: 8px; }', 'App.vue')).toHaveLength(1)
  })
})

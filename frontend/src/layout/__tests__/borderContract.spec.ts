import { FULL_SOURCE_AUDIT_TIMEOUT_MS } from './helpers/fullSourceAudit'
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { parse } from '@vue/compiler-sfc'
import { describe, expect, it } from 'vitest'
// @ts-expect-error 门禁是直接由 Node 执行的 ESM，复用同一检查器避免测试维护第二套规则。
import { inspectBorderStyles, inspectStockChartBoundaries, inspectSegmentedRoles } from '../../../scripts/border-contract.mjs'

describe('边界角色门禁', () => {
  it('拦截普通面板游离圆角、直接颜色及页面输入状态覆盖', () => {
    expect(inspectBorderStyles('.panel { border-radius: 8px; border: 1px solid #aaa; }', 'views/Example.vue')).toHaveLength(2)
    expect(inspectBorderStyles('.page :deep(.el-range-editor.is-active) { box-shadow: none; }', 'views/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles('.panel { border-top-left-radius: 6px; }', 'components/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles('.panel { border-radius: var(--layout-card-radius) 8px; }', 'components/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles('.panel { border-radius: calc(var(--layout-card-radius) + 8px); }', 'components/Example.vue')).toHaveLength(1)
  })

  it('允许共享角色、圆形、胶囊及具名图形；例外不能扩散到同文件的普通面板', () => {
    const css = '.divider { border-top: 1px solid var(--app-border-divider); } .dot { border-radius: 50%; } .pill { border-radius: 999px; }'
    expect(inspectBorderStyles(css, 'components/Example.vue')).toEqual([])
    expect(inspectBorderStyles('.panel { border-radius: var(--layout-card-radius, 10px); }', 'components/Example.vue')).toEqual([])
    expect(inspectBorderStyles('.navigation-preview { border-radius: 8px; }', 'App.vue')).toEqual([])
    expect(inspectBorderStyles('.ordinary-panel { border-radius: 8px; }', 'App.vue')).toHaveLength(1)
  })
})

describe('表面与分段语义收口', () => {
  it('页面即使引用主题变量也不能重新拼接普通表面，唯一共享入口可定义配方', () => {
    const recipe = '.panel { border: 1px solid var(--app-border-subtle); border-radius: var(--layout-card-radius); background: var(--el-bg-color); }'
    expect(inspectBorderStyles(recipe, 'views/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles(recipe, 'styles/borders.css')).toEqual([])
    expect(inspectBorderStyles(recipe.replace('--layout-card-radius)', '--layout-card-radius, 10px)'), 'views/Example.vue')).toHaveLength(1)
    expect(inspectBorderStyles('.panel { padding: var(--app-space-3); }', 'views/Example.vue')).toEqual([])
    expect(inspectBorderStyles('.app-interaction-card::before { border: 1px solid var(--el-border-color-lighter); }', 'styles/global.css')).toHaveLength(1)
  })

  it('主模式需要登记，普通参数默认中性，拒绝动态绕过、角色错配及失效记录', () => {
    const file = 'views/Example.vue'
    const roles = [{ file, label: '工作区模式', tone: 'primary', variant: 'contained', reason: '切换主工作区' }]
    const primary = '<PageSegmented aria-label="工作区模式" tone="primary" />'
    expect(inspectSegmentedRoles(primary, file, roles)).toEqual([])
    expect(inspectSegmentedRoles(primary, file, [])).toHaveLength(1)
    expect(inspectSegmentedRoles('<PageSegmented aria-label="工作区模式" />', file, roles)).toHaveLength(1)
    expect(inspectSegmentedRoles('<PageSegmented aria-label="参数" />', file, [])).toEqual([])
    expect(inspectSegmentedRoles('<PageSegmented :tone="tone" />', file, [])).toHaveLength(1)
    expect(inspectSegmentedRoles('<PageSegmented aria-label="参数" variant="tabs" />', file, [])).toHaveLength(1)
    expect(inspectSegmentedRoles('<div />', file, roles)).toHaveLength(1)
  })

  it('扫描全部真实模板和样式，主角色、普通表面与登记保持一致', () => {
    const root = resolve(process.cwd(), 'src')
    const findings: string[] = []
    function scan(directory: string) {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        if (entry.name === '__tests__') continue
        const path = join(directory, entry.name)
        if (entry.isDirectory()) { scan(path); continue }
        if (!path.endsWith('.vue')) continue
        const file = relative(root, path)
        const descriptor = parse(readFileSync(path, 'utf8')).descriptor
        const results = [
          ...inspectSegmentedRoles(descriptor.template?.content ?? '', file),
          ...descriptor.styles.flatMap(style => inspectBorderStyles(style.content, file)),
        ]
        findings.push(...results.map((finding: { message: string }) => `${file}: ${finding.message}`))
      }
    }
    scan(root)
    expect(findings).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})

describe('股票画布边界所有权门禁', () => {
  it.each(['AppWorkspacePane', 'section class="app-surface"'])(
    '穿透 %s 内的异步层，拒绝遗漏或动态嵌入声明', host => {
      const tag = host.split(' ')[0]
      for (const props of ['', ':embedded="false"', ':embedded="mode"', 'embedded="false"',
        'embedded :embedded="false"', 'embedded v-bind="props"']) {
        expect(inspectStockChartBoundaries(`<${host}><AppAsyncRegion>
          <template #default><StockChartWorkspace ${props} /></template>
        </AppAsyncRegion></${tag}>`)).toHaveLength(1)
      }
      expect(inspectStockChartBoundaries(`<${host}><AppAsyncRegion>
        <StockChartWorkspace embedded />
      </AppAsyncRegion></${tag}>`)).toEqual([])
    },
  )

  it('独立画布保留外框；弹层切断外围宿主作用域', () => {
    expect(inspectStockChartBoundaries('<StockChartRegion><StockChartWorkspace /></StockChartRegion>')).toEqual([])
    expect(inspectStockChartBoundaries('<el-card><div class="round-chart"><StockChartWorkspace /></div></el-card>')).toEqual([])
    expect(inspectStockChartBoundaries('<StockChartWorkspace embedded />')).toHaveLength(1)
    expect(inspectStockChartBoundaries(`<AppWorkspacePane>
      <StockChartWorkspace embedded />
      <AppDialog><StockChartWorkspace /></AppDialog>
      <PageDrawer><AppWorkspacePane><StockChartWorkspace embedded /></AppWorkspacePane></PageDrawer>
    </AppWorkspacePane>`)).toEqual([])
  })

  it('扫描全部真实消费者，并证明删除任一嵌入声明会被拦截', () => {
    const root = resolve(process.cwd(), 'src')
    const findings: string[] = []
    let embeddedConsumers = 0
    function inspectDirectory(directory: string) {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        if (entry.name === '__tests__') continue
        const path = join(directory, entry.name)
        if (entry.isDirectory()) { inspectDirectory(path); continue }
        if (!path.endsWith('.vue')) continue
        const template = parse(readFileSync(path, 'utf8')).descriptor.template?.content
        if (!template?.includes('<StockChartWorkspace')) continue
        findings.push(...inspectStockChartBoundaries(template).map(
          ({ message }: { message: string }) => `${relative(root, path)}: ${message}`,
        ))
        const mutation = template.replace(/(<StockChartWorkspace\b[^>]*?)\s+embedded(?=\s|\/?>)/g, '$1')
        if (mutation !== template) {
          embeddedConsumers++
          expect(inspectStockChartBoundaries(mutation), relative(root, path)).not.toEqual([])
        }
      }
    }
    inspectDirectory(root)
    expect(embeddedConsumers).toBeGreaterThan(0)
    expect(findings).toEqual([])
  }, FULL_SOURCE_AUDIT_TIMEOUT_MS)
})

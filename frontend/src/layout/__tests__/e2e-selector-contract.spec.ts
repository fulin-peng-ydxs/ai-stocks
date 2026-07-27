import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const LONG_TERM_E2E = [
  '../../../e2e/login-initial-render.spec.ts',
  '../../../e2e/role-permission-tree-accessibility.spec.ts',
]

describe('长期 E2E 选择器契约', () => {
  it.each(LONG_TERM_E2E)('%s 只使用稳定测试锚点或可访问语义', (path) => {
    const source = readFileSync(new URL(path, import.meta.url), 'utf8')

    expect(source).not.toMatch(/\b(?:locator|matches|querySelector)\(\s*['"`]\./)
    expect(source).not.toMatch(/\b(?:locator|matches|querySelector)\(\s*['"`][^'"`]*\s+\./)
  })

  it('普通展示文本和一次性容器不承载测试锚点', () => {
    const sources = [
      '../../../src/App.vue',
      '../../../src/views/LoginView.vue',
      '../../../src/components/SystemBuiltinTag.vue',
      '../../../src/views/system/PermissionResourceList.vue',
      '../../../src/views/system/RoleManageView.vue',
      '../../../src/views/system/MenuResourceView.vue',
    ].map((path) => readFileSync(new URL(path, import.meta.url), 'utf8')).join('\n')

    for (const forbiddenTestId of [
      'app-shell',
      'login-page',
      'permission-name',
      'active-role-name',
      'active-menu-title',
      'builtin-resource-code',
      'system-builtin-tag',
    ]) {
      expect(sources).not.toContain(`data-testid="${forbiddenTestId}"`)
    }
  })
})

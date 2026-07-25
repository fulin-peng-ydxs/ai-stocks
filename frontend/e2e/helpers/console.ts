import type { ConsoleMessage, Page } from '@playwright/test'

export interface ConsoleIssueOptions {
  allowedHttpStatuses?: readonly number[]
}

function isAllowedHttpFailure(message: ConsoleMessage, statuses: readonly number[]): boolean {
  const text = message.text()
  return statuses.some((status) => text.includes(`status of ${status}`))
}

/** 默认统一收集 error/warning；路由注入的预期 HTTP 失败必须显式加入白名单。 */
export function collectConsoleIssues(
  page: Page,
  options: ConsoleIssueOptions = {},
): string[] {
  const issues: string[] = []
  const allowedHttpStatuses = options.allowedHttpStatuses ?? []
  page.on('console', (message) => {
    if (
      ['error', 'warning'].includes(message.type())
      && !isAllowedHttpFailure(message, allowedHttpStatuses)
    ) {
      issues.push(message.text())
    }
  })
  return issues
}

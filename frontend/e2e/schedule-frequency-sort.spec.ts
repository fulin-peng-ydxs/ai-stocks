import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

test('任务调度频率列按实际执行时间升降序', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  const queriedOrders: string[] = []
  await page.route(/\/api\/data\/schedules(?:\?.*)?$/, async (route) => {
    const jobs = ['20:20', '20:10', '21:30', '00:00', '01:00'].map((time, index) => ({
      id: `e2e-schedule-${index}`,
      name: `任务 ${index}`,
      task_type: 'update',
      params: {},
      freq_type: 'daily',
      freq_config: { time },
      trigger_mode: 'time',
      dependency_job_id: null,
      dependency_condition: null,
      dependency_delay: { value: 0, unit: 'minute' },
      retry_config: { enabled: false, condition: 'failure', delay: { value: 5, unit: 'minute' }, max_retries: 1 },
      trading_day_only: true,
      enabled: true,
      last_run_at: null,
      last_task_id: null,
      created_at: '2026-08-24T00:00:00',
      updated_at: '2026-08-24T00:00:00',
      freq_text: `每天 ${time}`,
      trigger_text: `每天 ${time}`,
      waiting_trigger_count: 0,
      next_run_time: null,
    }))
    const query = new URL(route.request().url()).searchParams
    if (query.get('sort_by') === 'freq') {
      const order = query.get('sort_order')
      queriedOrders.push(order || '')
      jobs.sort((a, b) => a.freq_config.time.localeCompare(b.freq_config.time) * (order === 'desc' ? -1 : 1))
    }
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: { jobs, total: jobs.length, page: 1, size: 30, task_types: ['update'], quality_issue_types: [] },
      }),
    })
  })

  await openPageAndWaitForHeading(page, '/data/schedule', '任务调度')
  const frequencies = page.getByTestId('schedule-frequency')
  const frequencyHeader = page.getByRole('columnheader', { name: /触发规则/ })

  await frequencyHeader.click()
  await expect(frequencies).toHaveText([
    '每天 00:00', '每天 01:00', '每天 20:10', '每天 20:20', '每天 21:30',
  ])
  expect(queriedOrders.at(-1)).toBe('asc')

  await frequencyHeader.click()
  await expect(frequencies).toHaveText([
    '每天 21:30', '每天 20:20', '每天 20:10', '每天 01:00', '每天 00:00',
  ])
  expect(queriedOrders.at(-1)).toBe('desc')
  expect(consoleIssues).toEqual([])
})

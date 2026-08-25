import { expect, test } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { openPageAndWaitForHeading } from './helpers/navigation'

test('任务调度频率列按实际执行时间升降序', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  await loginAsDebugUser(page, request, 'debug_system')
  await page.route('**/api/data/schedules', async (route) => {
    const jobs = ['20:20', '20:10', '21:30', '00:00', '01:00'].map((time, index) => ({
      id: `e2e-schedule-${index}`,
      name: `任务 ${index}`,
      task_type: 'update',
      params: {},
      freq_type: 'daily',
      freq_config: { time },
      trading_day_only: true,
      enabled: true,
      last_run_at: null,
      last_task_id: null,
      created_at: '2026-08-24T00:00:00',
      updated_at: '2026-08-24T00:00:00',
      freq_text: `每天 ${time}`,
      next_run_time: null,
    }))
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: { jobs, task_types: ['update'], quality_issue_types: [] },
      }),
    })
  })

  await openPageAndWaitForHeading(page, '/data/schedule', '任务调度')
  const frequencies = page.getByTestId('schedule-frequency')
  const frequencyHeader = page.getByRole('columnheader', { name: /频率/ })

  await frequencyHeader.click()
  await expect(frequencies).toHaveText([
    '每天 00:00', '每天 01:00', '每天 20:10', '每天 20:20', '每天 21:30',
  ])

  await frequencyHeader.click()
  await expect(frequencies).toHaveText([
    '每天 21:30', '每天 20:20', '每天 20:10', '每天 01:00', '每天 00:00',
  ])
  expect(consoleIssues).toEqual([])
})

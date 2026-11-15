import { expect, test, type APIRequestContext } from '@playwright/test'

import { loginAsDebugUser } from './helpers/auth'
import { collectConsoleIssues } from './helpers/console'
import { DEFAULT_E2E_API_URL } from './helpers/e2e-backend-health.mjs'

const API_URL = process.env.E2E_API_URL || DEFAULT_E2E_API_URL

async function cleanupDependencyJobs(request: APIRequestContext, headers: Record<string, string>) {
  const response = await request.get(`${API_URL}/data/schedules`, { headers })
  if (!response.ok()) return
  const jobs = (await response.json()).data.jobs as { id: string; name: string }[]
  for (const prefix of ['E2E 依赖下游 ', 'E2E 依赖上游 ']) {
    for (const job of jobs.filter((item) => item.name.startsWith(prefix))) {
      await request.delete(`${API_URL}/data/schedules/${job.id}`, { headers })
    }
  }
}

test('可配置单上游依赖、延迟触发和有上限自身重试', async ({ page, request }) => {
  const consoleIssues = collectConsoleIssues(page)
  const auth = await loginAsDebugUser(page, request, 'debug_system')
  const headers = { authorization: `Bearer ${auth.accessToken}` }
  const suffix = Date.now()
  const upstreamName = `E2E 依赖上游 ${suffix}`
  const downstreamName = `E2E 依赖下游 ${suffix}`
  let upstreamId = ''
  let downstreamId = ''

  try {
    await cleanupDependencyJobs(request, headers)
    const created = await request.post(`${API_URL}/data/schedules`, {
      headers,
      data: {
        name: upstreamName,
        task_type: 'recompute',
        params: {},
        trigger_mode: 'time',
        freq_type: 'daily',
        freq_config: { time: '16:00' },
        dependency_delay: { value: 0, unit: 'minute' },
        retry_config: {
          enabled: false,
          condition: 'failure',
          delay: { value: 5, unit: 'minute' },
          max_retries: 1,
        },
        trading_day_only: false,
        enabled: false,
      },
    })
    expect(created.ok()).toBe(true)
    upstreamId = (await created.json()).data.id

    await page.goto('/data/schedule')
    await page.getByTestId('schedule-create').click()
    await page.getByTestId('schedule-name').fill(downstreamName)
    await page.getByTestId('schedule-trigger-mode-dependency').click()
    await page.getByTestId('schedule-dependency-job').click()
    await page.getByRole('option', { name: upstreamName }).click()
    // 上游已支持多选，选择后下拉保持打开；先正常关闭，再操作结果条件。
    await page.keyboard.press('Escape')
    await page.getByTestId('schedule-dependency-condition-failure').click()
    await expect(page.getByTestId('schedule-dependency-condition-failure')).toHaveAttribute('aria-pressed', 'true')
    await page.getByTestId('schedule-dependency-delay').locator('input').fill('2')
    await page.getByTestId('schedule-retry-enabled').click()
    await page.getByTestId('schedule-retry-delay').locator('input').fill('3')
    await page.getByTestId('schedule-max-retries').locator('input').fill('2')
    await page.getByTestId('schedule-enabled').click()
    await page.getByTestId('schedule-save').click()
    const downstreamRow = page.getByRole('row').filter({ hasText: downstreamName })
    await expect(downstreamRow).toBeVisible()

    const response = await request.get(`${API_URL}/data/schedules`, { headers })
    expect(response.ok()).toBe(true)
    const jobs = (await response.json()).data.jobs
    const downstream = jobs.find((item: { name: string }) => item.name === downstreamName)
    downstreamId = downstream?.id || ''
    expect(downstream).toMatchObject({
      trigger_mode: 'dependency',
      dependency_job_id: upstreamId,
      dependency_job_ids: [upstreamId],
      dependency_condition: 'failure',
      dependency_delay: { value: 2, unit: 'minute' },
      retry_config: {
        enabled: true,
        condition: 'failure',
        delay: { value: 3, unit: 'minute' },
        max_retries: 2,
      },
      enabled: false,
    })
    await expect(downstreamRow).toContainText('失败后')
    expect(consoleIssues).toEqual([])
  } finally {
    if (downstreamId) await request.delete(`${API_URL}/data/schedules/${downstreamId}`, { headers })
    if (upstreamId) await request.delete(`${API_URL}/data/schedules/${upstreamId}`, { headers })
    await cleanupDependencyJobs(request, headers)
  }
})

test('停用等待事件需确认且触发记录展示完整中文语义', async ({ page, request }) => {
  await loginAsDebugUser(page, request, 'debug_system')
  let enabledCalls = 0
  const job = {
    id: 'mock_waiting_job',
    name: '待确认依赖任务',
    task_type: 'checkup',
    params: {},
    freq_type: null,
    freq_config: {},
    trigger_mode: 'dependency',
    dependency_job_id: 'mock_upstream',
    dependency_job_name: '模拟上游',
    dependency_condition: 'completion',
    dependency_delay: { value: 2, unit: 'minute' },
    retry_config: {
      enabled: false,
      condition: 'failure',
      delay: { value: 5, unit: 'minute' },
      max_retries: 1,
    },
    trading_day_only: false,
    enabled: true,
    last_run_at: null,
    last_task_id: null,
    created_at: '2026-08-25 12:00:00',
    updated_at: '2026-08-25 12:00:00',
    freq_text: '依赖触发',
    trigger_text: '模拟上游·完成后，延迟2分钟',
    waiting_trigger_count: 2,
    next_dependency_run_at: '2026-08-25 16:02:00',
    next_run_time: '2026-08-25 16:02:00',
  }
  await page.route(/\/api\/data\/schedules(?:\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: { jobs: [job], total: 1, page: 1, size: 30, task_types: ['checkup'], quality_issue_types: [] },
      }),
    })
  })
  await page.route('**/api/data/schedules/mock_waiting_job/enabled*', async (route) => {
    enabledCalls += 1
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, msg: '已停用', data: { ...job, enabled: false } }),
    })
  })
  await page.route('**/api/data/schedules/mock_waiting_job/trigger-events*', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        msg: 'ok',
        data: {
          events: [{
            id: 'evt_mock',
            chain_id: 'task_root',
            source_task_id: 'task_upstream',
            source_attempt: 1,
            source_status: 'done',
            source_job_name: '模拟上游',
            target_job_id: job.id,
            trigger_kind: 'dependency',
            trigger_condition: 'completion',
            retry_count: 0,
            due_at: '2026-08-25 16:02:00',
            dispatched_at: '2026-08-25 16:02:03',
            status: 'dispatched',
            task_id: 'task_downstream',
            created_at: '2026-08-25 16:00:00',
            updated_at: '2026-08-25 16:02:03',
          }],
        },
      }),
    })
  })

  await page.goto('/data/schedule')
  const row = page.getByRole('row').filter({ hasText: job.name })
  await expect(row).toBeVisible()
  await page.getByTestId(`schedule-enabled-${job.id}`).click()
  await expect(page.getByRole('dialog', { name: '停用调度任务' })).toContainText(
    '取消当前 2 条等待或触发中的事件',
  )
  await page.getByRole('button', { name: '取消' }).click()
  expect(enabledCalls).toBe(0)

  await row.getByRole('button', { name: '更多' }).click()
  await page.getByRole('menuitem', { name: '触发记录' }).click()
  await expect(page.getByRole('cell', { name: '成功' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '完成后', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '2026-08-25 16:02:03' })).toBeVisible()
  await expect(page.getByText(`${job.name} · 触发记录`, { exact: true })).toBeVisible()
})

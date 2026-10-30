import { describe, expect, it } from 'vitest'
import { requestRuntimeText, taskRequestFields } from '../requestRuntime'

describe('请求运行指标', () => {
  it('历史任务缺指标时不补零', () => {
    expect(taskRequestFields()).toEqual([])
    expect(requestRuntimeText()).toContain('暂不可用')
  })

  it('来源真实失败与耗时独立于探活结果展示', () => {
    const text = requestRuntimeText({ requests: 20, failures: 2, network_seconds: 12.5,
      wait_seconds: 3, active: 2, waiting: 1, observed_rate: 4.5 })
    expect(text).toContain('网络在途 2 · 等待额度 1 · 近一分钟 4.5 次/秒')
    expect(text).toContain('累计请求 20 次 · 技术失败 2 次 · 网络 12.5 秒 · 额度等待 3.0 秒')
  })

  it('区分任务覆盖、物理请求与等待状态，未知ETA不展示精确时间', () => {
    const fields = taskRequestFields({
      requests: 30, failures: 2, network_seconds: 8.25, wait_seconds: 3.15,
      states: { network: 2, source_wait: 1, write_queue: 3 },
      completed: 20, elapsed_seconds: 15, work_concurrency: 6, default_concurrency: 4,
      concurrency_origin: 'task', policy_version: 'v1', policy_degraded: true,
    })
    expect(fields.find(f => f.label === '工作并发')?.value).toBe('6（任务覆盖；启动时默认 4）')
    expect(fields.find(f => f.label === '工作状态')?.value).toContain('网络 2 · 等待额度 1 · 等待落库 3')
    expect(fields.find(f => f.label === '当前阶段预计剩余')?.value).toContain('样本不足')
    const fingerprint = fields.find(f => f.label === '配置指纹')
    expect(fingerprint?.value).toBe('v1')
    expect(fingerprint?.warning).toContain('最近有效配置')
    expect(fields.find(f => f.label === '累计重试退避')?.value).toBe('未记录')
  })

  it('显示有效并发和配置容量，并将退避与额度等待分开', () => {
    const fields = taskRequestFields({
      requests: 4, failures: 0, network_seconds: 1, wait_seconds: 0.2,
      states: { retry_wait: 1 }, completed: 1, elapsed_seconds: 7,
      work_concurrency: 1, configured_work_concurrency: 8, retry_wait_seconds: 6,
    })
    expect(fields.find(f => f.label === '工作并发')?.value).toBe('1（系统默认；本阶段配置 8）')
    expect(fields.find(f => f.label === '工作状态')?.value).toContain('重试退避 1')
    expect(fields.find(f => f.label === '累计额度等待')?.value).toBe('0.2 秒')
    expect(fields.find(f => f.label === '累计重试退避')?.value).toBe('6.0 秒')
  })
})

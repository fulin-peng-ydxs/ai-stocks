import { ref } from 'vue'
import { readAuth } from '@/api/authToken'
import { syncLayoutUserDensity } from '@/api/layout'
import { PAGE_REGISTRY } from '@/layout/pageRegistry'
import type { Density } from '@/layout/schema'
import { knobMap, makeLayoutOverride } from '@/layout/merge'
import { readStoredOverlay } from '@/layout/useLayoutConfig'

interface DensityConsumer {
  /** 排空批量操作前已接受的保存；后续保存通过 barrier 等待批量事务结束。 */
  prepare: () => Promise<unknown>
  apply: (density: Density) => Density | void
}

const consumers = new Map<string, Set<DensityConsumer>>()
export const pageDensitySyncing = ref(false)
let barrier: Promise<void> | undefined

export function pageDensitySaveBarrier(): Promise<void> | undefined {
  return barrier
}

export function registerPageDensityConsumer(pageKey: string, consumer: DensityConsumer): () => void {
  const group = consumers.get(pageKey) ?? new Set<DensityConsumer>()
  group.add(consumer)
  consumers.set(pageKey, group)
  return () => {
    group.delete(consumer)
    if (!group.size) consumers.delete(pageKey)
  }
}

export function layoutPreferenceIdentity(): string {
  const auth = readAuth()
  return `${auth.tenant?.id ?? ''}:${auth.user?.id ?? ''}`
}

/** 一次性同步，不保存全局覆盖值；后续页面编辑继续使用原来的用户布局通道。 */
export async function unifyPageDensity(density: Density): Promise<number> {
  if (pageDensitySyncing.value) throw new Error('页面密度正在同步')
  const requestIdentity = layoutPreferenceIdentity()
  pageDensitySyncing.value = true
  let release!: () => void
  try {
    // prepare 同步捕获既有队列，随后才设置屏障；避免把排空任务自身堵住。
    const pending = [...consumers.values()].flatMap((group) => [...group].map((item) => item.prepare()))
    barrier = new Promise<void>((resolve) => { release = resolve })
    await Promise.all(pending)
    if (layoutPreferenceIdentity() !== requestIdentity) throw new Error('登录账号已变化，请重新应用')
    const result = await syncLayoutUserDensity({
      density,
      pageKeys: PAGE_REGISTRY.map((entry) => entry.pageKey),
    })
    if (layoutPreferenceIdentity() !== requestIdentity) throw new Error('登录账号已变化，请重新应用')
    for (const pageKey of result.pageKeys) {
      let cachedDensity = result.density
      for (const consumer of consumers.get(pageKey) ?? []) {
        cachedDensity = consumer.apply(result.density) ?? cachedDensity
      }
      const entry = PAGE_REGISTRY.find((page) => page.pageKey === pageKey)
      if (entry) {
        try {
          const key = `ai-stocks:layout:${pageKey}`
          const values = readStoredOverlay(key, knobMap(entry.layout))
          localStorage.setItem(key, JSON.stringify(makeLayoutOverride({ ...values, density: cachedDensity })))
        } catch { /* 本地缓存不可写不影响 PG 已提交的结果。 */ }
      }
    }
    return result.pageKeys.length
  } finally {
    barrier = undefined
    release?.()
    pageDensitySyncing.value = false
  }
}

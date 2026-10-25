/**
 * 应用层布局配置接线：在 useLayoutConfig（可移植布局核心）之上，
 * 挂载时拉取后端 page/user 两层配置并注入，使页面级默认和当前用户的
 * 「布局/组件偏好」真正作用到页面渲染。
 *
 * 分层（对齐 requirement §5.6 推荐节奏）：
 *   - 页面层：后端持久化（本 composable 接入）。
 *   - 用户层：PG 为权威；localStorage 仅作为离线 fallback 和迁移源。
 * 后端不可达或 403 时静默回落本地默认/缓存，页面照常渲染，不阻塞首屏。
 */
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { componentMetaForSlot, getPageEntry, useLayoutConfig, type PageLayout } from '@/layout'
import { getEffectiveLayoutConfig, saveLayoutUserConfig } from '@/api/layout'
import { layoutPreferenceIdentity, pageDensitySaveBarrier, registerPageDensityConsumer } from './pageDensitySync'

export function useRemoteLayoutConfig(base: PageLayout) {
  const ownerIdentity = layoutPreferenceIdentity()
  const registryEntry = getPageEntry(base.pageKey)
  const componentMetaBySlot = registryEntry
    ? Object.fromEntries(registryEntry.layout.slots.map((slot) => [slot.id, componentMetaForSlot(registryEntry, slot)]))
    : undefined
  const config = useLayoutConfig(base, { componentMetaBySlot })
  const remoteHydrated = ref(false)
  const remoteError = ref(false)
  const saving = ref(false)
  const saveError = ref(false)
  let resolveRemoteHydrated!: () => void
  const remoteHydratedPromise = new Promise<void>((resolve) => {
    resolveRemoteHydrated = resolve
  })
  let saveTimer: number | undefined
  let saveQueue: Promise<unknown> = Promise.resolve()
  let pendingSaveCount = 0
  let applyingDensity = false
  let densityEditedDuringSync = false

  function saveNow(): Promise<boolean> {
    if (!remoteHydrated.value || layoutPreferenceIdentity() !== ownerIdentity) return Promise.resolve(false)
    // 显式保存接管当前写入，取消 watcher 已排队的同值请求，避免重复 POST。
    if (saveTimer) {
      window.clearTimeout(saveTimer)
      saveTimer = undefined
    }
    pendingSaveCount += 1
    saving.value = true
    const densityBarrier = pageDensitySaveBarrier()
    const task = saveQueue.then(async (): Promise<boolean> => {
      if (densityBarrier) await densityBarrier
      try {
        if (layoutPreferenceIdentity() !== ownerIdentity) throw new Error('登录账号已变化')
        // 在真正轮到本次写入时读取最新配置，串行保证后发值最终落库。
        const userConfig = config.exportUserConfig()
        await saveLayoutUserConfig(base.pageKey, {
          config: userConfig,
          schemaVersion: userConfig.schemaVersion,
          layout: base as unknown as Record<string, unknown>,
        })
        saveError.value = false
        return true
      } catch {
        saveError.value = true
        return false
      } finally {
        pendingSaveCount -= 1
        saving.value = pendingSaveCount > 0
      }
    })
    saveQueue = task.then(() => undefined)
    return task
  }

  function scheduleSave(): void {
    if (!remoteHydrated.value) return
    if (saveTimer) window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => {
      saveTimer = undefined
      void saveNow()
    }, 300)
  }

  onMounted(async () => {
    let shouldFlushDirty = false
    try {
      // effective 同时返回经过后端读取过滤的 page/user 配置和字段开放策略；
      // 前端按 default < page < user 合并，以保留来源追踪和本地代码默认。
      const effective = await getEffectiveLayoutConfig(base.pageKey)
      config.applyComponentFieldPolicies(effective.componentFieldPolicies ?? [])
      const page = effective.layers.find((item) => item.layer === 'page')?.config
      const user = effective.layers.find((item) => item.layer === 'user')?.config
      config.applyPageConfig({ values: page?.values ?? {} })
      const applied = config.applyUserConfig(
        { schemaVersion: user?.schemaVersion, values: user?.values ?? {} },
        { preserveDirty: true },
      )
      shouldFlushDirty = applied.preservedDirty
    } catch {
      remoteError.value = true
      config.applyUserConfig({ values: config.exportUserConfig().values }, { preserveDirty: false })
    }

    remoteHydrated.value = true
    resolveRemoteHydrated()
    if (shouldFlushDirty) void saveNow()
  })

  // 批量补丁已落库，无需将整份配置再写一次；普通编辑仍照常防抖保存。
  watch(config.userConfigValues, () => {
    if (!applyingDensity) scheduleSave()
  }, { deep: true, flush: 'sync' })
  function markDensityEdit(path = 'density') {
    if (path === 'density' && pageDensitySaveBarrier()) densityEditedDuringSync = true
  }

  const unregisterDensity = registerPageDensityConsumer(base.pageKey, {
    prepare() {
      densityEditedDuringSync = false
      const pending = saveTimer ? saveNow() : saveQueue
      return Promise.all([remoteHydratedPromise, pending])
    },
    apply(density) {
      // 批量期间用户新做的逐页选择应在事务之后保存，不被批量响应反向覆盖。
      if (densityEditedDuringSync) return config.valueOf('density') as PageLayout['density']
      applyingDensity = true
      try {
        config.setKnob('density', density)
      } finally {
        applyingDensity = false
      }
    },
  })
  onScopeDispose(() => {
    unregisterDensity()
    // 关闭标签也要保存防抖窗口内的编辑，不能因移除密度订阅而丢失原有持久化。
    if (saveTimer) void saveNow()
  })

  return {
    ...config,
    setKnob(path: string, value: unknown) {
      config.setKnob(path, value)
      markDensityEdit(path)
    },
    resetKnob(path: string) {
      config.resetKnob(path)
      markDensityEdit(path)
    },
    resetAll() {
      config.resetAll()
      markDensityEdit()
    },
    resetLayer(layer: Parameters<typeof config.resetLayer>[0]) {
      config.resetLayer(layer)
      if (layer === 'user') markDensityEdit()
    },
    remoteHydrated: computed(() => remoteHydrated.value),
    whenRemoteHydrated: () => remoteHydratedPromise,
    remoteError: computed(() => remoteError.value),
    remoteSaving: computed(() => saving.value),
    remoteSaveError: computed(() => saveError.value),
    saveRemoteUserConfig: saveNow,
  }
}

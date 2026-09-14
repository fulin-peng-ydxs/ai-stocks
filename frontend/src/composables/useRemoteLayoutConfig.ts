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
import { computed, onMounted, ref, watch } from 'vue'
import { componentMetaForSlot, getPageEntry, useLayoutConfig, type PageLayout } from '@/layout'
import { getEffectiveLayoutConfig, saveLayoutUserConfig } from '@/api/layout'

export function useRemoteLayoutConfig(base: PageLayout) {
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

  async function saveNow(): Promise<void> {
    if (!remoteHydrated.value) return
    saving.value = true
    try {
      const userConfig = config.exportUserConfig()
      await saveLayoutUserConfig(base.pageKey, {
        config: userConfig,
        schemaVersion: userConfig.schemaVersion,
        layout: base as unknown as Record<string, unknown>,
      })
      saveError.value = false
    } catch {
      saveError.value = true
    } finally {
      saving.value = false
    }
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

  watch(config.userConfigValues, () => scheduleSave(), { deep: true })

  return {
    ...config,
    remoteHydrated: computed(() => remoteHydrated.value),
    whenRemoteHydrated: () => remoteHydratedPromise,
    remoteError: computed(() => remoteError.value),
    remoteSaving: computed(() => saving.value),
    remoteSaveError: computed(() => saveError.value),
    saveRemoteUserConfig: saveNow,
  }
}

/**
 * 应用层布局配置接线：在 useLayoutConfig（可移植布局核心）之上，
 * 挂载时拉取后端 page/user 两层配置并注入，使配置中心保存的「页面默认预设 +
 * 页面级覆盖」和当前用户的「布局/组件偏好」真正作用到页面渲染。
 *
 * 分层（对齐 requirement §5.6 推荐节奏）：
 *   - 预设层 / 页面层：后端持久化（本 composable 接入）。
 *   - 用户层：PG 为权威；localStorage 仅作为离线 fallback 和迁移源。
 * 后端不可达或 403 时静默回落本地默认/缓存，页面照常渲染，不阻塞首屏。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useLayoutConfig, type PageLayout } from '@/layout'
import { getLayoutPageConfig, getLayoutUserConfig, saveLayoutUserConfig } from '@/api/layout'

export function useRemoteLayoutConfig(base: PageLayout) {
  const config = useLayoutConfig(base)
  const remoteHydrated = ref(false)
  const remoteError = ref(false)
  const saving = ref(false)
  const saveError = ref(false)
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
    const pageReq = getLayoutPageConfig(base.pageKey)
    const userReq = getLayoutUserConfig(base.pageKey)
    const [pageResult, userResult] = await Promise.allSettled([pageReq, userReq])
    let shouldFlushDirty = false

    if (pageResult.status === 'fulfilled') {
      const page = pageResult.value
      config.applyPageConfig({ presetKey: page.presetKey, values: page.config?.values ?? {} })
    } else {
      remoteError.value = true
    }

    if (userResult.status === 'fulfilled') {
      const user = userResult.value
      const applied = config.applyUserConfig(
        { schemaVersion: user.config?.schemaVersion, values: user.config?.values ?? {} },
        { preserveDirty: true },
      )
      shouldFlushDirty = applied.preservedDirty
    } else {
      remoteError.value = true
      config.applyUserConfig({ values: config.exportUserConfig().values }, { preserveDirty: false })
    }

    remoteHydrated.value = true
    if (shouldFlushDirty) void saveNow()
  })

  watch(config.userConfigValues, () => scheduleSave(), { deep: true })

  return {
    ...config,
    remoteHydrated: computed(() => remoteHydrated.value),
    remoteError: computed(() => remoteError.value),
    remoteSaving: computed(() => saving.value),
    remoteSaveError: computed(() => saveError.value),
    saveRemoteUserConfig: saveNow,
  }
}

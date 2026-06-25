/**
 * 应用层布局配置接线：在 useLayoutConfig（可移植布局核心，仅本地）之上，
 * 挂载时拉取后端 layout_page_config 并注入页面层，使配置中心保存的「页面默认预设 +
 * 页面级覆盖」真正作用到页面渲染。
 *
 * 分层（对齐 requirement §5.6 推荐节奏）：
 *   - 预设层 / 页面层：后端持久化（本 composable 接入）。
 *   - 用户层：仍走 localStorage（多用户体系接入前不后端化），由 useLayoutConfig 内部处理。
 * 后端不可达时静默回落本地默认，页面照常渲染，不阻塞首屏。
 */
import { onMounted } from 'vue'
import { useLayoutConfig, type PageLayout } from '@/layout'
import { getLayoutPageConfig } from '@/api/layout'

export function useRemoteLayoutConfig(base: PageLayout) {
  const config = useLayoutConfig(base)

  onMounted(async () => {
    try {
      const page = await getLayoutPageConfig(base.pageKey)
      config.applyPageConfig({ presetKey: page.presetKey, values: page.config?.values ?? {} })
    } catch {
      /* 离线 / 接口失败：保持代码默认 + 本地预设 + localStorage 用户层 */
    }
  })

  return config
}

import { defineConfig } from 'vitest/config'
import base from './vitest.config'

// 共享组件新增测试自动接入；工具与 composable 纳入设计/交互契约，业务测试仍按影响定向运行。
export default defineConfig({
  ...base,
  test: {
    ...base.test,
    include: [
      'src/layout/**/*.{spec,test}.ts',
      'src/components/**/*.{spec,test}.ts',
      'src/directives/**/*.{spec,test}.ts',
      'src/utils/__tests__/{dateTime,displayScaleGeometry,displayText,elementPlusPopperContainer,fixedDecimal,keyboard,latestAnimationFrame,messagePolicy,money,money-consumers,multiSelectFilter,numberFormat,number-consumers,reorderTree}.{spec,test}.ts',
      'src/composables/__tests__/{useAppNavigation,useDefaultedSessionValue,useDisplayScale,useDrawerPreferences,useFormChangeTracker,useGlobalPreferenceSync,useLayoutViewport,useMediaQuery,useMenuPageTitle,usePageShortcuts,useRemoteLayoutConfig,useTheme,useUnsavedChangesGuard,useUserPreference,useWorkspaceTabs,useWorkspaceTabPreferences}.{spec,test}.ts',
    ],
  },
})

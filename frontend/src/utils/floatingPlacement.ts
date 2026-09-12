import type { Placement } from 'element-plus'

/**
 * 表单下拉与日期面板默认固定在触发器下方，只允许左右对齐回退。
 * 页面如有明确交互理由仍可覆盖，但不得各自复制位置数组。
 */
export const APP_BOTTOM_FLOATING_PLACEMENT: Placement = 'bottom-start'
export const APP_BOTTOM_FLOATING_FALLBACKS: Placement[] = ['bottom-start', 'bottom-end']

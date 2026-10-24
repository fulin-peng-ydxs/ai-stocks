import { ElMessageBox } from 'element-plus'

export type AssetVisibility = 'private' | 'tenant' | 'public'

const VISIBILITY_LEVEL: Record<AssetVisibility, number> = {
  private: 0,
  tenant: 1,
  public: 2,
}

/**
 * 收窄方案可见性会同步收窄依赖它的已发布回测，必须在用户操作入口显式说明影响。
 */
export async function confirmProfileVisibilityReduction(
  name: string,
  current: AssetVisibility,
  target: AssetVisibility,
): Promise<boolean> {
  if (VISIBILITY_LEVEL[target] >= VISIBILITY_LEVEL[current]) return true
  const targetLabel = target === 'private' ? '私有' : '租户公开'
  try {
    await ElMessageBox.confirm(
      `确认将方案「${name}」收回为${targetLabel}？引用它且可见范围更大的回测将同步收窄，历史结果不会删除。`,
      '收回方案可见性',
      { confirmButtonType: 'warning', type: 'warning', confirmButtonText: '确认收回', cancelButtonText: '取消' },
    )
    return true
  } catch {
    return false
  }
}

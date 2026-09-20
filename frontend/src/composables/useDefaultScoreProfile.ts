import { listUserPreferences } from '@/api/userPreferences'
import type { ProfileSummary } from '@/components/asset-search/types'
import { useUserPreference } from '@/composables/useUserPreference'
import { ref } from 'vue'

export interface DefaultScoreProfile {
  profile_ref: string
  id: string
  name: string
  version: number
  is_preset: boolean
  source: string | null
  owner_label: string | null
  readonly: boolean
}

const defaults: DefaultScoreProfile = {
  profile_ref: '', id: '', name: '', version: 0, is_preset: false,
  source: null, owner_label: null, readonly: true,
}

/** 评分业务域共享默认方案；包含旧榜单偏好的一次兼容迁移。 */
export function useDefaultScoreProfile() {
  const pref = useUserPreference<DefaultScoreProfile>({
    scope: 'feature',
    pageKey: 'scoring',
    prefKey: 'default-score-profile',
    defaults,
    localStorageKey: 'ai-stocks-default-score-profile',
  })

  function assign(item: ProfileSummary | null): void {
    if (!item) {
      pref.reset()
      return
    }
    pref.value.profile_ref = item.profile_ref || ''
    pref.value.id = item.id
    pref.value.name = item.name
    pref.value.version = item.version
    pref.value.is_preset = item.is_preset
    pref.value.source = item.source ?? null
    pref.value.owner_label = item.owner_label ?? null
    pref.value.readonly = true
  }

  const hydrated = ref(false)
  async function migrateLegacy(): Promise<void> {
    await pref.whenHydrated()
    if (pref.value.profile_ref || pref.value.id) {
      hydrated.value = true
      return
    }
    try {
      let saved: Partial<DefaultScoreProfile> | undefined
      try {
        const response = await listUserPreferences({
          scope: 'feature', pageKey: 'board', prefKey: 'default-score-profile',
        })
        saved = response.items[0]?.value as Partial<DefaultScoreProfile> | undefined
      } catch {
        // 旧远端偏好暂不可读时仍允许迁移浏览器内已保存的榜单默认；不得把网络故障当成无偏好。
      }
      if (!saved?.profile_ref && !saved?.id) {
        const raw = localStorage.getItem('ai-stocks-board-default-profile')
        saved = raw ? JSON.parse(raw) as Partial<DefaultScoreProfile> : undefined
      }
      if (!saved?.profile_ref && !saved?.id) return
      assign({
        id: saved.id || '',
        profile_ref: saved.profile_ref || undefined,
        name: saved.name || '默认评分方案',
        version: Number(saved.version || 0),
        is_preset: Boolean(saved.is_preset),
        source: saved.source as ProfileSummary['source'],
        owner_label: saved.owner_label,
        readonly: true,
      })
      await pref.saveRemoteNow()
      localStorage.removeItem('ai-stocks-board-default-profile')
    } catch {
      // 网络或旧载荷异常不能清除新偏好，也不能制造隐式默认。
    } finally {
      hydrated.value = true
    }
  }

  void migrateLegacy()
  return { ...pref, hydrated, setDefault: assign }
}

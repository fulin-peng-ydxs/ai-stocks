import { ref } from 'vue'
import { getPublicDictItems, type DictItem } from '@/api/dict'

export function usePublicDictItems(typeCode: string) {
  const items = ref<DictItem[]>([])

  async function load() {
    try {
      items.value = (await getPublicDictItems(typeCode)).items
    } catch {
      items.value = []
    }
  }

  return { items, load }
}

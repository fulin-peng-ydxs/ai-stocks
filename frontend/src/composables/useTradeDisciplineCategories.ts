import { inject, provide, ref, type InjectionKey, type Ref } from 'vue'
import { getPublicDictItems } from '@/api/dict'
import { checklistCategories, conditionCategories, type ChecklistCategoryOption } from '@/utils/tradeDisciplineConditions'

const CATEGORY_OPTIONS: InjectionKey<Ref<ChecklistCategoryOption[]>> = Symbol('trade-condition-categories')

/** 一个工作台统一加载分类，编辑、核对、历史和组件属性共用同一份候选。 */
export function provideTradeDisciplineCategories() {
  const categories = ref<ChecklistCategoryOption[]>([])
  const error = ref(false)
  const loading = ref(false)
  let request: Promise<void> | undefined
  async function load() {
    if (request) return request
    loading.value = true
    request = (async () => {
      try {
        const data = await getPublicDictItems('trade_discipline_condition_category')
        if (data.fallback) throw new Error('字典读取失败')
        categories.value = data.items.filter(item => !['other', 'notes'].includes(item.code))
          .map(item => ({ value: item.code, label: item.label }))
        error.value = false
      } catch { error.value = true }
      finally { loading.value = false; request = undefined }
    })()
    return request
  }
  provide(CATEGORY_OPTIONS, categories)
  return { categories, error, loading, load }
}

export function useTradeDisciplineCategories() {
  return inject(CATEGORY_OPTIONS, ref<ChecklistCategoryOption[]>(checklistCategories))
}

/** 复用现有 config-panel 元数据覆盖，新增分类同时进入默认折叠属性。 */
export function tradeConditionMeta(categories: readonly ChecklistCategoryOption[]) {
  return {
    stockConditions: {
      collapseSections: [...conditionCategories([], categories).map(item => ({ key: item.value, label: item.label })),
        { key: 'notes', label: '补充说明' }],
    },
  }
}

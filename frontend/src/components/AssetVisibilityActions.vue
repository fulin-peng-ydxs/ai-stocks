<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import AssetVisibilityTag from './AssetVisibilityTag.vue'

type AssetVisibility = 'private' | 'tenant' | 'public'

const props = withDefaults(defineProps<{
  visibility?: AssetVisibility
  readonly?: boolean
  canPublishTenant?: boolean
  canPublishPublic?: boolean
  saving?: boolean
  showVisibility?: boolean
  showReadonly?: boolean
  copyVisible?: boolean
  copyPermission?: string
  copyLabel?: string
  copyDisabled?: boolean
  reuseVisible?: boolean
  reusePermission?: string
  reuseLabel?: string
  reuseDisabled?: boolean
}>(), {
  visibility: 'private',
  readonly: false,
  canPublishTenant: false,
  canPublishPublic: false,
  saving: false,
  showVisibility: true,
  showReadonly: true,
  copyVisible: false,
  copyPermission: '',
  copyLabel: '复制为我的方案',
  copyDisabled: false,
  reuseVisible: false,
  reusePermission: '',
  reuseLabel: '复用参数',
  reuseDisabled: false,
})

const emit = defineEmits<{
  publish: [visibility: AssetVisibility]
  copy: []
  reuse: []
}>()

const canEdit = computed(() =>
  props.showVisibility
  && !props.readonly
  && (props.canPublishTenant || props.canPublishPublic),
)

function onCommand(command: string | number | object) {
  if (typeof command === 'string') emit('publish', command as AssetVisibility)
}
</script>

<template>
  <span class="asset-visibility-actions">
    <el-dropdown
      v-if="canEdit"
      trigger="click"
      :hide-on-click="true"
      @command="onCommand"
    >
      <AssetVisibilityTag :visibility="visibility" clickable>
        <el-icon class="asset-visibility-actions__arrow"><ArrowDown /></el-icon>
      </AssetVisibilityTag>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="private" :disabled="visibility === 'private' || saving">
            私有
          </el-dropdown-item>
          <el-dropdown-item command="tenant" :disabled="visibility === 'tenant' || !canPublishTenant || saving">
            租户公开
          </el-dropdown-item>
          <el-dropdown-item command="public" :disabled="visibility === 'public' || !canPublishPublic || saving">
            全体公开
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <AssetVisibilityTag
      v-else-if="showVisibility"
      :visibility="visibility"
      :readonly="readonly"
    />
    <AssetVisibilityTag v-if="showReadonly && readonly" mode="readonly" />
    <el-button
      v-if="copyVisible && copyPermission"
      v-permission="copyPermission"
      plain
      :disabled="copyDisabled"
      @click="$emit('copy')"
    >
      {{ copyLabel }}
    </el-button>
    <el-button
      v-else-if="copyVisible"
      plain
      :disabled="copyDisabled"
      @click="$emit('copy')"
    >
      {{ copyLabel }}
    </el-button>
    <el-button
      v-if="reuseVisible && reusePermission"
      v-permission="reusePermission"
      :disabled="reuseDisabled"
      @click="$emit('reuse')"
    >
      {{ reuseLabel }}
    </el-button>
    <el-button
      v-else-if="reuseVisible"
      :disabled="reuseDisabled"
      @click="$emit('reuse')"
    >
      {{ reuseLabel }}
    </el-button>
  </span>
</template>

<style scoped>
.asset-visibility-actions {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}
.asset-visibility-actions__arrow {
  margin-left: 4px;
  font-size: 11px;
  vertical-align: -1px;
}
</style>

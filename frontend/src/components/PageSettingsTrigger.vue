<script setup lang="ts">
defineProps<{ dirty?: boolean }>()
defineEmits<{ click: [] }>()
</script>

<template>
  <button class="page-settings-trigger" type="button" @click="$emit('click')">
    <span class="gear">⚙</span>
    <span v-if="dirty" class="dot" />
  </button>
</template>

<style scoped>
.page-settings-trigger {
  position: relative;
  width: 38px;
  height: 38px;
  border: none;
  background: transparent;
  color: var(--page-settings-trigger-text);
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color .15s ease, color .15s ease, transform .15s ease;
}
.page-settings-trigger:hover {
  background: var(--page-settings-trigger-hover-bg);
  color: var(--page-settings-trigger-hover-text);
}
.page-settings-trigger:active {
  transform: translateY(1px);
}
.gear {
  font-size: 22px;
  line-height: 1;
}
.dot {
  position: absolute;
  top: 7px;
  right: 7px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--page-settings-accent);
  box-shadow: 0 0 0 2px var(--page-settings-dot-ring);
}
</style>

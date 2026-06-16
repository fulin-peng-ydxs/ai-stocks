<script setup lang="ts">
defineProps<{ title?: string; desc?: string }>()
</script>

<template>
  <section class="page-setting-section">
    <header v-if="title || desc" class="pss-head">
      <span v-if="title" class="pss-title">{{ title }}</span>
      <span v-if="desc" class="pss-desc">{{ desc }}</span>
    </header>
    <div class="pss-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.page-setting-section + .page-setting-section {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--page-settings-divider);
}
.pss-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 10px;
}
.pss-title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--page-settings-text-subtle);
}
.pss-desc {
  font-size: 12px;
  color: var(--page-settings-text-muted);
}
.pss-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>

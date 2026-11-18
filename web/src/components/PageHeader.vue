<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="header">
    <div>
      <h2 class="title">{{ title }}</h2>
      <p v-if="description" class="muted desc">{{ description }}</p>
    </div>
    <div class="actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
}

.desc {
  margin: 6px 0 0;
  font-size: 13px;
}

.actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
</style>

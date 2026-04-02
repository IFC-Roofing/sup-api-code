<template>
  <div class="widget-card">
    <h3 class="widget-title">🚨 Needs Attention</h3>

    <div v-if="loading" class="space-y-3">
      <div v-for="i in 4" :key="i" class="h-14 bg-ifc-border/30 rounded-xl animate-pulse"></div>
    </div>

    <div v-else-if="items.length === 0" class="text-center py-8">
      <p class="text-ifc-green text-2xl mb-2">✅</p>
      <p class="text-gray-400 text-sm">All clear — nothing needs attention</p>
    </div>

    <div v-else class="space-y-3 max-h-80 overflow-y-auto pr-1">
      <div
        v-for="item in items"
        :key="item.project_id + item.issue"
        class="flex items-start gap-3 p-3 rounded-xl bg-ifc-dark/50 border border-ifc-border/50
               hover:border-ifc-border transition-colors"
      >
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-white truncate">{{ item.project_name }}</p>
          <p class="text-xs text-gray-400 mt-0.5">{{ item.issue }}</p>
          <p class="text-xs text-gray-500">{{ item.detail }}</p>
        </div>
        <span :class="'badge-' + item.severity">{{ item.severity }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  loading: Boolean,
})
</script>

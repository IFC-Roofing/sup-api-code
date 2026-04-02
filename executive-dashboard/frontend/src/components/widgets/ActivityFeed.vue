<template>
  <div class="widget-card">
    <h3 class="widget-title">⚡ Recent Activity</h3>

    <div v-if="loading" class="space-y-3">
      <div v-for="i in 5" :key="i" class="h-16 bg-ifc-border/30 rounded-xl animate-pulse"></div>
    </div>

    <div v-else-if="activities.length === 0" class="text-center py-8">
      <p class="text-gray-400 text-sm">No recent activity</p>
    </div>

    <div v-else class="space-y-2">
      <div
        v-for="(item, i) in activities"
        :key="item.id || i"
        class="flex items-start gap-3 p-3 rounded-xl hover:bg-ifc-dark/50 transition-colors"
      >
        <!-- Timeline dot -->
        <div class="flex flex-col items-center mt-1.5">
          <div class="w-2 h-2 rounded-full bg-ifc-accent"></div>
          <div v-if="i < activities.length - 1" class="w-px h-full bg-ifc-border/50 mt-1"></div>
        </div>

        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <p class="text-sm font-medium text-white truncate">{{ item.project_name || 'System' }}</p>
            <span v-for="tag in item.tags" :key="tag"
              class="text-xs bg-ifc-accent/20 text-ifc-accent px-1.5 py-0.5 rounded">
              {{ tag }}
            </span>
          </div>
          <p class="text-xs text-gray-400 mt-0.5 line-clamp-2">{{ item.content }}</p>
          <p class="text-xs text-gray-600 mt-1">{{ formatTime(item.created_at) }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  activities: { type: Array, default: () => [] },
  loading: Boolean,
})

function formatTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    const now = new Date()
    const diffMs = now - d
    const diffH = Math.floor(diffMs / 3600000)
    if (diffH < 1) return 'Just now'
    if (diffH < 24) return `${diffH}h ago`
    const diffD = Math.floor(diffH / 24)
    if (diffD < 7) return `${diffD}d ago`
    return d.toLocaleDateString()
  } catch {
    return ts
  }
}
</script>

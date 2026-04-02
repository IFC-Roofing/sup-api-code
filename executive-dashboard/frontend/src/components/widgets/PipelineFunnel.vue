<template>
  <div class="widget-card">
    <h3 class="widget-title">📊 Pipeline</h3>

    <div v-if="loading" class="space-y-3">
      <div v-for="i in 5" :key="i" class="h-8 bg-ifc-border/30 rounded-lg animate-pulse"></div>
    </div>

    <div v-else-if="data.length === 0" class="text-gray-500 text-sm py-8 text-center">
      No pipeline data available
    </div>

    <div v-else class="space-y-3">
      <div v-for="stage in data" :key="stage.stage" class="group">
        <div class="flex items-center justify-between mb-1">
          <span class="text-sm text-gray-300 group-hover:text-white transition-colors">{{ stage.stage }}</span>
          <span class="text-sm font-bold text-white">{{ stage.count }}</span>
        </div>
        <div class="h-2.5 bg-ifc-border/40 rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-700 ease-out"
            :class="barColor(stage.stage)"
            :style="{ width: barWidth(stage.count) + '%' }"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
  loading: Boolean,
})

const maxCount = computed(() => Math.max(...props.data.map(d => d.count), 1))

function barWidth(count) {
  return Math.max((count / maxCount.value) * 100, 4)
}

function barColor(stage) {
  const colors = {
    'New Lead': 'bg-gray-400',
    'Signed': 'bg-blue-400',
    'Inspection Scheduled': 'bg-blue-500',
    'Inspection Complete': 'bg-indigo-400',
    'Claim Filed': 'bg-purple-400',
    'Office Hands': 'bg-ifc-amber',
    'Supplement Sent': 'bg-orange-400',
    'Response Received': 'bg-cyan-400',
    'Appraisal': 'bg-pink-400',
    'Approved': 'bg-ifc-green',
    'In Production': 'bg-emerald-400',
    'Capped Out': 'bg-ifc-accent',
  }
  return colors[stage] || 'bg-ifc-accent'
}
</script>

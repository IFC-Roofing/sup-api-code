<template>
  <div class="widget-card">
    <p class="stat-label">{{ label }}</p>
    <p class="stat-value" :class="colorClass">
      {{ prefix }}{{ formatted }}{{ suffix }}
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: String,
  value: { type: Number, default: 0 },
  prefix: { type: String, default: '' },
  suffix: { type: String, default: '' },
  color: { type: String, default: 'white' },
})

const colorMap = {
  blue: 'text-blue-400',
  green: 'text-ifc-green',
  amber: 'text-ifc-amber',
  accent: 'text-ifc-accent',
  white: 'text-white',
}

const colorClass = computed(() => colorMap[props.color] || 'text-white')

const formatted = computed(() => {
  if (props.prefix === '$') {
    if (props.value >= 1000000) return (props.value / 1000000).toFixed(1) + 'M'
    if (props.value >= 1000) return (props.value / 1000).toFixed(0) + 'K'
    return props.value.toLocaleString()
  }
  return props.value.toLocaleString(undefined, { maximumFractionDigits: 1 })
})
</script>

<template>
  <div class="flex items-center justify-center" :class="containerClass">
    <div
      class="animate-spin rounded-full border-4 border-solid border-ifc-blue border-r-transparent"
      :class="sizeClass"
    ></div>
    <p v-if="message" class="ml-3 text-gray-400">{{ message }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  size: {
    type: String,
    default: 'md',
    validator: (value) => ['sm', 'md', 'lg'].includes(value)
  },
  message: {
    type: String,
    default: ''
  },
  containerClass: {
    type: String,
    default: 'py-8'
  }
})

const sizeClass = computed(() => {
  const sizes = {
    sm: 'h-6 w-6',
    md: 'h-10 w-10',
    lg: 'h-16 w-16'
  }
  return sizes[props.size]
})
</script>

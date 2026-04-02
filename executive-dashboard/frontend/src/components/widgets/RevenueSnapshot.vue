<template>
  <WidgetCard title="Total Pipeline" :loading="loading" :error="error">
    <div class="text-center">
      <div class="text-3xl font-bold text-white mb-1">
        {{ formatCurrency(revenueData.total_pipeline_rcv) }}
      </div>
      <div class="text-sm text-gray-400">RCV</div>
    </div>
  </WidgetCard>

  <WidgetCard title="Capped This Month" :loading="loading" :error="error">
    <div class="text-center">
      <div class="text-3xl font-bold text-green-400 mb-1">
        {{ formatCurrency(revenueData.capped_this_month) }}
      </div>
      <div class="text-sm text-gray-400">Revenue</div>
    </div>
  </WidgetCard>

  <WidgetCard title="Capped This Week" :loading="loading" :error="error">
    <div class="text-center">
      <div class="text-3xl font-bold text-blue-400 mb-1">
        {{ formatCurrency(revenueData.capped_this_week) }}
      </div>
      <div class="text-sm text-gray-400">Revenue</div>
    </div>
  </WidgetCard>

  <WidgetCard title="Average GP%" :loading="loading" :error="error">
    <div class="text-center">
      <div class="text-3xl font-bold text-purple-400 mb-1">
        {{ revenueData.average_gp_percent?.toFixed(1) || '0.0' }}%
      </div>
      <div class="text-sm text-gray-400">Gross Profit</div>
    </div>
  </WidgetCard>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import WidgetCard from '../common/WidgetCard.vue'

const revenueData = ref({
  total_pipeline_rcv: 0,
  capped_this_month: 0,
  capped_this_week: 0,
  average_gp_percent: 0
})
const loading = ref(true)
const error = ref(null)

function formatCurrency(value) {
  if (!value) return '$0'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
  }).format(value)
}

async function fetchData() {
  loading.value = true
  error.value = null

  try {
    const response = await axios.get('/api/dashboard/revenue')
    revenueData.value = response.data
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to load revenue data'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchData()
  window.addEventListener('dashboard-refresh', fetchData)
})
</script>

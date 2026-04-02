<template>
  <div class="min-h-screen bg-ifc-dark">
    <!-- Header -->
    <header class="sticky top-0 z-50 bg-ifc-dark/80 backdrop-blur-xl border-b border-ifc-border">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <img src="/ifc_logo.png" alt="IFC" class="h-8" />
          <div>
            <h1 class="text-lg font-bold leading-tight">Sup</h1>
            <p class="text-xs text-gray-500">Executive Dashboard</p>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <button
            @click="refreshAll"
            :class="['p-2 rounded-lg transition-all', refreshing ? 'animate-spin text-ifc-accent' : 'text-gray-400 hover:text-white hover:bg-ifc-card']"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <div class="flex items-center gap-2">
            <img v-if="user.picture" :src="user.picture" class="w-8 h-8 rounded-full" />
            <span class="text-sm text-gray-300 hidden sm:inline">{{ user.name }}</span>
          </div>
          <button @click="logout" class="text-gray-400 hover:text-white text-sm">Logout</button>
        </div>
      </div>
    </header>

    <!-- Dashboard Grid -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
      <!-- Revenue Row -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <RevenueCard label="Pipeline RCV" :value="revenue.pipeline_rcv" prefix="$" color="blue" />
        <RevenueCard label="Capped This Month" :value="revenue.capped_this_month" prefix="$" color="green" />
        <RevenueCard label="Capped This Week" :value="revenue.capped_this_week" prefix="$" color="amber" />
        <RevenueCard label="Avg Gross Profit" :value="revenue.avg_gp_pct" suffix="%" color="accent" />
      </div>

      <!-- Pipeline + Attention -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PipelineFunnel :data="pipeline" :loading="loadingPipeline" />
        <AttentionItems :items="attention" :loading="loadingAttention" />
      </div>

      <!-- Activity Feed -->
      <ActivityFeed :activities="activities" :loading="loadingActivity" />
    </main>

    <!-- Chat FAB -->
    <ChatWidget />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import RevenueCard from '../components/widgets/RevenueCard.vue'
import PipelineFunnel from '../components/widgets/PipelineFunnel.vue'
import AttentionItems from '../components/widgets/AttentionItems.vue'
import ActivityFeed from '../components/widgets/ActivityFeed.vue'
import ChatWidget from '../components/widgets/ChatWidget.vue'

const router = useRouter()
const user = ref({ name: '', picture: '' })
const refreshing = ref(false)

// Data
const revenue = ref({ pipeline_rcv: 0, capped_this_month: 0, capped_this_week: 0, avg_gp_pct: 0 })
const pipeline = ref([])
const attention = ref([])
const activities = ref([])

// Loading states
const loadingPipeline = ref(true)
const loadingAttention = ref(true)
const loadingActivity = ref(true)

async function fetchUser() {
  try {
    const res = await fetch('/auth/me')
    if (!res.ok) return router.push('/login')
    user.value = await res.json()
  } catch {
    router.push('/login')
  }
}

async function fetchRevenue() {
  try {
    const res = await fetch('/api/dashboard/revenue')
    if (res.ok) revenue.value = await res.json()
  } catch (e) { console.error('Revenue fetch failed', e) }
}

async function fetchPipeline() {
  loadingPipeline.value = true
  try {
    const res = await fetch('/api/dashboard/pipeline')
    if (res.ok) {
      const data = await res.json()
      pipeline.value = data.pipeline || []
    }
  } catch (e) { console.error('Pipeline fetch failed', e) }
  loadingPipeline.value = false
}

async function fetchAttention() {
  loadingAttention.value = true
  try {
    const res = await fetch('/api/dashboard/attention')
    if (res.ok) {
      const data = await res.json()
      attention.value = data.items || []
    }
  } catch (e) { console.error('Attention fetch failed', e) }
  loadingAttention.value = false
}

async function fetchActivity() {
  loadingActivity.value = true
  try {
    const res = await fetch('/api/dashboard/activity')
    if (res.ok) {
      const data = await res.json()
      activities.value = data.activities || []
    }
  } catch (e) { console.error('Activity fetch failed', e) }
  loadingActivity.value = false
}

async function refreshAll() {
  refreshing.value = true
  await Promise.all([fetchRevenue(), fetchPipeline(), fetchAttention(), fetchActivity()])
  refreshing.value = false
}

async function logout() {
  await fetch('/auth/logout', { method: 'POST' })
  router.push('/login')
}

onMounted(async () => {
  await fetchUser()
  refreshAll()
})
</script>

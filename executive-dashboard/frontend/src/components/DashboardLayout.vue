<template>
  <div class="min-h-screen bg-ifc-darker">
    <!-- Header -->
    <header class="bg-ifc-dark border-b border-gray-800 sticky top-0 z-50 backdrop-blur-sm bg-opacity-95">
      <div class="container mx-auto px-4 py-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-4">
            <img src="/ifc_logo.png" alt="IFC Logo" class="h-10 w-auto">
            <div>
              <h1 class="text-xl font-bold text-white">Executive Dashboard</h1>
              <p class="text-sm text-gray-400">Real-time pipeline insights</p>
            </div>
          </div>

          <div class="flex items-center space-x-4">
            <button
              @click="refreshData"
              :disabled="refreshing"
              class="p-2 hover:bg-gray-800 rounded-lg transition-colors"
              title="Refresh data"
            >
              <svg
                class="w-5 h-5 text-gray-400"
                :class="{ 'animate-spin': refreshing }"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>

            <div class="flex items-center space-x-3">
              <div class="text-right hidden sm:block">
                <p class="text-sm font-medium text-white">{{ authStore.user?.name }}</p>
                <p class="text-xs text-gray-400">{{ authStore.user?.email }}</p>
              </div>
              <button
                @click="handleLogout"
                class="px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm font-medium text-gray-300 transition-colors"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Main content -->
    <main class="container mx-auto px-4 py-6 pb-24">
      <!-- Stats overview row -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
        <RevenueSnapshot />
      </div>

      <!-- Pipeline and activity -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <PipelineFunnel />
        <ActivityFeed />
      </div>

      <!-- Attention items (full width) -->
      <div class="mb-6">
        <AttentionItems />
      </div>
    </main>

    <!-- Chat widget (floating) -->
    <ChatWidget />

    <!-- Footer -->
    <footer class="bg-ifc-dark border-t border-gray-800 mt-12">
      <div class="container mx-auto px-4 py-6">
        <div class="flex items-center justify-between text-sm text-gray-500">
          <p>&copy; 2026 IFC Roofing. All rights reserved.</p>
          <p>Last updated: {{ lastUpdate }}</p>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'
import PipelineFunnel from './widgets/PipelineFunnel.vue'
import RevenueSnapshot from './widgets/RevenueSnapshot.vue'
import ActivityFeed from './widgets/ActivityFeed.vue'
import AttentionItems from './widgets/AttentionItems.vue'
import ChatWidget from './widgets/ChatWidget.vue'

const authStore = useAuthStore()
const router = useRouter()

const refreshing = ref(false)
const lastUpdate = ref(new Date().toLocaleTimeString())
let refreshInterval = null

async function refreshData() {
  refreshing.value = true
  // Trigger refresh on all widgets via event bus
  window.dispatchEvent(new CustomEvent('dashboard-refresh'))
  lastUpdate.value = new Date().toLocaleTimeString()

  setTimeout(() => {
    refreshing.value = false
  }, 1000)
}

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}

onMounted(() => {
  // Auto-refresh every 5 minutes
  refreshInterval = setInterval(() => {
    refreshData()
  }, 5 * 60 * 1000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

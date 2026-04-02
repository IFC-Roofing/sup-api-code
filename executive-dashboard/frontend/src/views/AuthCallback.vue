<template>
  <div class="min-h-screen flex items-center justify-center bg-ifc-dark">
    <div class="text-center">
      <div class="animate-spin w-8 h-8 border-2 border-ifc-accent border-t-transparent rounded-full mx-auto mb-4"></div>
      <p class="text-gray-400">{{ message }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const message = ref('Signing you in...')

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('code')
  const error = params.get('error')

  if (error) {
    message.value = `Auth error: ${error}`
    setTimeout(() => router.push('/login'), 2000)
    return
  }

  if (!code) {
    message.value = 'No authorization code received'
    setTimeout(() => router.push('/login'), 2000)
    return
  }

  try {
    const res = await fetch('/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        redirect_uri: `${window.location.origin}/auth/callback`,
      }),
    })

    if (res.ok) {
      router.push('/')
    } else {
      const data = await res.json()
      message.value = data.detail || 'Authentication failed'
      setTimeout(() => router.push('/login'), 3000)
    }
  } catch (e) {
    message.value = 'Connection error'
    setTimeout(() => router.push('/login'), 2000)
  }
})
</script>

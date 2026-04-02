<template>
  <div class="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-ifc-darker via-ifc-dark to-ifc-darker">
    <div class="max-w-md w-full">
      <!-- Logo and title -->
      <div class="text-center mb-8">
        <img
          src="/ifc_logo.png"
          alt="IFC Logo"
          class="h-24 w-auto mx-auto mb-6 drop-shadow-lg"
        >
        <h1 class="text-3xl font-bold text-white mb-2">
          Executive Dashboard
        </h1>
        <p class="text-gray-400">
          Sign in with your IFC account
        </p>
      </div>

      <!-- Login card -->
      <div class="widget-card">
        <div v-if="authStore.error" class="mb-4 p-4 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
          {{ authStore.error }}
        </div>

        <div id="google-signin-button" class="flex justify-center mb-4"></div>

        <div v-if="authStore.loading" class="text-center py-4">
          <div class="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-ifc-blue border-r-transparent"></div>
          <p class="text-gray-400 mt-2">Signing in...</p>
        </div>

        <div class="mt-6 text-center text-sm text-gray-500">
          <p>Access restricted to @ifcroofing.com and @ifccontracting.com</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'

const authStore = useAuthStore()
const router = useRouter()

onMounted(() => {
  // Load Google Identity Services library
  const script = document.createElement('script')
  script.src = 'https://accounts.google.com/gsi/client'
  script.async = true
  script.defer = true
  script.onload = initializeGoogleSignIn
  document.head.appendChild(script)
})

function initializeGoogleSignIn() {
  window.google.accounts.id.initialize({
    client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID || 'YOUR_GOOGLE_CLIENT_ID',
    callback: handleCredentialResponse,
    auto_select: false
  })

  window.google.accounts.id.renderButton(
    document.getElementById('google-signin-button'),
    {
      theme: 'filled_black',
      size: 'large',
      width: 300,
      text: 'signin_with',
      shape: 'rectangular'
    }
  )
}

async function handleCredentialResponse(response) {
  const success = await authStore.loginWithGoogle(response.credential)

  if (success) {
    router.push('/')
  }
}
</script>

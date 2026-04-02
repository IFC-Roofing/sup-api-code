import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const token = ref(null)
  const loading = ref(false)
  const error = ref(null)

  const isAuthenticated = computed(() => !!user.value)

  async function loginWithGoogle(googleToken) {
    loading.value = true
    error.value = null

    try {
      const response = await axios.post('/auth/google', {
        token: googleToken
      })

      user.value = response.data.user
      token.value = response.data.token

      // Set default auth header
      axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`

      return true
    } catch (err) {
      error.value = err.response?.data?.detail || 'Login failed'
      return false
    } finally {
      loading.value = false
    }
  }

  async function checkAuth() {
    try {
      const response = await axios.get('/auth/me')
      user.value = response.data
      return true
    } catch (err) {
      user.value = null
      token.value = null
      return false
    }
  }

  async function logout() {
    try {
      await axios.post('/auth/logout')
    } catch (err) {
      console.error('Logout error:', err)
    } finally {
      user.value = null
      token.value = null
      delete axios.defaults.headers.common['Authorization']
    }
  }

  return {
    user,
    token,
    loading,
    error,
    isAuthenticated,
    loginWithGoogle,
    checkAuth,
    logout
  }
})

import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('./components/LoginScreen.vue')
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('./components/DashboardLayout.vue'),
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Auth guard
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth) {
    if (!authStore.isAuthenticated) {
      // Try to restore session
      const authenticated = await authStore.checkAuth()
      if (!authenticated) {
        next('/login')
        return
      }
    }
  }

  next()
})

export default router

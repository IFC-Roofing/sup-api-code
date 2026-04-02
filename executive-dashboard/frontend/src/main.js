import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './styles/tailwind.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('./views/Dashboard.vue') },
    { path: '/login', component: () => import('./views/Login.vue') },
    { path: '/auth/callback', component: () => import('./views/AuthCallback.vue') },
  ],
})

// Auth guard
router.beforeEach(async (to) => {
  if (to.path === '/login' || to.path === '/auth/callback') return true
  try {
    const res = await fetch('/auth/me')
    if (!res.ok) return '/login'
  } catch {
    return '/login'
  }
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('../layouts/AdminLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
        { path: 'org', name: 'org', component: () => import('../views/OrgView.vue') },
        { path: 'templates', name: 'templates', component: () => import('../views/TemplatesView.vue') },
        { path: 'tasks', name: 'tasks', component: () => import('../views/TasksView.vue') },
        { path: 'data', name: 'data', component: () => import('../views/DataView.vue') },
        { path: 'analysis', name: 'analysis', component: () => import('../views/AnalysisView.vue') },
        { path: 'audit', name: 'audit', component: () => import('../views/AuditView.vue') },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach((to) => {
  const loggedIn = Boolean(getToken())
  if (!to.meta.public && !loggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && loggedIn) {
    return { path: '/dashboard' }
  }
  return true
})

export default router

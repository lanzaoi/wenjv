import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { useAuthStore } from '../stores/auth.js';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { guest: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('../views/RegisterView.vue'),
    meta: { guest: true },
  },
  {
    path: '/',
    component: () => import('../views/ShellView.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'chat', component: () => import('../views/ChatView.vue') },
      { path: 'library', name: 'library', component: () => import('../views/LibraryView.vue') },
      { path: 'wiki/:id?', name: 'wiki', component: () => import('../views/WikiView.vue') },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.ready) auth.hydrate();
  if (to.meta['requiresAuth']) {
    if (!auth.token) return { name: 'login', query: { redirect: to.fullPath } };
    const ok = await auth.ensureValid();
    if (!ok) return { name: 'login' };
  }
  if (to.meta['guest'] && auth.token) {
    return { name: 'chat' };
  }
  return true;
});

export default router;

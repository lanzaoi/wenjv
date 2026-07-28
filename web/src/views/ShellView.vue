<template>
  <div class="shell">
    <header class="topnav glass">
      <div class="left">
        <div class="brand">
          <span class="mark" aria-hidden="true"><Icon name="logo" :size="26" /></span>
          <span class="logo">知识库</span>
        </div>
        <nav class="seg nav-seg">
          <router-link to="/" custom v-slot="{ href, navigate, isExactActive }">
            <a :href="href" :class="{ on: isExactActive }" @click="navigate">
              <Icon name="chat" :size="15" />
              对话
            </a>
          </router-link>
          <router-link to="/library" custom v-slot="{ href, navigate, isActive }">
            <a :href="href" :class="{ on: isActive }" @click="navigate">
              <Icon name="library" :size="15" />
              资料库
            </a>
          </router-link>
        </nav>
      </div>
      <div class="right">
        <span class="user-chip" :title="auth.email">
          <Icon name="user" :size="14" />
          <span class="user">{{ auth.email }}</span>
        </span>
        <button class="btn btn-secondary btn-sm logout" type="button" @click="onLogout">
          <Icon name="logout" :size="14" />
          退出
        </button>
      </div>
    </header>
    <main class="main">
      <router-view v-slot="{ Component }">
        <keep-alive :include="['ChatView']">
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import Icon from '../components/Icon.vue'

const auth = useAuthStore()
const router = useRouter()

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<style scoped>
.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}
.topnav {
  height: var(--nav-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px 0 14px;
  position: sticky;
  top: 0;
  z-index: 20;
}
.left {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mark {
  display: grid;
  place-items: center;
  color: var(--text);
  line-height: 0;
}
.logo {
  font-weight: 650;
  font-size: 15px;
  letter-spacing: -0.02em;
}
.nav-seg {
  padding: 3px;
}
.nav-seg a {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  padding: 7px 12px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition:
    background var(--dur-ui) var(--ease-out),
    color var(--dur-ui) var(--ease-out),
    box-shadow var(--dur-ui) var(--ease-out);
}
.nav-seg a:hover {
  text-decoration: none;
  color: var(--text);
}
.nav-seg a.on {
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow-sm);
  font-weight: 560;
}
.right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  color: var(--text-secondary);
  font-size: 13px;
  padding: 5px 10px;
  border-radius: var(--pill);
  background: rgba(0, 0, 0, 0.03);
}
.user {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.logout {
  display: inline-flex;
  gap: 6px;
}
.main {
  flex: 1;
  min-height: 0;
}
</style>

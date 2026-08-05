<template>
  <div class="auth-page">
    <div class="auth-bg" aria-hidden="true" />
    <div class="card auth-card">
      <div class="brand">
        <div class="mark"><Icon name="logo" :size="52" /></div>
        <h1>wenjv</h1>
        <p class="muted">问据 · 笔记 / 文件 / 有引用的问答</p>
      </div>
      <div v-if="error" class="error-banner">
        <Icon name="x" :size="15" />
        <span>{{ error }}</span>
      </div>
      <form @submit.prevent="onSubmit">
        <div class="field">
          <label>邮箱</label>
          <div class="input-wrap">
            <Icon name="mail" :size="16" class="lead" />
            <input
              v-model="email"
              type="email"
              required
              autocomplete="username"
              placeholder="you@example.com"
            />
          </div>
        </div>
        <div class="field">
          <label>密码</label>
          <div class="input-wrap">
            <Icon name="lock" :size="16" class="lead" />
            <input v-model="password" type="password" required autocomplete="current-password" />
          </div>
        </div>
        <button class="btn btn-primary btn-block" type="submit" :disabled="loading">
          <span v-if="loading" class="spinner" />
          <template v-else>
            <Icon name="arrow-right" :size="16" />
            登录
          </template>
        </button>
      </form>
      <p class="foot muted">
        没有账号？
        <router-link to="/register">注册</router-link>
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import Icon from '../components/Icon.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    router.replace(route.query.redirect || '/')
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100%;
  display: grid;
  place-items: center;
  padding: 28px 20px;
  position: relative;
  overflow: hidden;
}
.auth-bg {
  position: absolute;
  inset: -20%;
  background:
    radial-gradient(ellipse 50% 40% at 50% 0%, rgba(0, 113, 227, 0.1), transparent 55%),
    radial-gradient(ellipse 40% 30% at 80% 80%, rgba(0, 0, 0, 0.03), transparent 50%),
    var(--bg);
  pointer-events: none;
}
.auth-card {
  position: relative;
  width: min(400px, 100%);
  padding: 36px 30px 28px;
  animation: banner-in var(--dur-panel) var(--ease-out);
}
.brand {
  text-align: center;
  margin-bottom: 26px;
}
.brand h1 {
  margin: 14px 0 6px;
  font-size: 28px;
  font-weight: 650;
  letter-spacing: -0.03em;
}
.mark {
  width: 52px;
  height: 52px;
  margin: 0 auto;
  color: var(--text);
  filter: drop-shadow(0 8px 24px rgba(0, 0, 0, 0.12));
  line-height: 0;
}
.input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.input-wrap .lead {
  position: absolute;
  left: 12px;
  color: var(--text-tertiary);
  pointer-events: none;
  z-index: 1;
}
.input-wrap input {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 11px 13px 11px 38px;
  outline: none;
  transition:
    border-color var(--dur-ui) var(--ease-out),
    box-shadow var(--dur-ui) var(--ease-out);
}
.input-wrap input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 4px rgba(0, 113, 227, 0.14);
}
.error-banner {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.btn-block {
  display: inline-flex;
  gap: 8px;
}
.foot {
  text-align: center;
  margin-top: 20px;
}
.foot a {
  font-weight: 560;
}
</style>

<template>
  <div class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <h1 class="auth-title">freedom-accounts</h1>
      <p class="auth-sub">账号任务平台 · 管理员登录</p>
      <div>
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" :closable="false" class="page-panel" />
        <el-button class="full-width" size="large" type="primary" native-type="submit" :loading="loading">
          登 录
        </el-button>
      </div>
      <p class="section-hint page-panel">首次登录请使用管理员账号，密码可在系统设置中修改。</p>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { appStore } from '@/stores/app'

const router = useRouter()
const form = reactive({ username: 'admin', password: '' })
const error = ref('')
const loading = ref(false)

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await appStore.login({ ...form })
    form.password = ''
    await router.replace({ name: 'groups' })
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
form.auth-card :deep(.el-form-item__label) {
  flex: 0 0 64px;
  justify-content: flex-start;
}
</style>

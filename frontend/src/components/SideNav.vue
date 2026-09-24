<template>
  <aside class="side-rail">
    <div class="rail-brand">
      <span class="rail-mark">
        <el-icon :size="20"><Cpu /></el-icon>
      </span>
      <span>
        <span class="rail-name">freedom-accounts</span>
        <span class="rail-sub">账号任务平台</span>
      </span>
    </div>

    <nav class="rail-nav">
      <router-link v-for="item in items" :key="item.name" class="rail-item" :to="{ name: item.name }">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="rail-foot">
      <div class="engine-card">
        <div class="engine-head">
          <span>浏览器引擎</span>
          <span class="engine-dot" :class="{ 'is-off': degraded }" :title="engineTip" />
        </div>
        <span>{{ appStore.engineTitle() }}</span>
      </div>
      <div class="head-inline">
        <el-button class="flex-1" @click="appStore.logout()">退出登录</el-button>
        <el-button :icon="isDark ? Sunny : Moon" @click="toggleTheme" />
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { Coin, Connection, Grid, Moon, Setting, Sunny } from '@element-plus/icons-vue'
import { appStore } from '@/stores/app'

const items = [
  { name: 'groups', label: '分组与账号', icon: Grid },
  { name: 'tasks', label: '任务日志', icon: Coin },
  { name: 'proxies', label: '代理管理', icon: Connection },
  { name: 'settings', label: '系统设置', icon: Setting },
]

const isDark = computed(() => appStore.theme === 'dark')
const engine = computed(() => appStore.settings.engine || {})
const degraded = computed(() => engine.value.cloak_available === false)
const engineTip = computed(() => degraded.value ? 'CloakBrowser 不可用，已降级运行' : '指纹引擎正常')

function toggleTheme() {
  const next = isDark.value ? 'light' : 'dark'
  appStore.theme = next
  document.documentElement.classList.toggle('dark', next === 'dark')
  localStorage.setItem('fa_theme', next)
}
</script>

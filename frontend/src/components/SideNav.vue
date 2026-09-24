<template>
  <aside class="side-rail">
    <div class="rail-brand">
      <span class="rail-mark">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 3l7 2.6v5.9c0 4.4-2.9 7.5-7 9.2-4.1-1.7-7-4.8-7-9.2V5.6L12 3Z"
            stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"
          />
          <circle cx="12" cy="10.7" r="2.1" fill="currentColor" />
          <path d="M12 12.8v3.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
      </span>
      <span>
        <span class="rail-name">{{ appStore.siteSettings.site_main_title }}</span>
        <span class="rail-sub">{{ appStore.siteSettings.site_subtitle }}</span>
      </span>
    </div>

    <nav class="rail-nav">
      <router-link v-for="item in items" :key="item.name" class="rail-item" :to="{ name: item.name }">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="rail-foot">
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

function toggleTheme() {
  const next = isDark.value ? 'light' : 'dark'
  appStore.theme = next
  document.documentElement.classList.toggle('dark', next === 'dark')
  localStorage.setItem('fa_theme', next)
}
</script>

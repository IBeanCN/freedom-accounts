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
        <a
          class="github-link"
          href="https://github.com/IBeanCN/freedom-accounts"
          target="_blank"
          rel="noopener noreferrer"
          title="GitHub 项目"
          aria-label="GitHub 项目"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
          </svg>
        </a>
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

<style scoped>
.github-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  background: var(--el-fill-color-blank);
  color: var(--fa-muted);
  transition: color .15s, border-color .15s, background-color .15s;
}

.github-link:hover {
  border-color: var(--el-border-color-hover);
  background: var(--el-fill-color-light);
  color: var(--fa-ink);
}

.github-link svg {
  width: 16px;
  height: 16px;
}

.github-link:focus-visible {
  outline: 2px solid var(--fa-brand);
  outline-offset: 1px;
}
</style>

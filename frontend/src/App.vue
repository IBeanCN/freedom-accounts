<template>
  <router-view v-if="route.name === 'login'" />
  <div v-else-if="appStore.authenticated" class="shell">
    <SideNav />
    <main class="main">
      <header class="topbar">
        <div>
          <h1 class="page-title">{{ route.meta.title }}</h1>
          <p class="page-sub">{{ route.meta.sub }}</p>
        </div>
        <div class="head-inline">
          <slot name="actions" />
        </div>
      </header>
      <div class="content">
        <router-view />
      </div>
    </main>
  </div>
  <div v-else class="empty-state">正在检查登录状态…</div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import SideNav from '@/components/SideNav.vue'
import { appStore } from '@/stores/app'

const route = useRoute()
</script>

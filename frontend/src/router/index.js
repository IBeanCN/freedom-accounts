import { createRouter, createWebHashHistory } from 'vue-router'
import { appStore } from '@/stores/app'

export const router = createRouter({
  history: createWebHashHistory('/static/'),
  routes: [
    { path: '/', redirect: { name: 'groups' } },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { title: '管理员登录' } },
    {
      path: '/groups',
      name: 'groups',
      component: () => import('@/views/GroupsView.vue'),
      meta: { title: '分组与账号', sub: '按分组管理账号与浏览器指纹，一键批量执行账号任务' },
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: () => import('@/views/TasksView.vue'),
      meta: { title: '任务日志', sub: '查看账号任务的执行状态、步骤明细与适配器操作记录' },
    },
    {
      path: '/proxies',
      name: 'proxies',
      component: () => import('@/views/ProxiesView.vue'),
      meta: { title: '代理管理', sub: '维护任务代理：测试连通性、出口 IP 与耗时（ipify）' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { title: '系统设置', sub: '浏览器模式、指纹引擎、日志保留与管理员凭据' },
    },
    { path: '/:pathMatch(.*)*', redirect: { name: 'groups' } },
  ],
})

router.beforeEach((to) => {
  if (to.name !== 'login' && !appStore.authenticated) {
    return { name: 'login' }
  }
  if (to.name === 'login' && appStore.authenticated) {
    return { name: 'groups' }
  }
  return true
})

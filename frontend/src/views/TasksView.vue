<template>
  <div>
    <div class="metrics">
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.total }}</span><span class="metric-label">总任务</span></div>
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.success }}</span><span class="metric-label">成功</span></div>
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.failed }}</span><span class="metric-label">失败</span></div>
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.running }}</span><span class="metric-label">进行中</span></div>
    </div>

    <div class="panel-head">
      <el-radio-group v-model="appStore.taskFilter" @change="load">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="running">运行中</el-radio-button>
        <el-radio-button value="success">已完成</el-radio-button>
        <el-radio-button value="failed">失败</el-radio-button>
      </el-radio-group>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="filteredTasks" empty-text="暂无任务记录。">
        <el-table-column label="任务" width="90">
          <template #default="{ row }"><span class="mono">#{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column label="分组 · 账号" min-width="220">
          <template #default="{ row }">
            <div class="cell-stack">
              <span>{{ row.group_name || `分组 ${row.group_id}` }}</span>
              <span class="cell-sub">{{ row.username || `账号 ${row.account_id}` }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="180">
          <template #default="{ row }">
            <el-tag :type="taskStatusMeta(row).type">{{ taskStatusMeta(row).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="回调" width="120">
          <template #default="{ row }">
            <el-tag :type="callbackMeta(row.callback_status).type">{{ callbackMeta(row.callback_status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="showTask(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <TaskDetailDialog v-model="showDetail" :context="selectedTask" :title="`任务 #${selectedTask?.id || ''} 详情`" :subtitle="detailSubtitle" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import TaskDetailDialog from '@/dialogs/TaskDetailDialog.vue'
import { appStore } from '@/stores/app'
import { fmtTime } from '@/utils/format'
import { callbackMeta, taskStatusMeta } from '@/utils/status'

const loading = ref(false)
const showDetail = ref(false)
const selectedTask = ref(null)

const filteredTasks = computed(() => {
  const status = appStore.taskFilter
  if (!status) return appStore.tasks
  if (status === 'failed') {
    return appStore.tasks.filter((task) => ['failed', 'callback_failed'].includes(task.status))
  }
  if (status === 'running') {
    return appStore.tasks.filter((task) => ['queued', 'running', 'token_queued', 'token_running', 'pending'].includes(task.status))
  }
  return appStore.tasks.filter((task) => task.status === status)
})

const detailSubtitle = computed(() => {
  const task = selectedTask.value
  if (!task) return ''
  return `${task.group_name || '—'} · ${task.username || '—'} · ${fmtTime(task.created_at)}`
})

onMounted(load)

async function load() {
  loading.value = true
  try {
    await appStore.loadTasks()
  } finally {
    loading.value = false
  }
}

function showTask(task) {
  selectedTask.value = task
  showDetail.value = true
}
</script>

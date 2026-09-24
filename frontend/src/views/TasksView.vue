<template>
  <div>
    <div class="metrics">
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.total }}</span><span class="metric-label">总任务</span></div>
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.success }}</span><span class="metric-label">成功</span></div>
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.failed }}</span><span class="metric-label">失败</span></div>
      <div class="metric"><span class="metric-value">{{ appStore.taskMetrics.running }}</span><span class="metric-label">进行中</span></div>
    </div>

    <div class="panel-head">
      <el-radio-group v-model="appStore.taskFilter" @change="changeFilter">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="running">运行中</el-radio-button>
        <el-radio-button value="success">已完成</el-radio-button>
        <el-radio-button value="failed">失败</el-radio-button>
      </el-radio-group>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="appStore.tasks" empty-text="暂无任务记录。">
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
        <el-table-column label="开始时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="结束时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.finished_at) }}</template>
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
      <div class="table-pagination">
        <el-pagination
          :current-page="currentPage"
          :page-size="PAGE_SIZE"
          :total="appStore.taskTotal"
          layout="total, prev, pager, next"
          @current-change="changePage"
        />
      </div>
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
import { taskStatusMeta } from '@/utils/status'

const loading = ref(false)
const showDetail = ref(false)
const selectedTask = ref(null)
const PAGE_SIZE = 20
const currentPage = ref(1)

const detailSubtitle = computed(() => {
  const task = selectedTask.value
  if (!task) return ''
  return `${task.group_name || '—'} · ${task.username || '—'} · ${fmtTime(task.created_at)}`
})

onMounted(load)

async function load() {
  loading.value = true
  try {
    await appStore.loadTasks({
      status: appStore.taskFilter,
      page: currentPage.value,
      pageSize: PAGE_SIZE,
    })
  } finally {
    loading.value = false
  }
}

async function changeFilter() {
  currentPage.value = 1
  await load()
}

async function changePage(page) {
  currentPage.value = page
  await load()
}

function showTask(task) {
  selectedTask.value = task
  showDetail.value = true
}
</script>

<style scoped>
.table-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>

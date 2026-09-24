<template>
  <el-dialog v-model="visible" :title="dialogTitle" width="900px">
    <template #header>
      <div>
        <h3 class="page-title">{{ dialogTitle }}</h3>
        <p class="section-hint">{{ dialogSubtitle }}</p>
      </div>
    </template>
    <div v-loading="loading">
      <template v-if="history">
        <button v-for="task in tasks" :key="task.id" class="hist-row" type="button" @click="showDetail(task)">
          <el-tag :type="statusMeta(task.status).type">{{ statusMeta(task.status).label }}</el-tag>
          <span>任务 #{{ task.id }}</span>
          <span class="section-hint">{{ fmtTime(task.created_at) }}</span>
        </button>
        <div v-if="!tasks.length" class="empty-state">该账号暂无任务记录。</div>
      </template>
      <template v-else-if="task">
        <div class="detail-grid">
          <div class="detail-item"><span class="detail-key">任务编号</span><span class="detail-val mono">#{{ task.id }}</span></div>
          <div class="detail-item">
            <span class="detail-key">状态</span>
            <span><el-tag :type="taskStatusMeta(task).type">{{ taskStatusMeta(task).label }}</el-tag></span>
          </div>
          <div class="detail-item"><span class="detail-key">浏览器模式</span><span class="detail-val">{{ modeText(task.browser_mode) }}</span></div>
          <div class="detail-item">
            <span class="detail-key">回调状态</span>
            <span><el-tag :type="callbackMeta(task.callback_status).type">{{ callbackMeta(task.callback_status).label }}</el-tag></span>
          </div>
          <div class="detail-item"><span class="detail-key">开始时间</span><span class="detail-val">{{ fmtTime(task.started_at) }}</span></div>
          <div class="detail-item"><span class="detail-key">结束时间</span><span class="detail-val">{{ fmtTime(task.finished_at) }}</span></div>
        </div>
        <div v-if="task.error" class="detail-block">
          <span class="detail-block-title">错误信息</span>
          <pre class="detail-response">{{ task.error }}</pre>
        </div>
        <div v-if="steps.length" class="detail-block">
          <span class="detail-block-title">执行步骤</span>
          <ol class="step-list">
            <li v-for="(step, index) in steps" :key="index" :class="{ 'step-error': step.ok === false }">
              {{ step.text }} <span v-if="step.time" class="section-hint">{{ fmtTime(step.time) }}</span>
            </li>
          </ol>
        </div>
        <div v-if="result" class="detail-block">
          <span class="detail-block-title">执行结果</span>
          <pre class="detail-response">{{ JSON.stringify(result, null, 2) }}</pre>
        </div>
        <div v-if="task.callback_response" class="detail-block">
          <span class="detail-block-title">上游回调响应</span>
          <pre class="detail-response">{{ task.callback_response }}</pre>
        </div>
      </template>
    </div>
    <template #footer>
      <el-button v-if="history" @click="closeOrBack">{{ selectedTask ? '返回' : '关闭' }}</el-button>
      <el-button v-else type="primary" @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { fmtTime, modeText, safeJson, isEmpty } from '@/utils/format'
import { callbackMeta, statusMeta, taskStatusMeta } from '@/utils/status'

const props = defineProps({
  modelValue: Boolean,
  title: String,
  subtitle: String,
  history: Boolean,
  tasks: { type: Array, default: () => [] },
  context: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const loading = ref(false)
const task = ref(null)
const steps = ref([])
const result = ref(null)
const selectedTask = ref(null)

const dialogTitle = computed(() => selectedTask.value
  ? `任务 #${selectedTask.value.id} 详情`
  : props.title)
const dialogSubtitle = computed(() => {
  if (selectedTask.value) {
    return `${selectedTask.value.group_name || '—'} · ${selectedTask.value.username || '—'} · ${fmtTime(selectedTask.value.created_at)}`
  }
  return props.subtitle || ''
})

watch(visible, async (open) => {
  selectedTask.value = null
  task.value = null
  steps.value = []
  result.value = null
  if (open && !props.history && props.context?.id) await showDetail(props.context)
})

async function showDetail(listTask) {
  selectedTask.value = listTask
  loading.value = true
  try {
    const detail = await api.get(`/api/tasks/${listTask.id}`)
    task.value = detail
    const parsedSteps = safeJson(detail.steps, [])
    steps.value = Array.isArray(parsedSteps) ? parsedSteps.map(normalizeStep) : []
    const parsedResult = safeJson(detail.result_json, null)
    result.value = isEmpty(parsedResult) ? null : parsedResult
  } finally {
    loading.value = false
  }
}

function normalizeStep(step) {
  if (typeof step === 'string') return { text: step }
  const name = step?.step || step?.name || step?.text || '步骤'
  const detail = step?.detail ?? step?.message ?? ''
  return {
    text: detail && detail !== '-' ? `${name} · ${detail}` : name,
    time: step?.t || step?.time || step?.ts || step?.at || '',
    ok: step?.ok !== false,
  }
}

function closeOrBack() {
  if (selectedTask.value) {
    selectedTask.value = null
    task.value = null
  } else {
    visible.value = false
  }
}
</script>

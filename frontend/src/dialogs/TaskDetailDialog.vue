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
          <div class="task-step-summary">
            <span class="detail-block-title">执行步骤</span>
            <span class="task-step-count">
              共 {{ steps.length }} 步<template v-if="failedStepCount"> · 异常 {{ failedStepCount }} 步</template>
            </span>
          </div>
          <ol class="task-step-list">
            <li
              v-for="(step, index) in steps"
              :key="index"
              class="task-step"
              :class="{ 'is-error': step.ok === false }"
            >
              <time class="task-step-time">{{ fmtTime(step.time) }}</time>
              <span class="task-step-marker" aria-hidden="true"></span>
              <div class="task-step-body">
                <div class="task-step-title-row">
                  <span class="task-step-index">{{ index + 1 }}</span>
                  <span class="task-step-title">{{ stepLabel(step) }}</span>
                  <span v-if="step.ok === false" class="task-step-state">异常</span>
                </div>
                <p v-if="stepDetail(step)" class="task-step-detail">{{ stepDetail(step) }}</p>
              </div>
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

const STEP_LABELS = {
  auth_url: '获取授权链接',
  browser_closed: '浏览器已关闭',
  browser_launched: '浏览器已启动',
  browser_mode: '浏览器模式',
  callback: '获取授权回调',
  callback_timeout: '等待回调超时',
  clear_cookies: '清理 Cookies',
  cpr_unsupported: 'CPR 流程不支持',
  exchange_code: '兑换授权凭证',
  fill_2fa: '填写两步验证',
  fill_email: '填写邮箱',
  fill_password: '填写密码',
  finished: '任务结束',
  fingerprint: '指纹配置',
  fingerprint_detail: '指纹详情',
  goto: '打开授权页',
  phone_verification_auto: '启用自动接码',
  phone_verification_balance: '查询接码余额',
  phone_verification_code_filled: '填写验证码',
  phone_verification_code_received: '收到验证码',
  phone_verification_code_submitted: '提交验证码',
  phone_verification_code_waiting: '等待验证码',
  phone_verification_completed: '手机验证完成',
  phone_verification_confirm_failed: '接码平台确认失败',
  phone_verification_confirmed: '接码平台已确认',
  phone_verification_country: '选择国家',
  phone_verification_dropdown: '打开国家下拉',
  phone_verification_error_wait: '接码异常等待重试',
  phone_verification_fallback: '回退手动验证',
  phone_verification_filled: '填写手机号',
  phone_verification_no_numbers: '无可用号码',
  phone_verification_number_replacement: '更换接码号码',
  phone_verification_order_cancel_failed: '取消接码订单失败',
  phone_verification_order_cancelled: '取消接码订单',
  phone_verification_phone: '获取手机号',
  phone_verification_provider: '调用接码服务',
  phone_verification_sms_only: '确认 SMS 接码',
  phone_verification_submitted: '提交手机号',
  phone_verification_unsupported: '自动接码不支持',
  phone_verification_wait: '等待手动验证',
  proxy: '代理',
  recover_recover_state: '恢复账号状态',
  recover_schedulable: '启用调度',
  session_limit: '会话上限处理',
  stopped: '任务已停止',
  sub2api_unsupported: 'Sub2API 流程不支持',
  task_created: '任务已创建',
  token_refresh_result: 'Token 刷新结果',
  token_refresh_started: '开始刷新 Token',
  upstream_refresh: '上游 Token 刷新',
}

const failedStepCount = computed(() => steps.value.filter(step => step.ok === false).length)

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
  if (typeof step === 'string') return { code: step }
  const name = step?.step || step?.name || ''
  const detail = step?.detail ?? step?.message ?? ''
  return {
    code: name,
    time: step?.t || step?.time || step?.ts || step?.at || '',
    ok: step?.ok !== false,
    detail,
  }
}

function stepLabel(step) {
  if (step.code && STEP_LABELS[step.code]) return STEP_LABELS[step.code]
  return step.code || step.text || '执行步骤'
}

function stepDetail(step) {
  const value = String(step.detail ?? '').trim()
  return value && value !== '-' ? value : ''
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

<style scoped>
.task-step-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
}

.task-step-count {
  color: var(--fa-muted);
  font-size: 12px;
}

.task-step-list {
  max-height: 360px;
  margin: 8px 0 0;
  padding: 2px 2px 2px 0;
  overflow: auto;
  list-style: none;
}

.task-step {
  position: relative;
  display: grid;
  grid-template-columns: 74px 18px minmax(0, 1fr);
  gap: 0 10px;
  align-items: start;
  padding: 8px 0;
}

.task-step:not(:last-child)::before {
  content: "";
  position: absolute;
  top: 30px;
  bottom: -9px;
  left: 92px;
  width: 1px;
  background: var(--fa-line);
}

.task-step-time {
  color: var(--fa-muted);
  font-size: 12px;
  line-height: 20px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.task-step-marker {
  display: block;
  width: 8px;
  height: 8px;
  margin: 6px 0 0 5px;
  border: 1px solid var(--el-color-success);
  border-radius: 50%;
  background: var(--fa-surface);
}

.task-step.is-error .task-step-marker {
  border-color: var(--el-color-danger);
  background: var(--el-color-danger);
}

.task-step-body {
  min-width: 0;
}

.task-step-title-row {
  display: flex;
  gap: 8px;
  align-items: center;
  min-height: 20px;
}

.task-step-index {
  flex: 0 0 20px;
  height: 20px;
  color: var(--fa-muted);
  font-size: 12px;
  line-height: 20px;
  text-align: center;
  border: 1px solid var(--fa-line);
  border-radius: 4px;
}

.task-step-title {
  min-width: 0;
  overflow-wrap: anywhere;
  font-weight: 550;
}

.task-step-state {
  flex: 0 0 auto;
  padding: 0 6px;
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 18px;
  border: 1px solid var(--el-color-danger);
  border-radius: 4px;
}

.task-step-detail {
  margin: 4px 0 0 28px;
  color: var(--fa-muted);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
</style>

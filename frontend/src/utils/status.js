export const STATUS_MAP = {
  success: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  callback_failed: { label: '回调失败', type: 'danger' },
  queued: { label: '任务队列中', type: 'warning' },
  running: { label: '正在执行', type: 'info' },
  token_queued: { label: '刷新Token队列中', type: 'warning' },
  token_running: { label: '正在刷新Token', type: 'info' },
  pending: { label: '排队中', type: 'warning' },
  never: { label: '未运行', type: 'info' },
  cancelled: { label: '已停止', type: 'info' },
}

export const CALLBACK_MAP = {
  ok: { label: '回调成功', type: 'success' },
  failed: { label: '回调失败', type: 'danger' },
  skipped: { label: '已跳过', type: 'warning' },
  none: { label: '未配置', type: 'info' },
}

export function statusMeta(status) {
  return STATUS_MAP[status] || { label: status || '未知', type: 'info' }
}

export function callbackMeta(status) {
  return CALLBACK_MAP[status] || { label: status || '未配置', type: 'info' }
}

export function taskStatusMeta(task) {
  if (task.operation === 'token_refresh' && ['queued', 'running'].includes(task.status)) {
    return statusMeta(`token_${task.status}`)
  }
  return statusMeta(task.status)
}

export function remoteStatusType(status) {
  const map = {
    正常: 'success',
    配额耗尽: 'warning',
    限流中: 'warning',
    退避中: 'warning',
    已停用: 'info',
    错误: 'danger',
  }
  return map[status] || 'info'
}

export const FP_LEVEL_TYPE = {
  高: 'danger',
  中: 'warning',
  低: 'success',
}

export function fpLevel(risk) {
  const value = String(risk || '').replace('风险', '')
  if (value.includes('高')) return '高'
  if (value.includes('中')) return '中'
  return '低'
}

export function fpBadgeMeta(result, checkedAt) {
  const value = String(result || '').trim()
  if (!value) return { label: '未检测', type: 'info' }
  if (value === '检测中') return { label: '检测中', type: 'primary' }
  if (value === '已停止') return { label: '已停止', type: 'info' }
  const [risk, score] = value.split('/')
  const level = fpLevel(risk)
  return {
    label: score ? `${level}风险/${score}` : `${level}风险`,
    type: FP_LEVEL_TYPE[level] || 'info',
    tip: checkedAt ? `${level}风险/${score || ''} · ${checkedAt}` : `${level}风险/${score || ''}`,
  }
}

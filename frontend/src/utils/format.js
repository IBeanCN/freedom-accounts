export function modeText(mode) {
  if (mode === 'headed') return '有头'
  if (mode === 'headless') return '无头'
  return '跟随系统'
}

const DEFAULT_TIME_FORMAT = 'yyyy-MM-dd HH:mm:ss'

function toDate(value) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value === 'number' || typeof value === 'bigint') {
    const timestamp = Number(value)
    const date = new Date(timestamp < 100_000_000_000 ? timestamp * 1000 : timestamp)
    return Number.isNaN(date.getTime()) ? null : date
  }

  const text = String(value).trim()
  if (!text) return null
  if (/^[+-]?\d+$/.test(text)) return toDate(Number(text))
  const date = new Date(/^\d{4}-\d{2}-\d{2} /.test(text) ? text.replace(' ', 'T') : text)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatTimestamp(value, format = DEFAULT_TIME_FORMAT) {
  const date = toDate(value)
  if (!date) return '—'

  const parts = new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  const tokens = {
    yyyy: 'year',
    YYYY: 'year',
    MM: 'month',
    dd: 'day',
    HH: 'hour',
    mm: 'minute',
    ss: 'second',
  }

  return String(format).replace(
    /yyyy|YYYY|MM|dd|HH|mm|ss/g,
    token => values[tokens[token]] ?? token,
  )
}

export function fmtTime(value, format = DEFAULT_TIME_FORMAT) {
  return formatTimestamp(value, format)
}

export function fmtStepTime(value) {
  return fmtTime(value, 'HH:mm:ss')
}

export function safeJson(value, fallback) {
  if (value == null || value === '') return fallback
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return fallback
  }
}

export function isEmpty(value) {
  if (!value) return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value).length === 0
  return false
}

export function displayUrl(url) {
  return String(url || '').replace(/^https?:\/\//, '')
}

export function trimAccountTail(value) {
  return String(value ?? '').trim().replace(/[^\w@.%+-]+$/g, '')
}

export function trimTotpTail(value) {
  return String(value ?? '').trim().replace(/[^A-Za-z2-7=]+$/g, '')
}

const ENGINE_LABEL = {
  cloakbrowser: 'CloakBrowser',
  playwright: 'Playwright Chromium',
  chromium: 'Chromium',
}

export function engineLabel(id) {
  if (!id) return '未知'
  return ENGINE_LABEL[String(id).toLowerCase()] || String(id)
}

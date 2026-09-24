export function modeText(mode) {
  if (mode === 'headed') return '有头'
  if (mode === 'headless') return '无头'
  return '跟随系统'
}

export function fmtTime(value) {
  if (!value) return '—'
  const text = String(value).replace('T', ' ')
  return text.length > 16 ? text.slice(0, 16) : text
}

export function fmtStepTime(value) {
  if (!value) return '—'
  const text = String(value).replace('T', ' ')
  return text.match(/(\d{2}:\d{2}:\d{2})/)?.[1] || text
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

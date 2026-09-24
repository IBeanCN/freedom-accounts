export const FP_FALLBACK = {
  platforms: ['windows', 'macos'],
  brands: ['Chrome', 'Edge', 'Opera', 'Vivaldi'],
  brand_versions: Array.from({ length: 22 }, (_, index) => 130 + index),
  gpus: {
    windows: [{
      vendor: 'Google Inc. (Intel)',
      renderer: 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      label: 'Intel UHD 630',
    }],
    macos: [{
      vendor: 'Google Inc. (Apple)',
      renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)',
      label: 'Apple M1',
    }],
  },
  screens: {
    windows: [{ width: 1920, height: 1080 }],
    macos: [{ width: 1440, height: 900 }],
  },
  cores: { windows: [8], macos: [8] },
  memory: [4, 8],
  timezones: ['Asia/Shanghai', 'Asia/Tokyo', 'America/New_York', 'America/Chicago', 'Europe/London', 'Europe/Berlin', 'Asia/Singapore', 'America/Los_Angeles'],
  locales: ['zh-CN', 'en-US', 'en-GB', 'ja-JP', 'ko-KR', 'de-DE'],
}

export const FP_FIELD_LABEL = {
  seed: '种子 seed',
  platform: '平台',
  brand: '品牌',
  brand_version: '浏览器版本',
  screen_width: '屏幕宽',
  screen_height: '屏幕高',
  timezone: '时区',
  locale: '语言',
  hardware_concurrency: 'CPU 核心',
  device_memory: '内存',
  gpu_vendor: 'WebGL 厂商',
  gpu_renderer: 'WebGL 渲染器',
  webrtc_ip: 'WebRTC IP',
  storage_quota_mb: '存储配额',
  noise: '指纹噪声',
  user_agent: 'User Agent',
  viewport_w: '视口宽',
  viewport_h: '视口高',
  geoip: 'GeoIP',
}

export function fpOptions(meta) {
  return meta?.fp_options || FP_FALLBACK
}

export function optionsWithCurrent(items, current, toValue = (item) => String(item)) {
  const values = new Set(items.map((item) => toValue(item)))
  return current && !values.has(String(current))
    ? [{ value: String(current), label: `${current}（存量）` }, ...items.map((item) => ({ value: toValue(item), label: String(item) }))]
    : items.map((item) => ({ value: toValue(item), label: String(item) }))
}

export function screenValue(fp) {
  return fp?.screen_width && fp?.screen_height ? `${fp.screen_width}x${fp.screen_height}` : ''
}

export function randomFp(meta) {
  const options = fpOptions(meta)
  const pick = (items) => items[Math.floor(Math.random() * items.length)]
  const platform = pick(options.platforms)
  const gpu = pick(options.gpus[platform] || [])
  const screen = pick(options.screens[platform] || [])
  return {
    seed: Math.floor(Math.random() * 1e9),
    platform,
    brand: pick(options.brands),
    brand_version: pick(options.brand_versions || []),
    gpu_renderer: gpu.renderer,
    screen_width: screen.width,
    screen_height: screen.height,
    timezone: pick(options.timezones),
    locale: pick(options.locales),
    hardware_concurrency: pick(options.cores[platform] || []),
    device_memory: pick(options.memory),
    webrtc_ip: 'auto',
    noise: true,
    geoip: true,
  }
}

function normalized(value) {
  return value === undefined || value === null ? '' : String(value).trim()
}

export function fpChangedFields(oldFp, newFp) {
  const keys = new Set([...Object.keys(oldFp || {}), ...Object.keys(newFp || {})])
  return [...keys].filter((key) => normalized(oldFp?.[key]) !== normalized(newFp?.[key]))
    .map((key) => FP_FIELD_LABEL[key] || key)
}

export const FP_FALLBACK = {
  platforms: ['windows', 'macos'],
  brands: ['Chrome', 'Edge', 'Opera', 'Vivaldi'],
  brand_versions: Array.from({ length: 22 }, (_, index) => 130 + index),
  gpus: {
    windows: [
      { vendor: 'Google Inc. (Intel)', renderer: 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)', label: 'Intel UHD 630' },
      { vendor: 'Google Inc. (Intel)', renderer: 'ANGLE (Intel, Intel(R) Arc(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)', label: 'Intel Arc Graphics' },
      { vendor: 'Google Inc. (Intel)', renderer: 'ANGLE (Intel, Intel(R) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)', label: 'Intel Graphics' },
      { vendor: 'Google Inc. (NVIDIA)', renderer: 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)', label: 'GeForce GTX 1660' },
      { vendor: 'Google Inc. (NVIDIA)', renderer: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4050 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)', label: 'GeForce RTX 4050 Laptop GPU' },
      { vendor: 'Google Inc. (NVIDIA)', renderer: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)', label: 'GeForce RTX 4060 Laptop GPU' },
    ],
    macos: [
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)', label: 'Apple M1' },
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)', label: 'Apple M2' },
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)', label: 'Apple M3' },
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)', label: 'Apple M4' },
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M5, Unspecified Version)', label: 'Apple M5' },
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Pro, Unspecified Version)', label: 'Apple M5 Pro' },
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Max, Unspecified Version)', label: 'Apple M5 Max' },
      { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M6, Unspecified Version)', label: 'Apple M6' },
    ],
  },
  screens: {
    windows: [
      { width: 1920, height: 1080 },
      { width: 1920, height: 1200 },
      { width: 2880, height: 1800 },
      { width: 3200, height: 2000 },
      { width: 3840, height: 2400 },
    ],
    macos: [
      { width: 1440, height: 900 },
      { width: 2560, height: 1664 }, // MacBook Air 13-inch
      { width: 2880, height: 1864 }, // MacBook Air 15-inch
      { width: 3024, height: 1964 }, // MacBook Pro 14-inch
      { width: 3456, height: 2234 }, // MacBook Pro 16-inch
    ],
  },
  cores: { windows: [4, 6, 8, 12, 16], macos: [8, 10, 12, 15, 18] },
  memory: {
    macos: [8, 16, 24, 32, 36, 48, 64, 128],
    windows: [8, 16, 24, 32, 64, 128],
  },
  timezones: ['Asia/Shanghai', 'Asia/Tokyo', 'America/New_York', 'America/Chicago', 'Europe/London', 'Europe/Berlin', 'Asia/Singapore', 'America/Los_Angeles'],
  locales: ['zh-CN', 'en-US', 'en-GB', 'ja-JP', 'ko-KR', 'de-DE'],
}

// 设备方案：每条对应一台在售机型的标准配置。
// memory 取该机型的真实统一内存 / 物理内存档位，且必须落在上面 memory 池内，
// 否则表单下拉会退化成「N（存量）」。改动机型时三处同步：本数组、FP_FALLBACK.memory、
// 后端 fingerprint.py 的 _MEMORY。
export const FP_DEVICE_PROFILES = [
  {
    value: 'macbook-air-13-m5',
    label: 'MacBook Air 13 英寸 · M5',
    platform: 'macos',
    gpu: 'Apple M5',
    screen: [2560, 1664],
    cores: 10,
    memory: 16, // 统一内存 16/24/32，标配 16GB
  },
  {
    value: 'macbook-air-15-m5',
    label: 'MacBook Air 15 英寸 · M5',
    platform: 'macos',
    gpu: 'Apple M5',
    screen: [2880, 1864],
    cores: 10,
    memory: 16, // 统一内存 16/24/32，标配 16GB
  },
  {
    value: 'macbook-pro-14-m6',
    label: 'MacBook Pro 14 英寸 · M6',
    platform: 'macos',
    gpu: 'Apple M6',
    screen: [3024, 1964],
    cores: 12,
    memory: 16, // 统一内存 16/24/32，标配 16GB
  },
  {
    value: 'macbook-pro-16-m5-pro',
    label: 'MacBook Pro 16 英寸 · M5 Pro',
    platform: 'macos',
    gpu: 'Apple M5 Pro',
    screen: [3456, 2234],
    cores: 15,
    memory: 24, // 统一内存 24/48/64，标配 24GB
  },
  {
    value: 'macbook-pro-16-m5-max',
    label: 'MacBook Pro 16 英寸 · M5 Max',
    platform: 'macos',
    gpu: 'Apple M5 Max',
    screen: [3456, 2234],
    cores: 18,
    memory: 36, // 统一内存 36/48/64/128，32 核 GPU 机型标配 36GB
  },
  {
    value: 'dell-xps-13-9350',
    label: 'Dell XPS 13 · 9350',
    platform: 'windows',
    gpu: 'Intel Arc Graphics',
    screen: [1920, 1200],
    cores: 8,
    memory: 16, // LPDDR5x 16/32，主销 16GB
  },
  {
    value: 'dell-xps-14-9440',
    label: 'Dell XPS 14 · 9440',
    platform: 'windows',
    gpu: 'Intel Arc Graphics',
    screen: [1920, 1200],
    cores: 16,
    memory: 32, // LPDDR5x 16/32/64，Ultra 7 155H 主销 32GB
  },
  {
    value: 'dell-xps-16-9640',
    label: 'Dell XPS 16 · 9640',
    platform: 'windows',
    gpu: 'GeForce RTX 4060 Laptop GPU',
    screen: [3840, 2400],
    cores: 16,
    memory: 32, // DDR5 16/32/64，RTX 4060 机型主销 32GB
  },
  {
    value: 'thinkpad-x1-carbon-gen13',
    label: 'ThinkPad X1 Carbon · Gen 13',
    platform: 'windows',
    gpu: 'Intel Arc Graphics',
    screen: [2880, 1800],
    cores: 8,
    memory: 32, // LPDDR5x 16/32，商务标配 32GB
  },
  {
    value: 'thinkpad-t14-gen6',
    label: 'ThinkPad T14 · Gen 6',
    platform: 'windows',
    gpu: 'Intel Graphics',
    screen: [1920, 1200],
    cores: 12,
    memory: 16, // DDR5 插槽 16/32/64，企业批量配置 16GB
  },
  {
    value: 'thinkpad-x1-yoga-gen9',
    label: 'ThinkPad X1 Yoga · Gen 9',
    platform: 'windows',
    gpu: 'Intel Graphics',
    screen: [1920, 1200],
    cores: 12,
    memory: 16, // LPDDR5x 16/32，主销 16GB
  },
  {
    value: 'windows-laptop-intel',
    label: 'Windows 笔记本 · Intel UHD',
    platform: 'windows',
    gpu: 'Intel UHD 630',
    screen: [1920, 1080],
    cores: 8,
    memory: 16, // DDR4 8/16，UHD 630 平台主销 16GB
  },
]

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

// 种子区间与引擎自身口径一致：SDK 用 random.randint(10000, 99999) 生成，
// 引擎按 seed 确定性派生 canvas / WebGL / audio / 字体噪声。
export const FP_SEED_MIN = 10000
export const FP_SEED_MAX = 99999

export function randomSeed() {
  return FP_SEED_MIN + Math.floor(Math.random() * (FP_SEED_MAX - FP_SEED_MIN + 1))
}

// 返回空串表示合法；留空（由运行环境随机）也视为合法。
export function seedError(value) {
  if (value === undefined || value === null || value === '') return ''
  const num = Number(value)
  if (!Number.isInteger(num)) return '种子 seed 需为整数'
  if (num < FP_SEED_MIN || num > FP_SEED_MAX) {
    return `种子 seed 需在 ${FP_SEED_MIN}–${FP_SEED_MAX} 之间`
  }
  return ''
}

// ---- 指纹导入 / 导出 ----
// 导出为与库内同构的 JSON（不含包装字段时也能被其他工具直接读），
// 导入只接受 FINGERPRINT 已知字段并做类型收敛，未知键丢弃、非法值跳过。

export const FP_FILE_KIND = 'freedom-accounts/fingerprint'
export const FP_FILE_VERSION = 1

const FP_NUMBER_FIELDS = new Set([
  'seed', 'brand_version', 'hardware_concurrency', 'device_memory',
  'screen_width', 'screen_height', 'storage_quota_mb', 'viewport_w', 'viewport_h',
])
const FP_BOOLEAN_FIELDS = new Set(['noise', 'geoip'])

// 只挑已知字段，保持 FP_FIELD_LABEL 的字段顺序，便于人工核对与 diff。
export function fingerprintExport(fp) {
  const out = {}
  for (const key of Object.keys(FP_FIELD_LABEL)) {
    const value = fp?.[key]
    if (value === undefined || value === null || value === '') continue
    out[key] = value
  }
  return out
}

export function fingerprintFile(fp) {
  return {
    kind: FP_FILE_KIND,
    version: FP_FILE_VERSION,
    exported_at: new Date().toISOString(),
    fingerprint: fingerprintExport(fp),
  }
}

function coerceFingerprintField(key, value) {
  if (FP_NUMBER_FIELDS.has(key)) {
    const num = typeof value === 'boolean' ? Number.NaN : Number(value)
    if (!Number.isFinite(num)) return undefined
    if (key === 'seed' ? num < 0 : num <= 0) return undefined
    return num
  }
  if (FP_BOOLEAN_FIELDS.has(key)) {
    if (typeof value === 'boolean') return value
    if (value === 'true' || value === 1) return true
    if (value === 'false' || value === 0) return false
    return undefined
  }
  const text = typeof value === 'string' ? value.trim() : ''
  return text || undefined
}

// 接受三种输入：导出文件、裸指纹对象、`{ fingerprint: {...} }` 包装。
export function parseFingerprintInput(text) {
  let raw = text
  if (typeof text === 'string') {
    try {
      raw = JSON.parse(text)
    } catch {
      throw new Error('不是合法的 JSON 文件')
    }
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('文件内容不是指纹对象')
  }
  if (raw.fingerprint && typeof raw.fingerprint === 'object' && !Array.isArray(raw.fingerprint)) {
    raw = raw.fingerprint
  }

  const fingerprint = {}
  let ignored = 0
  for (const [key, value] of Object.entries(raw)) {
    if (!(key in FP_FIELD_LABEL)) {
      ignored += 1
      continue
    }
    const coerced = coerceFingerprintField(key, value)
    if (coerced === undefined) {
      ignored += 1
      continue
    }
    fingerprint[key] = coerced
  }
  if (Object.keys(fingerprint).length === 0) throw new Error('文件里没有可识别的指纹字段')
  const seedIssue = seedError(fingerprint.seed)
  if (seedIssue) throw new Error(`${seedIssue}（文件中的值为 ${fingerprint.seed}）`)
  return { fingerprint, ignored }
}

// 文件名带平台与时间，便于多设备间区分同名文件。
export function fingerprintFileName(fp, now = new Date()) {
  const pad = (value) => String(value).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
    + `-${pad(now.getHours())}${pad(now.getMinutes())}`
  const platform = fp?.platform === 'macos' || fp?.platform === 'windows' ? fp.platform : 'custom'
  return `fingerprint-${platform}-${stamp}.json`
}

// 内存池按平台取（Mac 统一内存档位 / Windows 物理内存档位）。
// 兼容旧版下发的扁平数组，避免滚动升级期间下拉变空。
export function memoryPool(options, platform) {
  const pool = options?.memory
  if (Array.isArray(pool)) return pool
  return pool?.[platform] || []
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
    seed: randomSeed(),
    platform,
    brand: pick(options.brands),
    brand_version: pick(options.brand_versions || []),
    gpu_renderer: gpu.renderer,
    screen_width: screen.width,
    screen_height: screen.height,
    timezone: pick(options.timezones),
    locale: pick(options.locales),
    hardware_concurrency: pick(options.cores[platform] || []),
    device_memory: pick(memoryPool(options, platform)),
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

<template>
  <div class="fp-fields">
    <div class="head-inline fp-toolbar">
      <el-button text size="small" @click="triggerImport">导入指纹</el-button>
      <el-button text size="small" @click="exportFingerprint">导出指纹</el-button>
      <input ref="fileInput" class="fp-file" type="file" accept="application/json,.json" @change="handleFile" />
    </div>
    <div class="form-grid">
      <el-form-item v-if="showSeed" label="种子 seed" :error="seedFieldError">
        <div class="fp-seed-row">
          <el-input-number v-model="seed" :controls="false" :precision="0" :step="1" />
          <el-button text size="small" :disabled="!canPickSeed" @click="fillRandomSeed">随机</el-button>
          <el-button
            text
            size="small"
            :disabled="!canPickSeed || !accountId"
            :loading="readingSeed"
            @click="readLastSeed"
          >读取上次</el-button>
        </div>
        <div class="section-hint">5 位数字（10000–99999）；种子已配置时需先清空才能重新取值。</div>
      </el-form-item>
      <el-form-item label="配置方式">
        <el-radio-group v-model="configMode" size="small">
          <el-radio-button value="custom">自定义</el-radio-button>
          <el-radio-button value="device">设备方案</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="configMode === 'device'" label="设备方案">
        <el-select v-model="deviceProfile" clearable filterable @change="applyDeviceProfile">
          <el-option v-for="item in deviceProfiles" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
        <div class="section-hint">选择方案会填充下方字段，填充后仍可逐项修改。</div>
      </el-form-item>
      <el-form-item label="平台 platform">
        <el-select v-model="platform" clearable>
          <el-option v-for="item in platformOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="品牌 brand">
        <el-select v-model="brand" clearable filterable>
          <el-option v-for="item in brandOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="屏幕分辨率">
        <el-select v-model="screen" clearable filterable>
          <el-option v-for="item in screenOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="时区">
        <el-select v-model="timezone" clearable filterable>
          <el-option v-for="item in timezoneOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="语言">
        <el-select v-model="locale" clearable filterable>
          <el-option v-for="item in localeOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="CPU 核心">
        <el-select v-model="cores" clearable filterable>
          <el-option v-for="item in coreOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="内存 (GB)">
        <el-select v-model="memory" clearable filterable>
          <el-option v-for="item in memoryOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="GPU 机型">
        <el-select v-model="gpu" clearable filterable>
          <el-option v-for="item in gpuOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
        <div class="section-hint">厂商随 GPU 机型自动写入</div>
      </el-form-item>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import {
  FP_DEVICE_PROFILES,
  fingerprintExport,
  fingerprintFile,
  fingerprintFileName,
  fpOptions,
  memoryPool,
  optionsWithCurrent,
  parseFingerprintInput,
  randomSeed,
  screenValue,
  seedError,
} from '@/utils/fingerprint'
import { api } from '@/api/client'
import { appStore } from '@/stores/app'

const props = defineProps({
  modelValue: { type: Object, required: true },
  showSeed: { type: Boolean, default: false },
  // 库里已存的 seed。存量账号可能持有 5 位以外的旧种子，原值原样保留不报错，
  // 只拦本次新写入的值，避免打开编辑弹窗就变成不可保存。
  originalSeed: { type: [Number, String], default: undefined },
  // 当前编辑的账号 id；新建账号时为空，读取「上次启动 seed」不可用。
  accountId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue'])
const options = computed(() => fpOptions(appStore.meta))
const configMode = ref('custom')
const deviceProfile = ref('')
const deviceProfiles = FP_DEVICE_PROFILES

function patch(value) {
  emit('update:modelValue', { ...props.modelValue, ...value })
}

const fileInput = ref(null)
const readingSeed = ref(false)
// 两个取种子的按钮只在「尚未配置种子」时可用：种子一旦定下就是身份，
// 允许随手覆盖等于随手换一台机器。
const canPickSeed = computed(() => !props.modelValue.seed)

function fillRandomSeed() {
  if (!canPickSeed.value) return
  patch({ seed: randomSeed() })
}

// 取上一次浏览器启动实际使用的 seed；读不到就退回旧值，旧值也没有则随机。
async function readLastSeed() {
  if (!canPickSeed.value || !props.accountId) return
  readingSeed.value = true
  try {
    const data = await api.get(`/api/accounts/${props.accountId}/last-seed`)
    if (data?.seed) {
      patch({ seed: Number(data.seed) })
      ElMessage.success(`已读取上次启动的 seed ${data.seed}`)
      return
    }
  } catch {
    // 读不到就继续走兜底，不打断用户
  } finally {
    readingSeed.value = false
  }
  if (props.originalSeed) {
    patch({ seed: Number(props.originalSeed) })
    ElMessage.info('没有启动记录，已保留原种子')
    return
  }
  patch({ seed: randomSeed() })
  ElMessage.info('没有启动记录，已生成新种子')
}
const seedFieldError = computed(() => (
  props.modelValue.seed === props.originalSeed ? '' : seedError(props.modelValue.seed)
))

function validateSeed() {
  const message = seedFieldError.value
  if (!message) return true
  ElMessage.error(message)
  return false
}

defineExpose({ validateSeed })

function triggerImport() {
  fileInput.value?.click()
}

// 导出当前表单里的整套指纹（含 seed），用于在另一台设备复现同一指纹。
function exportFingerprint() {
  const fingerprint = fingerprintExport(props.modelValue)
  if (!Object.keys(fingerprint).length) {
    ElMessage.warning('当前没有可导出的指纹配置')
    return
  }
  const blob = new Blob([`${JSON.stringify(fingerprintFile(fingerprint), null, 2)}\n`], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fingerprintFileName(fingerprint)
  // 挂进文档再点：部分浏览器对游离节点的 click() 不触发下载。
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
  ElMessage.success('指纹已导出为 JSON 文件')
}

async function handleFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const { fingerprint, ignored } = parseFingerprintInput(await file.text())
    // 整体替换而非合并：导入的目标是让两台设备指纹完全一致。
    emit('update:modelValue', fingerprint)
    // 导入后不再对应任何预置方案，清掉选中项避免方案名与实际值矛盾。
    deviceProfile.value = ''
    const count = Object.keys(fingerprint).length
    ElMessage.success(ignored ? `已导入 ${count} 项，忽略 ${ignored} 个无效字段` : `已导入 ${count} 项指纹`)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function applyDeviceProfile(value) {
  const profile = deviceProfiles.find((item) => item.value === value)
  if (!profile) return
  const gpu = (options.value.gpus[profile.platform] || []).find((item) => item.label === profile.gpu)
  patch({
    platform: profile.platform,
    gpu_renderer: gpu?.renderer,
    screen_width: profile.screen[0],
    screen_height: profile.screen[1],
    hardware_concurrency: profile.cores,
    device_memory: profile.memory,
  })
}

const seed = computed({
  get: () => props.modelValue.seed,
  set: (value) => patch({ seed: value == null || value === '' ? undefined : Number(value) }),
})
const platform = computed({
  get: () => props.modelValue.platform || '',
  set: (value) => patch({ platform: value || undefined }),
})
const brand = computed({
  get: () => props.modelValue.brand || '',
  set: (value) => patch({ brand: value || undefined }),
})
const screen = computed({
  get: () => screenValue(props.modelValue),
  set: (value) => {
    if (!value) {
      patch({ screen_width: undefined, screen_height: undefined })
      return
    }
    const [width, height] = String(value).split('x').map(Number)
    patch({ screen_width: width, screen_height: height })
  },
})
const timezone = computed({
  get: () => props.modelValue.timezone || '',
  set: (value) => patch({ timezone: value || undefined }),
})
const locale = computed({
  get: () => props.modelValue.locale || '',
  set: (value) => patch({ locale: value || undefined }),
})
const cores = computed({
  get: () => props.modelValue.hardware_concurrency,
  set: (value) => patch({ hardware_concurrency: value ? Number(value) : undefined }),
})
const memory = computed({
  get: () => props.modelValue.device_memory,
  set: (value) => patch({ device_memory: value ? Number(value) : undefined }),
})
const gpu = computed({
  get: () => props.modelValue.gpu_renderer || '',
  set: (value) => patch({ gpu_renderer: value || undefined }),
})

const platformOptions = computed(() => optionsWithCurrent(options.value.platforms, props.modelValue.platform))
const brandOptions = computed(() => optionsWithCurrent(options.value.brands, props.modelValue.brand))
const timezoneOptions = computed(() => optionsWithCurrent(options.value.timezones, props.modelValue.timezone))
const localeOptions = computed(() => optionsWithCurrent(options.value.locales, props.modelValue.locale))

const platformKey = computed(() => props.modelValue.platform || 'windows')
const gpuOptions = computed(() => (options.value.gpus[platformKey.value] || []).map((item) => ({
  value: item.renderer,
  label: item.label,
})))
const screenOptions = computed(() => (options.value.screens[platformKey.value] || []).map((item) => ({
  value: `${item.width}x${item.height}`,
  label: `${item.width} × ${item.height}`,
})))
const coreOptions = computed(() => (options.value.cores[platformKey.value] || []).map((item) => ({
  value: String(item),
  label: `${item} 核`,
})))
// 内存档位随平台切换：Mac 只给统一内存档位，Windows 只给物理内存档位。
const memoryOptions = computed(() => optionsWithCurrent(
  memoryPool(options.value, platformKey.value),
  props.modelValue.device_memory,
))
</script>

<style scoped>
.fp-toolbar {
  justify-content: flex-end;
  margin-bottom: 6px;
}

.fp-file {
  display: none;
}

.fp-seed-row {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}

.fp-seed-row :deep(.el-input-number) {
  flex: 1;
  min-width: 0;
}
</style>

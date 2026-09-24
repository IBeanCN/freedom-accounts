<template>
  <div class="form-grid">
    <el-form-item v-if="showSeed" label="种子 seed">
      <el-input-number v-model="seed" class="full-width" :controls="false" />
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
</template>

<script setup>
import { computed } from 'vue'
import { fpOptions, optionsWithCurrent, screenValue } from '@/utils/fingerprint'
import { appStore } from '@/stores/app'

const props = defineProps({
  modelValue: { type: Object, required: true },
  showSeed: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])
const options = computed(() => fpOptions(appStore.meta))

function patch(value) {
  emit('update:modelValue', { ...props.modelValue, ...value })
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
const memoryOptions = computed(() => optionsWithCurrent(options.value.memory, props.modelValue.device_memory))

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
</script>

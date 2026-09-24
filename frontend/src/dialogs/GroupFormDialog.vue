<template>
  <el-dialog v-model="visible" :title="editing ? `编辑分组 #${editing.id}` : '新建分组'" width="860px" destroy-on-close>
    <el-form class="dialog-form" label-position="top" :model="form">
      <div class="form-grid">
        <el-form-item label="分组类型" required>
          <el-select v-model="form.group_type" filterable @change="changeGroupType">
            <el-option v-for="item in appStore.meta.group_types" :key="item.key" :value="item.key" :label="item.label" />
            <el-option v-if="legacyType" :value="form.group_type" :label="`${form.group_type}（存量）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="分组名称" required>
          <el-input v-model="form.name" placeholder="如 OpenAI 主力池" />
        </el-form-item>
        <el-form-item label="任务类型" required>
          <el-select v-model="form.login_type" filterable>
            <el-option v-for="item in appStore.meta.login_types" :key="item.key" :value="item.key" :label="item.label" />
            <el-option v-if="legacyAdapter" :value="form.login_type" :label="`${form.login_type}（存量）`" />
          </el-select>
          <div class="section-hint">{{ adapterHint }}</div>
        </el-form-item>
        <el-form-item label="任务地址" required>
          <el-input v-model="form.login_url" :placeholder="urlHint" />
          <div class="section-hint">{{ platformHint }}</div>
        </el-form-item>
        <el-form-item label="任务 Key（上游鉴权，可选）" class="full-width">
          <el-input v-model="form.upstream_key" placeholder="适配器请求上游时自动携带" />
        </el-form-item>
        <el-form-item label="并发数量">
          <el-input-number v-model="form.concurrency" :min="1" :controls="false" class="full-width" />
        </el-form-item>
        <el-form-item label="间隔下限 (ms)">
          <el-input-number v-model="form.interval_min_ms" :min="0" :controls="false" class="full-width" />
        </el-form-item>
        <el-form-item label="间隔上限 (ms)">
          <el-input-number v-model="form.interval_max_ms" :min="0" :controls="false" class="full-width" />
        </el-form-item>
        <el-form-item label="浏览器模式">
          <el-select v-model="form.browser_mode">
            <el-option value="inherit" label="跟随系统" />
            <el-option value="headless" label="无头" />
            <el-option value="headed" label="有头" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联代理（分组默认，账号可覆盖）">
          <el-select v-model="form.proxy_id" clearable filterable>
            <el-option value="" label="不使用代理（直连）" />
            <el-option v-for="item in appStore.proxyOptions" :key="item.value" :value="item.value" :label="item.label" />
            <el-option v-if="legacyProxy" :value="form.proxy_id" :label="`${form.proxy_id}（存量）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="接码平台（账号可覆盖）">
          <el-select v-model="form.phone_platform" filterable>
            <el-option value="" label="跟随系统" />
            <el-option value="hero_sms" label="HeroSMS" />
            <el-option v-if="legacyPhonePlatform" :value="form.phone_platform" :label="`${form.phone_platform}（存量）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="指纹检测站点（可选，覆盖系统设置）">
          <el-input v-model="form.fp_check_url" placeholder="留空使用系统设置地址" />
        </el-form-item>
      </div>

      <el-divider>指纹模板</el-divider>
      <div class="head-inline page-panel">
        <el-button @click="fillRandom">随机一套</el-button>
        <el-button @click="fillGeo">回填时区</el-button>
        <el-button text @click="form.fingerprint_template = {}">清空</el-button>
        <span class="section-hint">组内账号默认继承（seed 每账号自动随机）；统一机型场景必填，留空则每账号全随机</span>
      </div>
      <FingerprintFields v-model="form.fingerprint_template" />
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import FingerprintFields from '@/components/FingerprintFields.vue'
import { appStore } from '@/stores/app'
import { fpChangedFields, randomFp } from '@/utils/fingerprint'

const props = defineProps({
  modelValue: Boolean,
  editing: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const saving = ref(false)
const form = reactive(createForm(null))

const legacyType = computed(() => props.editing && form.group_type
  && !appStore.meta.group_types.some((item) => item.key === form.group_type))
const legacyAdapter = computed(() => props.editing && form.login_type
  && !appStore.meta.login_types.some((item) => item.key === form.login_type))
const legacyProxy = computed(() => Boolean(props.editing?.proxy_id)
  && !appStore.proxies.some((item) => item.id === props.editing.proxy_id))
const legacyPhonePlatform = computed(() => Boolean(props.editing?.phone_platform)
  && props.editing.phone_platform !== 'hero_sms')
const platformMeta = computed(() => appStore.meta.group_types.find((item) => item.key === form.group_type))
const adapterMeta = computed(() => appStore.meta.login_types.find((item) => item.key === form.login_type))
const urlHint = computed(() => platformMeta.value?.login_url_hint || 'https://...')
const platformHint = computed(() => platformMeta.value?.description || '')
const adapterHint = computed(() => adapterMeta.value?.description || '')

function createForm(group) {
  return {
    group_type: group?.group_type || '',
    name: group?.name || '',
    login_type: group?.login_type || '',
    login_url: group?.login_url || '',
    upstream_key: group?.upstream_key || '',
    concurrency: group?.concurrency ?? 1,
    interval_min_ms: group?.interval_min_ms ?? 5000,
    interval_max_ms: group?.interval_max_ms ?? 10000,
    browser_mode: group?.browser_mode || 'inherit',
    fp_check_url: group?.fp_check_url || '',
    proxy_id: group?.proxy_id ?? '',
    phone_platform: group?.phone_platform || '',
    fingerprint_template: { ...(group?.fingerprint_template || {}) },
  }
}

watch(visible, (open) => {
  if (open) Object.assign(form, createForm(props.editing))
})

function changeGroupType() {
  if (!props.editing && platformMeta.value?.default_login_type) {
    form.login_type = platformMeta.value.default_login_type
  }
}

function fillRandom() {
  const fingerprint = randomFp(appStore.meta)
  delete fingerprint.seed
  form.fingerprint_template = fingerprint
}

function geoHasData(geo) {
  return Boolean(geo && [geo.timezone, geo.region, geo.city].some((value) => String(value || '').trim()))
}

async function fillGeo() {
  let geo = form.proxy_id ? appStore.proxies.find((item) => item.id === form.proxy_id) || null : null
  if (!geoHasData(geo) && props.editing) geo = props.editing
  if (!geoHasData(geo) && geoHasData(appStore.defaultGeo)) geo = appStore.defaultGeo
  if (!geoHasData(geo)) {
    await ElMessageBox.alert('请先在代理管理或系统设置保存时区位置。', '暂无已保存的时区数据')
    return
  }
  form.fingerprint_template.timezone = geo.timezone || undefined
  form.fingerprint_template.locale = geo.locale || undefined
  ElMessage.success(`已回填：${[geo.country, geo.city, geo.timezone, geo.locale].filter(Boolean).join(' / ')}`)
}

async function submit() {
  const body = {
    ...form,
    name: form.name.trim(),
    login_url: form.login_url.trim(),
    upstream_key: form.upstream_key.trim(),
    concurrency: Number(form.concurrency) || 1,
    interval_min_ms: Number(form.interval_min_ms) || 5000,
    interval_max_ms: Number(form.interval_max_ms) || 10000,
    fp_check_url: form.fp_check_url.trim(),
    proxy_id: form.proxy_id ? Number(form.proxy_id) : null,
    fingerprint_template: compactFingerprint(form.fingerprint_template),
  }
  if (props.editing) {
    const changed = fpChangedFields(props.editing.fingerprint_template || {}, body.fingerprint_template)
    if (changed.length) {
      try {
        await ElMessageBox.confirm(
          `以下指纹配置将被修改：${changed.join('、')}。指纹变化可能使已登录会话失效。确认保存吗？`,
          `确认修改分组「${props.editing.name}」的指纹模板`,
          { confirmButtonText: '保存', cancelButtonText: '取消', type: 'warning' },
        )
      } catch {
        return
      }
    }
  }
  saving.value = true
  try {
    await appStore.saveGroup(props.editing?.id, body)
    ElMessage.success('分组已保存')
    visible.value = false
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

function compactFingerprint(fingerprint) {
  return Object.fromEntries(Object.entries(fingerprint || {}).filter(([, value]) => value !== undefined && value !== null && value !== ''))
}
</script>

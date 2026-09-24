<template>
  <el-dialog v-model="visible" :title="editing ? `编辑账号 #${editing.id}` : '添加账号'" width="880px" destroy-on-close>
    <el-form class="dialog-form" label-position="top" :model="form">
      <el-segmented v-if="!editing" v-model="mode" class="page-panel" :options="modeOptions" />

      <template v-if="mode === 'single'">
        <div class="form-grid">
          <el-form-item label="账号" required>
            <el-input v-model="form.username" />
          </el-form-item>
          <el-form-item label="密码" :required="!editing">
            <el-input v-model="form.password" type="password" show-password placeholder="编辑时留空表示不修改" />
          </el-form-item>
          <el-form-item label="2FA 密钥（TOTP base32，可选）" class="full-width">
            <el-input v-model="form.totp_secret" :placeholder="editing ? '留空表示不修改' : 'JBSWY3DPEHPK3PXP'" />
          </el-form-item>
        </div>
      </template>
      <el-form-item v-else label="批量账号" required>
        <el-input
          v-model="form.bulk"
          type="textarea"
          :rows="8"
          placeholder="email@example.com|password|JBSWY3DPEHPK3PXP&#10;email2@example.com|password"
        />
        <div class="section-hint">每行一个账号，格式：邮箱|密码|2FA密钥。2FA 密钥可选。</div>
      </el-form-item>

      <div class="form-grid">
        <el-form-item label="备注">
          <el-input v-model="form.remark" placeholder="可选，用于人工区分账号用途" />
        </el-form-item>
        <el-form-item label="账号状态">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </div>

      <el-divider>
        <el-button text type="primary" @click="showEnvironment = !showEnvironment">
          {{ showEnvironment ? '收起' : '展开' }}环境配置
        </el-button>
      </el-divider>
      <template v-if="showEnvironment">
      <div class="form-grid form-grid--three">
        <el-form-item label="浏览器模式">
          <el-select v-model="form.browser_mode">
            <el-option value="inherit" label="跟随分组 / 系统" />
              <el-option value="headless" label="无头" />
              <el-option value="headed" label="有头" />
            </el-select>
          </el-form-item>
          <el-form-item label="接码平台">
            <el-select v-model="form.phone_platform" filterable>
              <el-option value="inherit" label="跟随分组" />
              <el-option value="hero_sms" label="HeroSMS" />
            <el-option v-if="legacyPhonePlatform" :value="form.phone_platform" :label="`${form.phone_platform}（存量）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联代理">
          <el-select v-model="form.proxy_id" filterable>
            <el-option :value="INHERIT_PROXY" label="跟随分组代理" />
            <el-option v-for="item in appStore.proxyOptions" :key="item.value" :value="item.value" :label="item.label" />
              <el-option v-if="legacyProxy" :value="form.proxy_id" :label="`${form.proxy_id}（存量）`" />
            </el-select>
          </el-form-item>
        </div>

        <div class="head-inline page-panel">
          <el-button @click="fillRandom">随机生成</el-button>
          <el-button @click="fillGeo">回填时区</el-button>
          <span class="section-hint">留空按分组指纹模板生成，无模板则随机</span>
        </div>
        <FingerprintFields v-model="form.fingerprint" show-seed />
      </template>
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
import { api } from '@/api/client'
import { appStore } from '@/stores/app'
import { fpChangedFields, randomFp } from '@/utils/fingerprint'
import { trimAccountTail, trimTotpTail } from '@/utils/format'

const props = defineProps({
  modelValue: Boolean,
  editing: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const modeOptions = [
  { label: '单个添加', value: 'single' },
  { label: '批量添加', value: 'bulk' },
]
const mode = ref('single')
const showEnvironment = ref(false)
const saving = ref(false)
const fpBase = ref({})
const form = reactive(createForm(null))
const INHERIT_PROXY = 'inherit'

const legacyProxy = computed(() => Boolean(props.editing?.proxy_id)
  && !appStore.proxies.some((item) => item.id === props.editing.proxy_id))
const legacyPhonePlatform = computed(() => Boolean(props.editing?.phone_platform)
  && !['inherit', 'hero_sms'].includes(props.editing.phone_platform))

function createForm(account) {
  return {
    username: account?.username || '',
    password: '',
    totp_secret: '',
    bulk: '',
    remark: account?.remark || '',
    enabled: account ? Boolean(account.enabled) : true,
    browser_mode: account?.browser_mode || 'inherit',
    phone_platform: account?.phone_platform || 'inherit',
    proxy_id: account?.proxy_id || INHERIT_PROXY,
    fingerprint: { ...(account?.fingerprint || {}) },
  }
}

watch(visible, (open) => {
  if (!open) return
  mode.value = 'single'
  showEnvironment.value = false
  fpBase.value = { ...(props.editing?.fingerprint || {}) }
  Object.assign(form, createForm(props.editing))
})

function fillRandom() {
  form.fingerprint = randomFp(appStore.meta)
}

function geoHasData(geo) {
  return Boolean(geo && [geo.timezone, geo.region, geo.city].some((value) => String(value || '').trim()))
}

async function fillGeo() {
  let geo = form.proxy_id !== INHERIT_PROXY
    ? appStore.proxies.find((item) => String(item.id) === String(form.proxy_id)) || null
    : null
  if (!geoHasData(geo)) {
    const group = appStore.groups.find((item) => String(item.id) === String(props.editing?.group_id || appStore.currentGroup))
    geo = group || geo
  }
  if (!geoHasData(geo) && geoHasData(appStore.defaultGeo)) geo = appStore.defaultGeo
  if (!geoHasData(geo)) {
    await ElMessageBox.alert('请先在代理管理或系统设置保存时区位置。', '暂无已保存的时区数据')
    return
  }
  form.fingerprint.timezone = geo.timezone || undefined
  form.fingerprint.locale = geo.locale || undefined
  ElMessage.success(`已回填：${[geo.country, geo.city, geo.timezone, geo.locale].filter(Boolean).join(' / ')}`)
}

function compact(value) {
  return Object.fromEntries(Object.entries(value || {}).filter(([, item]) => item !== undefined && item !== null && item !== ''))
}

function fingerprintBody() {
  const visibleFp = compact(form.fingerprint)
  return compact({ ...fpBase.value, ...visibleFp })
}

function parseBulkAccounts(text) {
  const rows = []
  const errors = []
  const emails = new Set()
  let duplicates = 0
  String(text || '').split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim()
    if (!line) return
    const parts = line.split('|').map((value) => value.trim())
    if (parts.length < 2 || parts.length > 3 || !parts[0] || !parts[1]) {
      errors.push(`第 ${index + 1} 行格式应为：邮箱|密码|2FA密钥`)
      return
    }
    const username = trimAccountTail(parts[0])
    const email = username.toLowerCase()
    if (emails.has(email)) {
      duplicates += 1
      return
    }
    emails.add(email)
    rows.push({ username, password: parts[1], totp_secret: trimTotpTail(parts[2] || '') })
  })
  return { rows, errors, duplicates }
}

async function submit() {
  const shared = {
    group_id: appStore.currentGroup,
    browser_mode: form.browser_mode,
    phone_platform: form.phone_platform,
    fingerprint: fingerprintBody(),
    enabled: form.enabled,
    remark: form.remark.trim(),
    proxy_id: form.proxy_id !== INHERIT_PROXY ? Number(form.proxy_id) : null,
  }
  saving.value = true
  try {
    if (!props.editing && mode.value === 'bulk') {
      const { rows, errors, duplicates } = parseBulkAccounts(form.bulk)
      if (errors.length) throw new Error(errors[0])
      if (!rows.length) throw new Error('请至少输入一个账号')
      const failures = []
      let created = 0
      let skipped = duplicates
      for (const row of rows) {
        try {
          const result = await api.post('/api/accounts', { ...shared, ...row })
          if (result.exists) skipped += 1
          else created += 1
        } catch (error) {
          failures.push(`${row.username}: ${error.message}`)
        }
      }
      await appStore.loadAccounts(appStore.currentGroup)
      await appStore.loadGroups()
      if (failures.length) {
        ElMessage.error(`已添加 ${created} 个，跳过 ${skipped} 个，失败 ${failures.length} 个；${failures[0]}`)
      } else {
        visible.value = false
        ElMessage.success(created
          ? (skipped ? `已添加 ${created} 个账号，跳过 ${skipped} 个已存在账号` : `已添加 ${created} 个账号`)
          : `所选账号均已存在，已跳过 ${skipped} 个`)
      }
      return
    }

    const body = {
      ...shared,
      username: props.editing ? form.username.trim() : trimAccountTail(form.username),
      password: form.password,
      totp_secret: trimTotpTail(form.totp_secret),
    }
    if (!body.password) throw new Error('密码不能为空')
    if (props.editing) {
      const changed = fpChangedFields(props.editing.fingerprint || {}, body.fingerprint)
      if (changed.length) {
        try {
          await ElMessageBox.confirm(
            `以下指纹配置将被修改：${changed.join('、')}。指纹变化可能使已登录会话失效。确认保存吗？`,
            `确认修改账号 ${props.editing.username} 的指纹`,
            { confirmButtonText: '保存', cancelButtonText: '取消', type: 'warning' },
          )
        } catch {
          return
        }
      }
    }
    await appStore.saveAccount(props.editing, body)
    visible.value = false
    ElMessage.success(props.editing && appStore.accounts.some((item) => item.id === props.editing.id) ? '账号已保存' : '账号已保存')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}
</script>

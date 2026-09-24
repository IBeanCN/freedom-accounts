<template>
  <div v-loading="loading">
    <section>
      <div class="panel-head"><h2>任务环境</h2><span class="section-hint">浏览器以什么模式运行、检测时打开哪个站点</span></div>
      <div class="settings-grid">
        <el-card shadow="never">
          <template #header>浏览器模式（全局默认）</template>
          <el-radio-group v-model="form.global_browser_mode">
            <el-radio-button value="headless">无头 headless</el-radio-button>
            <el-radio-button value="headed">有头 headed</el-radio-button>
          </el-radio-group>
          <p class="section-hint">覆盖顺序：账号 &gt; 分组 &gt; 系统设置。服务器部署建议无头；强防护站点建议切换有头。</p>
          <template #footer><el-button type="primary" @click="save({ global_browser_mode: form.global_browser_mode }, '浏览器模式已保存')">保存</el-button></template>
        </el-card>

        <el-card shadow="never">
          <template #header>指纹检测站点</template>
          <el-input v-model="form.fp_check_url" placeholder="https://fuck-claude.com/zh/" />
          <p class="section-hint">分组内可单独覆盖此地址</p>
          <template #footer><el-button type="primary" @click="save({ fp_check_url: form.fp_check_url.trim() }, '检测站点地址已保存')">保存</el-button></template>
        </el-card>

        <el-card shadow="never" class="full-width">
          <template #header>手机号验证</template>
          <el-radio-group v-model="form.phone_verification_mode" @change="onPhoneModeChange">
            <el-radio-button value="manual">手动</el-radio-button>
            <el-radio-button value="auto">自动</el-radio-button>
          </el-radio-group>
          <div v-if="form.phone_verification_mode === 'auto'" class="form-grid page-panel">
            <el-form-item label="接码平台">
              <el-select v-model="form.phone_verification_platform">
                <el-option value="hero_sms" label="HeroSMS" />
              </el-select>
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="phoneApiKey" type="password" show-password autocomplete="new-password" :placeholder="appStore.settings.phone_verification_api_key_set ? '已配置（留空保持不变）' : '未配置'" @blur="probeProvider" />
              <div class="section-hint">Key 加密保存；留空表示不修改已有 Key</div>
            </el-form-item>
            <el-form-item label="国家列表">
              <el-select v-model="form.phone_verification_country" clearable filterable>
                <el-option v-for="country in appStore.phoneCountries" :key="country.code" :value="country.code" :label="country.name ? `${country.name}（${country.code}）` : country.code" />
              </el-select>
            </el-form-item>
            <el-form-item label="国家编码">
              <el-select v-model="form.phone_verification_page_country" clearable filterable>
                <el-option v-for="country in pageCountries" :key="country.code" :value="country.code" :label="`${country.name}（${country.code} +${country.dial_code}）`" />
                <el-option v-if="legacyPageCountry" :value="form.phone_verification_page_country" :label="`${form.phone_verification_page_country}（存量）`" />
              </el-select>
            </el-form-item>
          </div>
          <el-alert v-if="phoneBalance" :title="phoneBalance" type="success" :closable="false" class="page-panel" />
          <el-alert v-if="phoneError" :title="phoneError" type="error" :closable="false" class="page-panel" />
          <p class="section-hint">自动流程会查余额、获取号码、轮询验证码并确认收到；配置不完整或平台调用失败时回退手动。</p>
          <template #footer><el-button type="primary" @click="savePhone">保存</el-button></template>
        </el-card>
      </div>
    </section>

    <section>
      <div class="panel-head"><h2>指纹环境</h2><span class="section-hint">引擎提供指纹，时区与地区是指纹的组成部分</span></div>
      <div class="settings-grid">
        <el-card shadow="never">
          <template #header>指纹浏览器引擎</template>
          <div class="cell-stack page-panel">
            <span>当前引擎：{{ engine.engine || '—' }}</span>
            <span>引擎状态：{{ engine.cloak_available ? '可用' : '不可用' }}</span>
            <span>引擎版本：{{ engine.cdp_version ? `${engine.cloak_version || '—'}（CDP ${engine.cdp_version}）` : engine.cloak_version || '—' }}</span>
            <span>License Key：{{ licenseText }}</span>
            <span>Python：{{ engine.python || '—' }}</span>
          </div>
          <el-form-item label="cloakserve CDP 地址">
            <el-input v-model="form.cloak_cdp_url" placeholder="http://127.0.0.1:9222" />
            <div class="section-hint">远程指纹浏览器优先于本地引擎；留空则使用本地引擎</div>
          </el-form-item>
          <template #footer><el-button @click="save({ cloak_cdp_url: form.cloak_cdp_url.trim() }, 'CDP 地址已保存')">保存 CDP 地址</el-button></template>
        </el-card>

        <el-card shadow="never">
          <template #header>默认时区位置</template>
          <div class="form-grid">
            <el-form-item label="国家代码"><el-input v-model="form.default_geo_country" maxlength="2" placeholder="US" /></el-form-item>
            <el-form-item label="地区"><el-input v-model="form.default_geo_region" placeholder="California" /></el-form-item>
            <el-form-item label="城市"><el-input v-model="form.default_geo_city" placeholder="Los Angeles" /></el-form-item>
            <el-form-item label="IANA 时区"><el-input v-model="form.default_geo_timezone" placeholder="America/Los_Angeles" /></el-form-item>
            <el-form-item label="语言 locale" class="full-width"><el-input v-model="form.default_geo_locale" placeholder="en-US" /></el-form-item>
          </div>
          <template #footer>
            <el-button type="primary" @click="saveGeo()">保存</el-button>
            <el-button :loading="resolvingGeo" @click="resolveGeo">按出口 IP 解析</el-button>
          </template>
        </el-card>
      </div>
    </section>

    <section>
      <div class="panel-head"><h2>数据与安全</h2><span class="section-hint">服务端数据保留策略与管理员凭据</span></div>
      <div class="settings-grid">
        <el-card shadow="never">
          <template #header>账号日志保留</template>
          <el-form-item label="保留天数（1–365）"><el-input-number v-model="form.log_retention_days" :min="1" :max="365" :controls="false" /></el-form-item>
          <p class="section-hint">每小时巡检一次，服务启动时也会立即清理一次。「立即清理」按当前保留天数执行一次，不可撤销。</p>
          <template #footer>
            <el-button type="primary" @click="save({ log_retention_days: form.log_retention_days }, `日志保留期已设为 ${form.log_retention_days} 天`)">保存</el-button>
            <el-button @click="pruneNow">立即清理</el-button>
          </template>
        </el-card>

        <el-card shadow="never">
          <template #header>管理员密码</template>
          <el-form-item label="旧密码"><el-input v-model="password.old" type="password" show-password autocomplete="current-password" /></el-form-item>
          <el-form-item label="新密码（不少于 6 位）"><el-input v-model="password.new" type="password" show-password autocomplete="new-password" /></el-form-item>
          <template #footer><el-button type="primary" @click="changePassword">修改密码</el-button></template>
        </el-card>

        <el-card shadow="never">
          <template #header>Token 自动刷新</template>
          <el-form-item label="执行间隔（60–2592000 秒）">
            <el-input-number v-model="form.token_refresh_interval_seconds" :min="60" :max="2592000" :controls="false" class="full-width" />
          </el-form-item>
          <template #footer><el-button type="primary" @click="save({ token_refresh_interval_seconds: form.token_refresh_interval_seconds }, `Token 自动刷新间隔已设为 ${form.token_refresh_interval_seconds} 秒`)">保存</el-button></template>
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { appStore } from '@/stores/app'

const loading = ref(false)
const resolvingGeo = ref(false)
const phoneApiKey = ref('')
const phoneBalance = ref('')
const phoneError = ref('')
const pageCountries = ref([])
const password = reactive({ old: '', new: '' })

const form = reactive({
  global_browser_mode: 'headless',
  cloak_cdp_url: '',
  log_retention_days: 3,
  token_refresh_interval_seconds: 3600,
  fp_check_url: '',
  phone_verification_mode: 'manual',
  phone_verification_platform: 'hero_sms',
  phone_verification_country: '',
  phone_verification_page_country: '',
  default_geo_country: '',
  default_geo_region: '',
  default_geo_city: '',
  default_geo_timezone: '',
  default_geo_locale: '',
})

const engine = computed(() => appStore.settings.engine || {})
const licenseText = computed(() => ({
  env: '已配置（.env）',
  file: '已配置（license.key）',
  none: '未配置',
}[engine.value.license_key_source] || '未知'))
const legacyPageCountry = computed(() => Boolean(form.phone_verification_page_country)
  && !pageCountries.value.some((country) => country.code === form.phone_verification_page_country))

onMounted(load)

watch(() => appStore.settings, (settings) => {
  Object.assign(form, {
    global_browser_mode: settings.global_browser_mode || 'headless',
    cloak_cdp_url: settings.cloak_cdp_url || '',
    log_retention_days: settings.log_retention_days ?? 3,
    token_refresh_interval_seconds: settings.token_refresh_interval_seconds ?? 3600,
    fp_check_url: settings.fp_check_url || '',
    phone_verification_mode: settings.phone_verification_mode || 'manual',
    phone_verification_platform: settings.phone_verification_platform || 'hero_sms',
    phone_verification_country: settings.phone_verification_country || '',
    phone_verification_page_country: settings.phone_verification_page_country || '',
    default_geo_country: settings.default_geo_country || '',
    default_geo_region: settings.default_geo_region || '',
    default_geo_city: settings.default_geo_city || '',
    default_geo_timezone: settings.default_geo_timezone || '',
    default_geo_locale: settings.default_geo_locale || '',
  })
}, { immediate: true, deep: true })

async function load() {
  loading.value = true
  try {
    await appStore.loadSettings()
    await loadPageCountries(appStore.settings.phone_verification_page_country || '')
    if (form.phone_verification_mode === 'auto') {
      await appStore.loadPhoneCountries({
        platform: form.phone_verification_platform,
        savedCountry: form.phone_verification_country,
      })
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function save(body, message) {
  await appStore.saveSettings(body, message)
}

async function loadPageCountries(savedCountry = '') {
  try {
    const data = await api.get('/api/settings/page-countries')
    pageCountries.value = data.countries || []
    if (savedCountry && !pageCountries.value.some((country) => country.code === savedCountry)) {
      pageCountries.value.push({ code: savedCountry, name: savedCountry, dial_code: '' })
    }
  } catch {
    pageCountries.value = []
  }
}

async function onPhoneModeChange(mode) {
  if (mode !== 'auto') return
  if (phoneApiKey.value.trim()) await probeProvider()
  else await appStore.loadPhoneCountries({ platform: form.phone_verification_platform, savedCountry: form.phone_verification_country })
}

async function probeProvider() {
  phoneBalance.value = ''
  phoneError.value = ''
  const result = await appStore.testPhoneProvider(form.phone_verification_platform, phoneApiKey.value.trim())
  phoneBalance.value = result.balance ? `${form.phone_verification_platform === 'hero_sms' ? 'HeroSMS' : form.phone_verification_platform} 余额: ${result.balance}` : ''
  phoneError.value = result.error || appStore.phoneCountryError
}

async function savePhone() {
  const body = {
    phone_verification_mode: form.phone_verification_mode,
    phone_verification_platform: form.phone_verification_platform,
    phone_verification_country: form.phone_verification_country || '',
    phone_verification_page_country: form.phone_verification_page_country || '',
  }
  if (phoneApiKey.value.trim()) body.phone_verification_api_key = phoneApiKey.value.trim()
  await appStore.saveSettings(body, '手机号验证设置已保存')
  phoneApiKey.value = ''
}

function geoBody() {
  return {
    default_geo_country: form.default_geo_country.trim(),
    default_geo_region: form.default_geo_region.trim(),
    default_geo_city: form.default_geo_city.trim(),
    default_geo_timezone: form.default_geo_timezone.trim(),
    default_geo_locale: form.default_geo_locale.trim(),
  }
}

async function saveGeo() {
  await appStore.saveSettings(geoBody(), '默认时区位置已保存')
}

async function resolveGeo() {
  resolvingGeo.value = true
  try {
    const geo = await api.get('/api/geo/lookup')
    if (!geo.ok) throw new Error(geo.error || '解析失败')
    Object.assign(form, {
      default_geo_country: geo.country || '',
      default_geo_region: geo.region || '',
      default_geo_city: geo.city || '',
      default_geo_timezone: geo.timezone || '',
      default_geo_locale: geo.locale || '',
    })
    ElMessage.success(`已解析：${geo.ip} → ${[geo.country, geo.city, geo.timezone, geo.locale].filter(Boolean).join(' / ') || '无结果'}`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    resolvingGeo.value = false
  }
}

async function pruneNow() {
  const result = await api.post('/api/logs/prune')
  ElMessage.success(`已清理：适配器日志 ${result.adapter_logs_deleted} 条 · 任务日志 ${result.tasks_deleted} 条`)
}

async function changePassword() {
  await api.post('/api/auth/change-password', { old_password: password.old, new_password: password.new })
  password.old = ''
  password.new = ''
  ElMessage.success('密码已修改')
}
</script>

<template>
  <el-dialog v-model="visible" :title="editing ? '编辑代理' : '新增代理'" width="760px" destroy-on-close>
    <el-form class="dialog-form" label-position="top" :model="form">
      <el-form-item label="代理名称" required>
        <el-input v-model="form.name" placeholder="输入代理名称" />
      </el-form-item>
      <el-form-item label="代理地址">
        <el-input
          v-model="form.server"
          :type="showServer ? 'text' : 'password'"
          autocomplete="off"
          placeholder="socks5://用户名:密码@主机:端口"
        >
          <template #append>
            <el-button :icon="showServer ? Hide : View" @click="showServer = !showServer" />
          </template>
        </el-input>
        <div class="section-hint">留空保留当前连接和认证信息，填写新地址时，请包含所需的用户名和密码</div>
      </el-form-item>
      <el-checkbox v-model="form.custom_geo">自定义时区位置</el-checkbox>
      <template v-if="form.custom_geo">
        <div class="head-inline page-panel">
          <span class="section-hint">{{ geoSource }}</span>
          <el-button text type="primary" :loading="resolving" @click="fillByExitIp">按出口 IP 解析</el-button>
        </div>
        <div class="form-grid">
          <el-form-item label="国家代码">
            <el-input v-model="form.country" maxlength="2" placeholder="请输入两位国家代码" />
          </el-form-item>
          <el-form-item label="地区">
            <el-input v-model="form.region" placeholder="请输入地区" />
          </el-form-item>
          <el-form-item label="城市">
            <el-input v-model="form.city" placeholder="请输入城市" />
          </el-form-item>
          <el-form-item label="IANA 时区">
            <el-input v-model="form.timezone" placeholder="America/New_York" />
          </el-form-item>
          <el-form-item label="语言 locale">
            <el-input v-model="form.locale" placeholder="en-US" />
          </el-form-item>
        </div>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button :loading="testing" @click="testThenClose">测试连接</el-button>
      <el-button type="primary" :loading="saving" @click="submit(false)">保存代理</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Hide, View } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import { appStore } from '@/stores/app'

const props = defineProps({
  modelValue: Boolean,
  editing: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const showServer = ref(false)
const saving = ref(false)
const testing = ref(false)
const resolving = ref(false)
const geoPrefilled = ref(false)
const form = reactive(createForm(null))

const geoSource = computed(() => geoPrefilled.value
  ? '使用该代理已保存的位置，可手动修改或按出口 IP 解析'
  : '打开「自定义时区位置」后将预填系统默认值')

function createForm(proxy) {
  return {
    name: proxy?.name || '',
    server: '',
    custom_geo: Boolean(proxy?.custom_geo),
    country: proxy?.country || '',
    region: proxy?.region || '',
    city: proxy?.city || '',
    timezone: proxy?.timezone || '',
    locale: proxy?.locale || '',
  }
}

watch([visible, form.custom_geo], ([open]) => {
  if (!open) return
  Object.assign(form, createForm(props.editing))
  showServer.value = false
  geoPrefilled.value = Boolean(props.editing?.country || props.editing?.timezone)
  if (form.custom_geo && !geoPrefilled.value) fillDefaults()
}, { immediate: true })

function fillDefaults() {
  const hasAny = [form.country, form.region, form.city, form.timezone].some((value) => String(value || '').trim())
  if (hasAny || !appStore.defaultGeo) return
  Object.assign(form, {
    country: appStore.defaultGeo.country || '',
    region: appStore.defaultGeo.region || '',
    city: appStore.defaultGeo.city || '',
    timezone: appStore.defaultGeo.timezone || '',
    locale: appStore.defaultGeo.locale || '',
  })
  geoPrefilled.value = true
}

function body(serverOverride) {
  return {
    name: form.name.trim(),
    server: (serverOverride ?? form.server).trim(),
    custom_geo: form.custom_geo,
    country: form.country.trim(),
    region: form.region.trim(),
    city: form.city.trim(),
    timezone: form.timezone.trim(),
    locale: form.locale.trim(),
  }
}

async function ensureSaved() {
  if (props.editing?.id) {
    await api.put(`/api/proxies/${props.editing.id}`, body(form.server))
    return props.editing.id
  }
  const data = await api.post('/api/proxies', body(form.server))
  return data.id
}

async function testThenClose() {
  if (!form.name.trim()) return ElMessage.error('请先填写代理名称')
  if (!props.editing && !form.server.trim()) return ElMessage.error('请先填写代理地址')
  testing.value = true
  try {
    const id = await ensureSaved()
    await api.post(`/api/proxies/${id}/test`)
    visible.value = false
    ElMessage.success('测试连接已发起')
    await appStore.loadProxies()
    appStore.pollProxyTest(id, 0, Date.now())
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    testing.value = false
  }
}

async function fillByExitIp() {
  if (!form.name.trim()) return ElMessage.error('请先填写代理名称')
  if (!props.editing && !form.server.trim()) return ElMessage.error('请先填写代理地址')
  resolving.value = true
  try {
    let ip = props.editing?.exit_ip || ''
    if (!ip) {
      const id = await ensureSaved()
      await api.post(`/api/proxies/${id}/test`)
      ip = await appStore.pollProxyExitIp(id, 20)
      if (!ip) throw new Error('未能获取出口 IP（代理连接失败？）')
    }
    const geo = await api.get(`/api/geo/lookup?ip=${encodeURIComponent(ip)}`)
    if (!geo.ok) throw new Error(geo.error || '解析失败')
    Object.assign(form, {
      country: geo.country || '',
      region: geo.region || '',
      city: geo.city || '',
      timezone: geo.timezone || '',
      locale: geo.locale || '',
    })
    ElMessage.success(`已解析：${[geo.country, geo.city, geo.timezone, geo.locale].filter(Boolean).join(' / ') || '无结果'}`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    resolving.value = false
  }
}

async function submit(afterTest = false) {
  saving.value = true
  try {
    await appStore.saveProxy(props.editing, body())
    ElMessage.success(props.editing ? '代理已保存' : '代理已创建')
    visible.value = false
    return afterTest
  } catch (error) {
    ElMessage.error(error.message)
    return false
  } finally {
    saving.value = false
  }
}

defineExpose({ submit })
</script>

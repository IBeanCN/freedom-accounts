<template>
  <div>
    <div class="panel-head">
      <div class="panel-title-row">
        <h2>代理列表</h2>
        <el-tag effect="plain">{{ appStore.proxies.length }} 个代理</el-tag>
        <span class="section-hint">测试连接通过 ipify 检测链路与出口 IP</span>
      </div>
      <div class="head-inline">
        <el-input v-model="keyword" clearable placeholder="搜索代理名称..." style="width: 240px" />
        <el-button type="primary" :icon="Plus" @click="open()">新增代理</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table :data="filteredProxies" empty-text="暂无代理，点击右上角「新增代理」创建。">
        <el-table-column label="代理名称" min-width="160">
          <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column label="代理地址" min-width="240">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="mono">{{ row.server_masked || '—' }}</span>
              <span v-if="row.custom_geo" class="cell-sub">{{ [row.country, row.region, row.city, row.timezone].filter(Boolean).join(' · ') }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="出口 IP" width="160">
          <template #default="{ row }">
            <el-tag v-if="testing(row)" type="info">检测中</el-tag>
            <span v-else-if="failed(row)" class="step-error">失败</span>
            <span v-else class="mono">{{ row.exit_ip || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            <span v-if="!testing(row) && !failed(row)">{{ row.latency_ms == null || row.latency_ms === '' ? '—' : `${row.latency_ms} ms` }}</span>
            <span v-else-if="testing(row)">…</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="关联账号" width="100" prop="linked_accounts" />
        <el-table-column label="测试时间" width="150">
          <template #default="{ row }">{{ testing(row) ? '' : fmtTime(row.check_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button :disabled="testing(row)" :icon="Promotion" circle title="测试连接" @click="test(row)" />
            <el-button :icon="Edit" circle title="编辑" @click="open(row)" />
            <el-button :icon="Delete" circle type="danger" title="删除" @click="remove(row)" />
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <ProxyFormDialog v-model="showForm" :editing="editing" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Promotion } from '@element-plus/icons-vue'
import ProxyFormDialog from '@/dialogs/ProxyFormDialog.vue'
import { appStore } from '@/stores/app'
import { fmtTime } from '@/utils/format'

const keyword = ref('')
const showForm = ref(false)
const editing = ref(null)

const filteredProxies = computed(() => {
  const value = keyword.value.trim().toLowerCase()
  return value ? appStore.proxies.filter((proxy) => String(proxy.name || '').toLowerCase().includes(value)) : appStore.proxies
})

onMounted(() => appStore.loadProxies())

function testing(proxy) {
  return proxy.testing === true || proxy.check_error === '检测中'
}

function failed(proxy) {
  return !testing(proxy) && String(proxy.check_error || '').trim() !== ''
}

function open(proxy = null) {
  editing.value = proxy
  showForm.value = true
}

async function test(proxy) {
  if (testing(proxy)) return
  await appStore.testProxy(proxy)
}

async function remove(proxy) {
  try {
    await ElMessageBox.confirm(
      `该代理与 ${proxy.linked_accounts || 0} 个账号的关联配置将被删除，此操作不可撤销。`,
      `删除代理「${proxy.name}」`,
      { confirmButtonText: '删除代理', cancelButtonText: '取消', type: 'error', confirmButtonClass: 'el-button--danger' },
    )
    await appStore.deleteProxy(proxy)
  } catch (error) {
    if (error !== 'cancel' && error?.message) ElMessage.error(error.message)
  }
}
</script>

<template>
  <div>
    <div class="panel-head">
      <div class="panel-title-row">
        <h2>分组</h2>
        <el-tag effect="plain">{{ appStore.groups.length }} 个分组</el-tag>
        <span class="section-hint">点击分组卡片展开该分组的账号列表</span>
      </div>
      <el-button :icon="Plus" @click="openGroup()">新建分组</el-button>
    </div>

    <div class="group-grid">
      <div
        v-for="group in appStore.groups"
        :key="group.id"
        class="group-card"
        :class="{ 'is-selected': isSelected(group), 'is-open': appStore.expandedGroups.has(String(group.id)) }"
        tabindex="0"
        role="button"
        @click="select(group)"
        @keydown.enter.prevent="select(group)"
        @keydown.space.prevent="select(group)"
      >
        <div class="group-head">
          <span class="group-avatar">{{ initial(group) }}</span>
          <div class="group-head-text">
            <div class="group-name-row">
              <el-tooltip v-if="risk(group)" :content="risk(group).tip" placement="top">
                <span class="risk-dot" :style="{ background: riskColor(group) }" />
              </el-tooltip>
              <span class="group-name">{{ group.name }}</span>
            </div>
            <span class="group-sub">
              {{ appStore.groupTypeLabel(group.group_type) }} · {{ appStore.loginTypeLabel(group.login_type) }} · {{ group.account_count || 0 }} 个账号
            </span>
          </div>
          <el-tag v-if="(group.running_count || 0) > 0" type="info">运行中 {{ group.running_count }}</el-tag>
          <el-button text :icon="appStore.expandedGroups.has(String(group.id)) ? ArrowUp : ArrowDown" @click.stop="appStore.toggleGroupExpanded(group.id)" />
        </div>
        <div class="group-actions" @click.stop>
          <el-button text size="small" type="primary" @click="groupAction(group, 'start')">执行</el-button>
          <template v-if="appStore.localEngine">
            <el-button
              text
              v-if="group.browser_open"
              size="small"
              @click="groupAction(group, 'close-browser')"
            >关浏览器</el-button>
            <el-button
              text
              v-else
              size="small"
              @click="groupAction(group, 'open-browser')"
            >开浏览器</el-button>
          </template>
          <el-button text size="small" @click="groupAction(group, 'sync-accounts')">同步</el-button>
          <el-button
            text
            v-if="isGroupChecking(group)"
            size="small"
            :disabled="appStore.fpStopPending.has(`g${group.id}`)"
            @click="appStore.stopGroupFingerprintCheck(group)"
          >
            {{ appStore.fpStopPending.has(`g${group.id}`) ? '停止中…' : '停止' }}
          </el-button>
          <el-button v-else text size="small" @click="appStore.startGroupFingerprintCheck(group)">检测</el-button>
          <el-button text size="small" @click="openGroup(group)">编辑</el-button>
          <el-button text size="small" type="danger" @click="removeGroup(group)">删除</el-button>
        </div>
      </div>
    </div>
    <div v-if="!appStore.groups.length" class="empty-state">暂无分组，点击「新建分组」创建。</div>

    <el-card v-if="appStore.currentGroup" class="page-panel" shadow="never">
      <div class="panel-head">
        <div class="panel-title-row">
          <h3>账号 · {{ appStore.currentGroupModel?.name || '' }}</h3>
          <el-select v-model="appStore.accountAutoRefreshSeconds" style="width: 100px" @change="appStore.scheduleAccountRefresh">
            <el-option label="关闭" value="" />
            <el-option label="5秒" value="5" />
            <el-option label="10秒" value="10" />
            <el-option label="15秒" value="15" />
            <el-option label="30秒" value="30" />
          </el-select>
        </div>
        <div class="head-inline">
          <el-button :icon="Plus" @click="openAccount()">添加账号</el-button>
          <el-button @click="startSelected">一键执行（{{ scopeLabel }}）</el-button>
          <el-button @click="showBatchFingerprint = true">批量换指纹（{{ scopeLabel }}）</el-button>
          <el-button :disabled="appStore.anyAccountBusy" :loading="refreshingTokens" @click="refreshTokens">
            {{ appStore.anyAccountBusy ? '账号任务进行中…' : `一键刷新Token（${scopeLabel}）` }}
          </el-button>
          <el-button type="danger" plain :disabled="deleteDisabled" @click="deleteSelected">
            {{ selectedRows.length ? `删除（已选 ${selectedRows.length}）` : '删除账号' }}
          </el-button>
          <el-button text @click="appStore.closeAccounts">收起</el-button>
        </div>
      </div>

      <el-table
        ref="accountTableRef"
        :data="appStore.accounts"
        row-key="id"
        empty-text="该分组暂无账号，点击上方「添加账号」创建。"
        @select-all="appStore.toggleAllAccounts"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" fixed="left" />
        <el-table-column label="账号 / 上游信息" width="260" fixed="left" prop="username" sortable :sort-method="sortByAccount">
          <template #default="{ row }">
            <div class="cell-stack">
              <el-tooltip :content="row.username" :disabled="!row.username" placement="top">
                <span class="ellipsis-cell">{{ row.username }}</span>
              </el-tooltip>
              <el-tooltip :content="upstreamInfo(row)" placement="top">
                <span class="ellipsis-cell cell-sub">{{ upstreamInfo(row) }}</span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="上游状态" width="110" prop="remote_status" sortable :sort-method="sortByRemoteStatus">
          <template #default="{ row }">
            <el-tag :type="remoteStatusType(row.remote_status)" effect="plain">{{ row.remote_status || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="指纹 / 检测" width="230" sortable :sort-method="sortByFingerprint">
          <template #default="{ row }">
            <div class="fingerprint-cell">
              <el-tooltip :content="badge(row).tip || badge(row).label" placement="top">
                <el-tag size="small" :type="badge(row).type === 'primary' ? 'info' : badge(row).type">{{ badge(row).label }}</el-tag>
              </el-tooltip>
              <el-tooltip :content="fingerprintSummary(row.fingerprint)" :disabled="!row.fingerprint?.seed" placement="top">
                <div class="fingerprint-lines">
                  <span class="ellipsis-cell mono">{{ fingerprintMeta(row.fingerprint).seed }}</span>
                  <span class="ellipsis-cell cell-sub">{{ fingerprintMeta(row.fingerprint).meta }}</span>
                </div>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="浏览器 / 代理" width="130" sortable :sort-method="sortByBrowserProxy">
          <template #default="{ row }">
            <div class="cell-stack">
              <el-tooltip :content="modeText(row.browser_mode)" placement="top">
                <span class="ellipsis-cell">{{ modeText(row.browser_mode) }}</span>
              </el-tooltip>
              <el-tooltip :content="proxyText(row)" placement="top">
                <span class="ellipsis-cell cell-sub">{{ proxyText(row) }}</span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80" sortable :sort-method="sortByEnabled">
          <template #default="{ row }">
            <el-switch :model-value="Boolean(row.enabled)" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column label="最新状态" width="160" sortable :sort-method="sortByLatestStatus">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.last_status).type">{{ statusMeta(row.last_status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近运行" width="170" prop="last_run_at" sortable :sort-method="sortByLastRun">
          <template #default="{ row }">
            <span class="ellipsis-cell">{{ fmtTime(row.last_run_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <div class="account-actions">
              <template v-if="row.enabled">
                <el-button link size="small" type="primary" :disabled="busy(row)" @click="run(row)">{{ runLabel(row) }}</el-button>
                <el-button link size="small" :disabled="busy(row)" @click="regenerate(row)">换指纹</el-button>
                <el-button link size="small" :disabled="busy(row)" @click="refresh(row)">{{ tokenLabel(row) }}</el-button>
                <el-button
                  v-if="isChecking(row)"
                  link
                  size="small"
                  :disabled="appStore.fpStopPending.has(`a${row.id}`)"
                  @click="appStore.stopAccountFingerprintCheck(row)"
                >{{ appStore.fpStopPending.has(`a${row.id}`) ? '停止中…' : '停止检测' }}</el-button>
                <el-button v-else link size="small" :disabled="busy(row)" @click="check(row)">指纹检测</el-button>
                <el-button v-if="loginBusy(row)" link size="small" type="warning" @click="stop(row)">停止</el-button>
                <el-button link size="small" @click="showLogs(row)">日志</el-button>
              </template>
              <el-tag v-else type="warning">已停用</el-tag>
              <el-button link size="small" @click="openAccount(row)">编辑</el-button>
              <el-button link size="small" type="danger" :disabled="busy(row)" @click="remove(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <GroupFormDialog v-model="showGroupForm" :editing="editingGroup" />
    <AccountFormDialog v-model="showAccountForm" :editing="editingAccount" />
    <BatchFingerprintDialog
      v-model="showBatchFingerprint"
      :account-ids="selectedIds"
      :selected-count="selectedRows.length"
    />
    <TaskDetailDialog v-model="showTaskDialog" history :tasks="accountTasks" title="账号最近任务" subtitle="点击任意条目查看完整详情" />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { ArrowDown, ArrowUp, Plus } from '@element-plus/icons-vue'
import GroupFormDialog from '@/dialogs/GroupFormDialog.vue'
import AccountFormDialog from '@/dialogs/AccountFormDialog.vue'
import BatchFingerprintDialog from '@/dialogs/BatchFingerprintDialog.vue'
import TaskDetailDialog from '@/dialogs/TaskDetailDialog.vue'
import { api } from '@/api/client'
import { appStore, isAccountBusy } from '@/stores/app'
import { fmtTime, modeText, safeJson } from '@/utils/format'
import { fpBadgeMeta, fpLevel, remoteStatusType, statusMeta } from '@/utils/status'

const showGroupForm = ref(false)
const editingGroup = ref(null)
const showAccountForm = ref(false)
const editingAccount = ref(null)
const showBatchFingerprint = ref(false)
const showTaskDialog = ref(false)
const accountTasks = ref([])
const refreshingTokens = ref(false)
const accountTableRef = ref(null)

const selectedRows = ref([])
const selectedIds = computed(() => [...new Set(selectedRows.value.map((row) => Number(row.id)))])
const scopeLabel = computed(() => selectedRows.value.length ? `已选 ${selectedRows.value.length}` : 'ALL')
const selectedBusy = computed(() => selectedRows.value.some(isAccountBusy))
const deleteDisabled = computed(() => !selectedRows.value.length || selectedBusy.value)

onMounted(async () => {
  await appStore.loadGroups()
  if (appStore.currentGroup) await appStore.loadAccounts(appStore.currentGroup)
})

watch(() => appStore.accounts, async () => {
  await nextTick()
  const table = accountTableRef.value
  if (!table) return
  appStore.accounts.forEach((row) => {
    table.toggleRowSelection(row, appStore.selectedAccountIds.includes(String(row.id)))
  })
})

function isSelected(group) {
  return String(appStore.currentGroup) === String(group.id)
}

async function select(group) {
  await appStore.selectGroup(group.id)
}

function initial(group) {
  return String(group.name || '·').trim().charAt(0).toUpperCase()
}

function isGroupChecking(group) {
  return group.fp_check_result === '检测中' || appStore.fpStopPending.has(`g${group.id}`)
}

function risk(group) {
  const value = String(group.fp_check_result || '').trim()
  if (!value) return null
  if (value === '检测中') return { tip: '指纹模板检测中', color: 'var(--el-color-info)' }
  if (value === '已停止') return { tip: '指纹模板检测已停止', color: 'var(--el-color-info)' }
  if (value.startsWith('失败')) return { tip: value, color: 'var(--el-color-info)' }
  const [riskText, score] = value.split('/')
  const level = fpLevel(riskText)
  const colors = { 高: 'var(--el-color-danger)', 中: 'var(--el-color-warning)', 低: 'var(--el-color-success)' }
  return { tip: `${level}风险/${score || ''}`, color: colors[level] }
}

function riskColor(group) {
  return risk(group)?.color || 'transparent'
}

async function groupAction(group, action) {
  try {
    if (action === 'sync-accounts') {
      await ElMessageBox.confirm(
        '将按上游账号 ID 比对：ID 已存在则仅更新上游信息（密码/2FA/指纹等本地配置不动），上游已移除的删除，新增的落库；与上游账号重复的其他账号将被停用。',
        `同步账号 · ${group.name}`,
        { confirmButtonText: '开始同步', cancelButtonText: '取消', type: 'warning' },
      )
    }
    await appStore.groupAction(group, action)
  } catch (error) {
    if (error !== 'cancel' && error?.message) ElMessage.error(error.message)
  }
}

async function openGroup(group = null) {
  editingGroup.value = group
  showGroupForm.value = true
}

async function removeGroup(group) {
  try {
    await ElMessageBox.confirm(
      `该分组下的 ${group.account_count || 0} 个账号、指纹配置与任务记录将一并删除，此操作不可撤销。`,
      `删除分组「${group.name}」`,
      { confirmButtonText: '删除分组', cancelButtonText: '取消', type: 'error', confirmButtonClass: 'el-button--danger' },
    )
    await appStore.deleteGroup(group)
    ElMessage.success('分组已删除')
  } catch (error) {
    if (error !== 'cancel' && error?.message) ElMessage.error(error.message)
  }
}

function busy(account) {
  return isAccountBusy(account)
}

function loginBusy(account) {
  return ['queued', 'running'].includes(account.last_status)
}

function runLabel(account) {
  if (account.last_status === 'running') return '执行中…'
  return isAccountBusy(account) ? '队列中…' : '执行'
}

function tokenLabel(account) {
  return ['token_queued', 'token_running'].includes(account.last_status) ? '刷新中…' : '刷新Token'
}

function isChecking(account) {
  return account.fp_check_result === '检测中' || appStore.fpStopPending.has(`a${account.id}`)
}

function fingerprintSummary(fingerprint) {
  if (!fingerprint?.seed) return '未配置'
  const screen = fingerprint.screen_width && fingerprint.screen_height ? `${fingerprint.screen_width}×${fingerprint.screen_height}` : '—'
  return `#${fingerprint.seed} · ${fingerprint.platform || '—'} · ${screen} · ${fingerprint.timezone || '—'}`
}

function fingerprintMeta(fingerprint) {
  if (!fingerprint?.seed) return { seed: '未配置', meta: '运行或换指纹时生成' }
  const screen = fingerprint.screen_width && fingerprint.screen_height ? `${fingerprint.screen_width}×${fingerprint.screen_height}` : '—'
  return {
    seed: `#${fingerprint.seed}`,
    meta: [fingerprint.platform || '—', screen, fingerprint.timezone || '—'].filter(Boolean).join(' · '),
  }
}

function upstreamInfo(account) {
  const parts = []
  if (account.remote_id) parts.push(`ID ${account.remote_id}`)
  if (account.remote_remark) parts.push(account.remote_remark)
  return parts.join(' · ') || '无上游信息'
}

function compareSortValues(a, b) {
  if (a == null && b == null) return 0
  if (a == null) return -1
  if (b == null) return 1
  return String(a).localeCompare(String(b), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' })
}

function sortByAccount(a, b) {
  return compareSortValues(a.username, b.username)
    || compareSortValues(upstreamInfo(a), upstreamInfo(b))
}

function sortByRemoteStatus(a, b) {
  return compareSortValues(a.remote_status, b.remote_status)
    || compareSortValues(a.username, b.username)
}

function sortByFingerprint(a, b) {
  return compareSortValues(badge(a).label, badge(b).label)
    || compareSortValues(a.fingerprint?.seed, b.fingerprint?.seed)
}

function sortByBrowserProxy(a, b) {
  return compareSortValues(modeText(a.browser_mode), modeText(b.browser_mode))
    || compareSortValues(proxyText(a), proxyText(b))
}

function sortByEnabled(a, b) {
  return compareSortValues(Number(Boolean(b.enabled)), Number(Boolean(a.enabled)))
    || compareSortValues(a.username, b.username)
}

function sortByLatestStatus(a, b) {
  return compareSortValues(statusMeta(a.last_status).label, statusMeta(b.last_status).label)
    || compareSortValues(a.username, b.username)
}

function sortByLastRun(a, b) {
  return compareSortValues(a.last_run_at, b.last_run_at)
    || compareSortValues(a.username, b.username)
}

function proxyText(account) {
  if (account.proxy_id) return `代理 ${account.proxy_name}`
  return account.group_proxy_id ? '跟随分组代理' : '直连'
}

function badge(account) {
  return fpBadgeMeta(account.fp_check_result, account.fp_check_at)
}

function onSelectionChange(rows) {
  selectedRows.value = rows
  appStore.setAccountSelection(rows)
}

async function startSelected() {
  try {
    await appStore.startAccounts(selectedIds.value)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function openAccount(account = null) {
  editingAccount.value = account
  showAccountForm.value = true
}

async function accountGuard(account, message) {
  if (!account.enabled) {
    ElMessage.error('账号已停用，仅允许编辑/删除')
    return false
  }
  if (busy(account)) {
    ElMessage.error('账号正在运行或排队，请稍后再试')
    return false
  }
  if (!message) return true
  try {
    await ElMessageBox.confirm(message.message, message.title, {
      confirmButtonText: message.ok,
      cancelButtonText: '取消',
      type: message.type || 'warning',
      confirmButtonClass: message.danger ? 'el-button--danger' : '',
    })
    return true
  } catch {
    return false
  }
}

async function run(account) {
  if (!await accountGuard(account)) return
  if (!account.has_password) {
    ElMessage.error(`账号 ${account.username} 未配置密码，请先编辑账号`)
    return
  }
  await appStore.runAccount(account)
}

async function stop(account) {
  const queued = account.last_status === 'queued'
  if (!await accountGuard(account, {
    title: `停止任务：${account.username}`,
    message: queued ? '该账号仍在队列中，停止后会直接从队列移除。' : '该账号任务正在执行，停止后会中断后续流程并关闭指纹浏览器。',
    ok: '停止',
  })) return
  await appStore.stopAccount(account)
}

async function toggleEnabled(account) {
  if (account.enabled && busy(account)) {
    ElMessage.error('账号正在运行或排队，不能停用')
    return
  }
  await appStore.toggleAccountEnabled(account)
}

async function regenerate(account) {
  if (!await accountGuard(account, {
    title: '重新生成浏览器指纹',
    message: `将为账号 ${account.username} 随机生成一套新的指纹（平台、分辨率、时区、WebGL 等），覆盖现有配置。`,
    ok: '重新生成',
  })) return
  await appStore.regenerateAccountFingerprint(account)
}

async function refresh(account) {
  if (!await accountGuard(account, {
    title: `刷新 Token：${account.username}`,
    message: '账号级刷新会忽略 30 分钟窗口限制，但仍要求上游状态正常且能识别 Token 过期时间。',
    ok: '刷新 Token',
  })) return
  await appStore.refreshAccountToken(account)
}

async function check(account) {
  if (!await accountGuard(account)) return
  await appStore.startAccountFingerprintCheck(account)
}

async function remove(account) {
  if (!await accountGuard(account, {
    title: `删除账号 ${account.username}`,
    message: '该账号的登录凭据、2FA 密钥与浏览器指纹将一并删除，此操作不可撤销。',
    ok: '删除账号',
    type: 'error',
    danger: true,
  })) return
  await appStore.deleteAccount(account)
}

async function refreshTokens() {
  if (!selectedRows.value.length && !appStore.accounts.length) {
    ElMessage.error('该分组暂无账号')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将先同步上游数据；批量刷新仅处理上游状态正常且 Token 将在 30 分钟内过期的启用账号，多个账号之间间隔 5–20 秒。',
      `一键刷新 ${selectedRows.value.length || appStore.accounts.length} 个账号 Token`,
      { confirmButtonText: '开始刷新', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  refreshingTokens.value = true
  try {
    await appStore.batchRefreshTokens(selectedIds.value)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    refreshingTokens.value = false
  }
}

async function deleteSelected() {
  const selected = selectedRows.value
  if (!selected.length) return
  try {
    await ElMessageBox.confirm(
      `将删除：${selected.map((account) => account.username).join('、')}。登录凭据、2FA 密钥与浏览器指纹将一并删除，此操作不可撤销。`,
      `删除 ${selected.length} 个账号`,
      { confirmButtonText: '删除账号', cancelButtonText: '取消', type: 'error', confirmButtonClass: 'el-button--danger' },
    )
    await appStore.batchDeleteAccounts(selectedIds.value)
  } catch (error) {
    if (error !== 'cancel' && error?.message) ElMessage.error(error.message)
  }
}

async function showLogs(account) {
  if (!account.enabled) {
    ElMessage.error('账号已停用，仅允许编辑/删除')
    return
  }
  const data = await api.get(`/api/accounts/${account.id}/tasks`)
  accountTasks.value = data.tasks || []
  showTaskDialog.value = true
}
</script>

<style scoped>
.account-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px 8px;
  align-items: center;
  justify-items: start;
}

.account-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.account-actions :deep(.el-button),
.account-actions :deep(.el-tag) {
  justify-self: start;
  min-width: 0;
}
</style>

import { reactive } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { api } from '@/api/client'
import { engineLabel } from '@/utils/format'

const defaultSettings = {
  global_browser_mode: 'headless',
  cloak_cdp_url: '',
  log_retention_days: 3,
  token_refresh_interval_seconds: 3600,
  fp_check_url: '',
  phone_verification_mode: 'manual',
  phone_verification_platform: 'hero_sms',
  phone_verification_country: '',
  phone_verification_page_country: '',
  phone_verification_api_key_set: false,
  default_geo_country: '',
  default_geo_region: '',
  default_geo_city: '',
  default_geo_timezone: '',
  default_geo_locale: '',
  engine: {},
}

export const appStore = reactive({
  authenticated: false,
  authChecked: false,
  theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
  settings: { ...defaultSettings },
  meta: { login_types: [], group_types: [], fp_options: null },
  localEngine: true,
  defaultGeo: {},

  groups: [],
  proxies: [],
  currentGroup: null,
  accounts: [],
  selectedAccountIds: [],
  expandedGroups: new Set(),
  fpStopPending: new Set(),
  accountAutoRefreshSeconds: '',
  accountAutoRefreshTimer: null,

  tasks: [],
  taskFilter: '',
  taskMetrics: { total: 0, success: 0, failed: 0, running: 0 },

  phoneCountries: [],
  phoneCountryError: '',

  get proxyOptions() {
    return this.proxies.map((proxy) => ({
      value: proxy.id,
      label: `${proxy.name}（${String(proxy.server_masked || '').replace(/^[a-z0-9]+:\/\//, '')}）`,
    }))
  },

  get currentGroupModel() {
    return this.groups.find((group) => String(group.id) === String(this.currentGroup)) || null
  },

  get selectedAccounts() {
    return this.accounts.filter((account) => this.selectedAccountIds.includes(String(account.id)))
  },

  get selectedNumberIds() {
    return [...new Set(this.selectedAccounts.map((account) => Number(account.id)))]
  },

  get anyAccountBusy() {
    return this.accounts.some(isAccountBusy)
  },

  async initAuth() {
    window.addEventListener('fa:unauthorized', () => {
      this.authenticated = false
      this.resetAccountRefresh()
      window.location.hash = '#/login'
    })
    try {
      await api.get('/api/auth/me')
      this.authenticated = true
      await this.loadAll()
    } catch {
      this.authenticated = false
    } finally {
      this.authChecked = true
    }
  },

  async login(payload) {
    await api.post('/api/auth/login', payload)
    this.authenticated = true
    await this.loadAll()
  },

  async logout() {
    try {
      await api.post('/api/auth/logout')
    } finally {
      this.authenticated = false
      this.resetAccountRefresh()
      window.location.hash = '#/login'
    }
  },

  async loadAll() {
    await Promise.all([this.loadSettings(), this.loadMeta(), this.loadProxies({ silent: true })])
    await this.loadGroups()
    if (this.currentGroup && this.groups.some((group) => String(group.id) === String(this.currentGroup))) {
      await this.loadAccounts(this.currentGroup)
    } else if (this.currentGroup) {
      this.closeAccounts()
    }
  },

  async loadSettings() {
    const settings = await api.get('/api/settings')
    this.settings = { ...defaultSettings, ...settings }
    this.localEngine = !String(settings.cloak_cdp_url || '').trim()
    this.defaultGeo = {
      country: settings.default_geo_country || '',
      region: settings.default_geo_region || '',
      city: settings.default_geo_city || '',
      timezone: settings.default_geo_timezone || '',
      locale: settings.default_geo_locale || '',
    }
  },

  async saveSettings(body, successMessage) {
    await api.put('/api/settings', body)
    await this.loadSettings()
    if (successMessage) ElMessage.success(successMessage)
  },

  async loadMeta() {
    try {
      this.meta = await api.get('/api/meta')
    } catch {
      this.meta = { login_types: [], group_types: [], fp_options: null }
    }
  },

  loginTypeLabel(key) {
    const adapter = this.meta.login_types.find((item) => item.key === key)
    return adapter ? adapter.label.split(/[（(]/)[0].trim() || key : key || '—'
  },

  groupTypeLabel(key) {
    const platform = this.meta.group_types.find((item) => item.key === key)
    return platform ? platform.label : key || '—'
  },

  async loadGroups() {
    const data = await api.get('/api/groups')
    this.groups = data.groups || []
  },

  async saveGroup(id, body) {
    if (id) await api.put(`/api/groups/${id}`, body)
    else await api.post('/api/groups', body)
    await this.loadAll()
  },

  async deleteGroup(group) {
    await api.del(`/api/groups/${group.id}`)
    if (String(this.currentGroup) === String(group.id)) this.closeAccounts()
    await this.loadGroups()
  },

  async groupAction(group, action) {
    const data = await api.post(`/api/groups/${group.id}/${action}`, {})
    if (action === 'sync-accounts') {
      const bits = [`新增 ${data.created}`, `更新 ${data.updated || 0}`, `删除 ${data.deleted}`]
      if (data.disabled) bits.push(`停用重复 ${data.disabled}`)
      bits.push(`忽略 ${data.ignored}`)
      ElMessage.success(`同步完成：${bits.join(' · ')}`)
      await this.loadGroups()
      if (String(this.currentGroup) === String(group.id)) await this.loadAccounts(group.id)
    } else if (action === 'start') {
      ElMessage.success(data.queued ? `已入队 ${data.queued} 个账号任务` : '已触发调度')
      setTimeout(() => this.loadGroups(), 1200)
    } else if (action === 'open-browser') {
      await this.loadGroups()
      ElMessage.success(data.reused ? `分组 ${group.name} 的浏览器已打开（复用现有窗口）` : `已为分组 ${group.name} 打开浏览器`)
    } else if (action === 'close-browser') {
      await this.loadGroups()
      ElMessage.success(data.closed ? `分组 ${group.name} 的浏览器已关闭` : `分组 ${group.name} 没有打开的浏览器`)
    }
    return data
  },

  toggleGroupExpanded(groupId) {
    const key = String(groupId)
    if (this.expandedGroups.has(key)) this.expandedGroups.delete(key)
    else this.expandedGroups.add(key)
  },

  async selectGroup(groupId) {
    this.currentGroup = groupId
    this.selectedAccountIds = []
    await this.loadAccounts(groupId)
  },

  closeAccounts() {
    this.resetAccountRefresh()
    this.currentGroup = null
    this.accounts = []
    this.selectedAccountIds = []
  },

  async loadAccounts(groupId) {
    const data = await api.get(`/api/accounts?group_id=${groupId}`)
    this.accounts = data.accounts || []
    const ids = new Set(this.accounts.map((account) => String(account.id)))
    this.selectedAccountIds = this.selectedAccountIds.filter((id) => ids.has(id))
    this.scheduleAccountRefresh()
  },

  setAccountSelection(rows) {
    this.selectedAccountIds = [...new Set(rows.map((row) => String(row.id)))]
  },

  toggleAllAccounts(selection) {
    this.selectedAccountIds = [...new Set(selection.map((account) => String(account.id)))]
  },

  toggleAccountRow(selection, row) {
    this.setAccountSelection(selection)
    void row
  },

  resetAccountRefresh() {
    clearTimeout(this.accountAutoRefreshTimer)
    this.accountAutoRefreshTimer = null
    this.accountAutoRefreshSeconds = ''
  },

  scheduleAccountRefresh() {
    clearTimeout(this.accountAutoRefreshTimer)
    this.accountAutoRefreshTimer = null
    const seconds = Number(this.accountAutoRefreshSeconds)
    if (!seconds || !this.currentGroup || !this.authenticated) return
    this.accountAutoRefreshTimer = setTimeout(async () => {
      this.accountAutoRefreshTimer = null
      const groupId = this.currentGroup
      try {
        await this.loadAccounts(groupId)
      } catch (error) {
        ElMessage.error(error.message)
        this.scheduleAccountRefresh()
      }
    }, seconds * 1000)
  },

  async toggleAccountEnabled(account) {
    const next = !account.enabled
    await api.put(`/api/accounts/${account.id}/enabled`, { enabled: next })
    ElMessage.success(next ? '账号已启用' : '账号已停用（仅可编辑/删除）')
    await this.loadAccounts(this.currentGroup)
  },

  async startAccounts(accountIds = this.selectedNumberIds) {
    const groupId = this.currentGroup
    const data = await api.post(`/api/groups/${groupId}/start`, {
      account_ids: accountIds.length ? accountIds : null,
    })
    ElMessage.success(data.queued ? `已入队 ${data.queued} 个账号任务` : '已触发调度')
    setTimeout(() => this.loadGroups(), 1200)
  },

  async runAccount(account) {
    const data = await api.post('/api/accounts/start', { account_ids: [account.id] })
    ElMessage.success(`任务已入队（${data.queued}）`)
    setTimeout(() => this.loadAccounts(this.currentGroup), 1000)
  },

  async stopAccount(account) {
    const data = await api.post(`/api/accounts/${account.id}/stop`)
    ElMessage.success(data.action === 'queued_removed' ? '已从队列移除' : '账号任务已停止')
    await this.loadAccounts(this.currentGroup)
  },

  async regenerateAccountFingerprint(account) {
    await api.post(`/api/accounts/${account.id}/regenerate-fingerprint`)
    ElMessage.success('指纹已更新')
    await this.loadAccounts(this.currentGroup)
  },

  async refreshAccountToken(account) {
    await api.post(`/api/accounts/${account.id}/refresh-token`)
    ElMessage.success(`账号 ${account.username} 开始刷新 Token`)
    await this.loadAccounts(this.currentGroup)
    this.pollTokenRefresh([Number(account.id)], 0)
  },

  pollTokenRefresh(ids, tried) {
    if (tried >= 900) return
    setTimeout(async () => {
      try {
        await this.loadAccounts(this.currentGroup)
        const refreshing = this.accounts.some((account) =>
          ids.includes(Number(account.id)) && ['token_queued', 'token_running'].includes(account.last_status))
        if (refreshing) this.pollTokenRefresh(ids, tried + 1)
      } catch {
        this.pollTokenRefresh(ids, tried + 1)
      }
    }, 2000)
  },

  async batchRefreshTokens(accountIds = this.selectedNumberIds) {
    const groupId = this.currentGroup
    const ids = accountIds.length ? accountIds : this.selectedNumberIds
    const data = await api.post(`/api/groups/${groupId}/refresh-tokens`, {
      account_ids: ids.length ? ids : null,
    })
    if (!data.queued) {
      ElMessage.warning(data.message || '没有需要刷新 Token 的启用账号')
      return data
    }
    ElMessage.success(`已提交 ${data.queued} 个账号刷新 Token`)
    await this.loadAccounts(groupId)
    this.pollTokenRefresh(data.accounts.map((account) => Number(account.id)), 0)
    return data
  },

  async batchDeleteAccounts(accountIds = this.selectedNumberIds) {
    const selected = this.accounts.filter((account) => accountIds.includes(Number(account.id)))
    const data = await api.post('/api/accounts/batch-delete', {
      account_ids: selected.map((account) => Number(account.id)),
    })
    ElMessage.success(`已删除 ${data.deleted} 个账号`)
    this.selectedAccountIds = []
    await this.loadAccounts(this.currentGroup)
    await this.loadGroups()
  },

  async saveAccount(account, body) {
    if (account) await api.put(`/api/accounts/${account.id}`, body)
    else await api.post('/api/accounts', body)
    await this.loadAccounts(this.currentGroup)
    await this.loadGroups()
  },

  async deleteAccount(account) {
    await api.del(`/api/accounts/${account.id}`)
    ElMessage.success('账号已删除')
    this.selectedAccountIds = this.selectedAccountIds.filter((id) => String(account.id) !== id)
    await this.loadAccounts(this.currentGroup)
    await this.loadGroups()
  },

  async batchRegenerateFingerprints(mode, accountIds = this.selectedNumberIds) {
    const groupId = this.currentGroup
    const ids = accountIds.length ? accountIds : this.selectedNumberIds
    const data = await api.post(`/api/groups/${groupId}/regenerate-fingerprints`, {
      mode,
      account_ids: ids.length ? ids : null,
    })
    ElMessage.success(`已更新 ${data.updated} 个账号的指纹`)
    await this.loadAccounts(groupId)
    return data
  },

  async startAccountFingerprintCheck(account) {
    await api.post(`/api/accounts/${account.id}/fp-check`)
    ElMessage.success(`账号 ${account.username} 开始指纹检测`)
    await this.loadAccounts(this.currentGroup)
    this.pollAccountFingerprintCheck(account.id, this.currentGroup, 0)
  },

  pollAccountFingerprintCheck(accountId, groupId, tried) {
    if (tried >= 60 || String(this.currentGroup) !== String(groupId)) return
    setTimeout(async () => {
      if (String(this.currentGroup) !== String(groupId)) return
      try {
        await this.loadAccounts(groupId)
        const account = this.accounts.find((item) => item.id === accountId)
        if (account?.fp_check_result === '检测中') {
          this.pollAccountFingerprintCheck(accountId, groupId, tried + 1)
        } else if (account) {
          if (account.fp_check_result === '已停止') ElMessage.success('指纹检测已停止')
          else if (String(account.fp_check_result || '').startsWith('失败')) ElMessage.error('指纹检测失败')
          else ElMessage.success(`检测结果：${account.fp_check_result}`)
        }
      } catch {
        this.pollAccountFingerprintCheck(accountId, groupId, tried + 1)
      }
    }, 3000)
  },

  async stopAccountFingerprintCheck(account) {
    const key = `a${account.id}`
    if (this.fpStopPending.has(key)) return
    this.fpStopPending.add(key)
    ElMessage.info(`账号 ${account.username} 正在停止检测…`)
    try {
      await api.post(`/api/accounts/${account.id}/fp-check/stop`)
      ElMessage.success(`账号 ${account.username} 的指纹检测已停止`)
    } finally {
      this.fpStopPending.delete(key)
      await this.loadAccounts(this.currentGroup)
    }
  },

  async startGroupFingerprintCheck(group) {
    await api.post(`/api/groups/${group.id}/fp-check`)
    ElMessage.success(`分组 ${group.name} 开始指纹模板检测`)
    await this.loadGroups()
    this.pollGroupFingerprintCheck(group.id, 0)
  },

  pollGroupFingerprintCheck(groupId, tried) {
    if (tried >= 60) return
    setTimeout(async () => {
      try {
        await this.loadGroups()
        const group = this.groups.find((item) => String(item.id) === String(groupId))
        if (!group) return
        if ((group.fp_check_result || '') === '检测中') {
          this.pollGroupFingerprintCheck(groupId, tried + 1)
        } else if (group.fp_check_result === '已停止') {
          ElMessage.success('指纹模板检测已停止')
        } else if (group.fp_check_result) {
          if (String(group.fp_check_result).startsWith('失败')) ElMessage.error('指纹模板检测失败')
          else ElMessage.success(`模板检测结果：${group.fp_check_result}`)
        }
      } catch {
        this.pollGroupFingerprintCheck(groupId, tried + 1)
      }
    }, 3000)
  },

  async stopGroupFingerprintCheck(group) {
    const key = `g${group.id}`
    if (this.fpStopPending.has(key)) return
    this.fpStopPending.add(key)
    ElMessage.info(`分组 ${group.name} 正在停止检测…`)
    try {
      await api.post(`/api/groups/${group.id}/fp-check/stop`)
      ElMessage.success(`分组 ${group.name} 的指纹模板检测已停止`)
    } finally {
      this.fpStopPending.delete(key)
      await this.loadGroups()
    }
  },

  async loadTasks() {
    const data = await api.get('/api/tasks?limit=100')
    this.tasks = data.tasks || []
    const count = (status) => this.tasks.filter((task) => task.status === status).length
    this.taskMetrics = {
      total: this.tasks.length,
      success: count('success'),
      failed: count('failed') + count('callback_failed'),
      running: count('queued') + count('running') + count('token_queued') + count('token_running') + count('pending'),
    }
  },

  async loadProxies({ silent = false } = {}) {
    const data = await api.get('/api/proxies')
    this.proxies = data.proxies || []
    if (!silent) await Promise.resolve()
  },

  async saveProxy(proxy, body) {
    if (proxy?.id) await api.put(`/api/proxies/${proxy.id}`, body)
    else await api.post('/api/proxies', body)
    await this.loadProxies()
  },

  async deleteProxy(proxy) {
    await api.del(`/api/proxies/${proxy.id}`)
    ElMessage.success('代理已删除')
    await this.loadProxies()
  },

  async testProxy(proxy) {
    await api.post(`/api/proxies/${proxy.id}/test`)
    const item = this.proxies.find((row) => row.id === proxy.id)
    if (item) {
      item.check_error = '检测中'
      item.testing = true
      item._testStartedAt = Date.now()
    }
    this.pollProxyTest(proxy.id, 0, Date.now())
  },

  async pollProxyExitIp(proxyId, maxTries = 20) {
    for (let tried = 0; tried < maxTries; tried += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000))
      await this.loadProxies({ silent: true })
      const proxy = this.proxies.find((item) => String(item.id) === String(proxyId))
      if (proxy?.exit_ip) return proxy.exit_ip
      const error = String(proxy?.check_error || '').trim()
      if (proxy && error && error !== '检测中') return ''
    }
    return ''
  },

  pollProxyTest(proxyId, tried, startedAt) {
    if (tried >= 40) return
    setTimeout(async () => {
      try {
        await this.loadProxies({ silent: true })
        const proxy = this.proxies.find((item) => String(item.id) === String(proxyId))
        if (!proxy) return
        const checkedAt = proxy.check_at ? new Date(String(proxy.check_at).replace(' ', 'T')).getTime() : 0
        const fresh = !startedAt || checkedAt > startedAt - 2000
        if (fresh && String(proxy.check_error || '').trim()) {
          ElMessage.error(`测试失败：${proxy.check_error}`)
          return
        }
        if (fresh && proxy.exit_ip) {
          ElMessage.success(`测试通过：出口 ${proxy.exit_ip} · ${proxy.latency_ms} ms`)
          return
        }
        this.pollProxyTest(proxyId, tried + 1, startedAt)
      } catch {
        this.pollProxyTest(proxyId, tried + 1, startedAt)
      }
    }, 3000)
  },

  async loadPhoneCountries({ platform, apiKey = '', savedCountry = '' } = {}) {
    const params = new URLSearchParams()
    if (platform) params.set('platform', platform)
    if (apiKey) params.set('api_key', apiKey)
    const query = params.toString() ? `?${params.toString()}` : ''
    try {
      const data = await api.get(`/api/settings/phone-countries${query}`)
      this.phoneCountries = data.countries || []
      this.phoneCountryError = data.error || ''
      if (savedCountry && this.phoneCountries.some((country) => country.code === savedCountry)) return savedCountry
      return ''
    } catch {
      this.phoneCountries = []
      return ''
    }
  },

  async testPhoneProvider(platform, apiKey = '') {
    const params = new URLSearchParams({ platform })
    if (apiKey) params.set('api_key', apiKey)
    const result = { balance: '', error: '' }
    try {
      const data = await api.get(`/api/settings/phone-balance?${params.toString()}`)
      result.balance = data.balance || ''
      result.error = data.detail || ''
    } catch (error) {
      result.error = error.message
    }
    await this.loadPhoneCountries({ platform, apiKey })
    return result
  },

  engineTitle() {
    const engine = this.settings.engine || {}
    const label = engineLabel(engine.engine)
    return engine.cloak_available === false ? `${label} · 降级` : label
  },
})

export const BUSY_ACCOUNT_STATUSES = new Set(['queued', 'running', 'token_queued', 'token_running'])

export function isAccountBusy(account) {
  return BUSY_ACCOUNT_STATUSES.has(account?.last_status)
}

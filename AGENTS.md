# AGENTS.md — freedom-accounts 开发约定

> 本文件面向**所有在此仓库上工作的开发者与 AI 编码进程**，是仓库的强制契约入口。
> 前端（`frontend/`）的任何改动都必须符合 [`DESIGN.md`](./DESIGN.md)。
> 本文件是**执行摘要 + 强制流程**，`DESIGN.md` 是**前端权威规范**；两者冲突时以 `DESIGN.md` 为准。

---

## 0. 改前端之前，先做这三件事

1. **读规范**：读完 [`DESIGN.md`](./DESIGN.md)，重点看架构职责、token、组件和验证。
2. **先看真实实现**：读目标页面 / 弹窗 / 组件、`stores/app.js` 中对应动作和 `utils/status.js` 中的状态映射。
3. **复用，不发明**：表格、表单、按钮、标签、下拉、分页、对话框、抽屉、消息和确认框优先使用 Element Plus 现有组件；只有可复用的页面布局和业务控件才补自定义样式。

改完必跑最低校验：

```bash
cd frontend && npm run build
```

布局、交互、状态或明暗模式变化时，用 `npm run dev` 配合后端检查受影响页面。

---

## 1. 三条铁律

| # | 规则 | 反例 | 正例 |
| --- | --- | --- | --- |
| 1 | 新增自定义业务样式禁止硬编码色值 | `color: #6e6e73` | `color: var(--fa-muted)` |
| 2 | 自定义卡片不使用层级阴影，靠 1px 描边 + 底色区分 | `.card { box-shadow: 0 2px 8px … }` | `border: 1px solid var(--fa-line)` |
| 3 | 全站只有一个品牌强调色 | 新开一个蓝 `#0a84ff` | 一律 `var(--fa-brand)` |

> Element Plus 自身的组件样式和语义状态色（如 `--el-color-danger`）可直接使用。选中态可用 `box-shadow: 0 0 0 1px var(--fa-brand)` 模拟加粗描边，不改变布局尺寸。

---

## 2. 文件职责（不要越界）

| 文件 | 可以改 | 不可以改 |
| --- | --- | --- |
| `frontend/index.html` | 应用入口配置 | 生产脚本路径和根容器结构 |
| `frontend/src/main.js` | 注册新 Element Plus 组件 | 改全局引入顺序和 dark CSS vars 加载 |
| `frontend/src/styles/main.css` | 全局 token、布局和少量共享类 | 顺手重构已有组件类；改 token 前先查引用 |
| `frontend/src/views/` | 路由页面 | 直接裸写 `fetch` |
| `frontend/src/dialogs/` | 表单、详情和批量弹窗 | 越权复用为无关业务的通用组件 |
| `frontend/src/components/` | 跨页面业务控件 | 放只属于单页的逻辑 |
| `frontend/src/stores/app.js` | 共享状态和 `/api/*` 编排 | **`/api/*` 路径与请求 / 响应字段擅自变更** |
| `frontend/src/utils/status.js` | 状态文字、类型和排序映射 | 在页面里重复硬编码状态映射 |
| `frontend/dist/` | 由 `npm run build` 生成 | 手工编辑产物 |

路由使用 hash 模式，生产 base 是 `/static/`。组件局部状态样式写在 `<style scoped>`；
确需覆盖 Element Plus 内部类时优先限定在组件作用域。

---

## 3. 后端契约（冻结）

前端依赖以下接口，**路径与字段均不得改动**。需要扩展时改后端，并同步更新本表和前端调用点。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录，返回 token |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/auth/me` | 当前用户（未登录返回 401） |
| POST | `/api/auth/change-password` | 修改管理员密码 |
| GET | `/api/meta` | 注册表下发：`login_types`（流程适配器）/ `group_types`（平台注册表），驱动前端下拉 |
| GET / POST | `/api/groups` | 分组列表 / 新建（含 `fingerprint_template` 指纹模板、`proxy_id` 分组级代理、`phone_platform` 分组级接码平台，空值跟随系统设置；列表附带 `browser_open` 分组常驻浏览器状态） |
| PUT / DELETE | `/api/groups/{id}` | 更新（含 `proxy_id`）/ 删除分组 |
| POST | `/api/groups/{id}/start` | 分组一键执行；body 可选 `account_ids`，有值只处理选中账号，空/缺省处理全部账号。仍先同步，且入队上游状态 `error` 或无上游账号 ID 的本地手动启用账号。执行前校验密码必填；2FA 选填，已配置时须是可生成验证码的有效 TOTP |
| POST | `/api/groups/{id}/open-browser` | 打开常驻交互浏览器（本地 SDK 引擎专用：配置了 `cloak_cdp_url` 时 409 拒绝）。用分组指纹模板（无模板则全随机，seed 必随机）+ 分组代理、有头模式；按组幂等（`reused:true` 表示复用已开窗口），不自动关闭，`/close-browser` 或服务停止时关闭 |
| POST | `/api/groups/{id}/close-browser` | 关闭该分组的常驻交互浏览器（无会话时 `closed:false`，幂等） |
| POST | `/api/groups/{id}/regenerate-fingerprints` | 批量换指纹（`mode`: seed_only / from_template / random；body 可选 `account_ids`，有值只改选中账号，空/缺省改全部账号） |
| POST | `/api/groups/{id}/sync-accounts` | 同步上游账号，身份键=上游 `remote_id`：已存在→仅更新上游字段（username 显示名取 email、`remote_status`/`remote_remark` 独立列；密码/2FA/指纹/代理等本地属性不动）；唯一本地手动行与唯一上游 email/用户名身份一一匹配时回填 `remote_id` 和上游字段，避免重复新建；上游没有的 synced 行删除；新增按分组指纹模板落库；歧义匹配及与上游账号重复的本地账号全部停用（body 可选 `dry_run`，返回含 `disabled` 计数）。上游状态由适配器转中文（normal/quota_exhausted/rate_limited/disabled/error/refresh_backoff → 正常/配额耗尽/限流中/已停用/错误/退避中），仅展示、不影响本地 enabled |
| POST | `/api/groups/{id}/refresh-tokens` | 一键刷新 Token；先同步上游，再按 `account_ids`（空/缺省=全部）筛选启用且上游状态「正常」的账号。批量只处理 Token 已可解析、剩余寿命 ≤30 分钟且非四种运行态的账号，账号间随机间隔 5–20 秒；全局只允许一个 Token 刷新队列，执行过程写入 `operation=token_refresh` 任务日志并回写 `token_refresh_result` / `token_refresh_at` / 新过期时间 |
| POST | `/api/groups/{id}/fp-check` | 指纹模板检测：用分组模板生成代表性指纹验证可用性（后台执行，结果写 `groups.fp_check_result`）；前置校验检测地址（分组覆盖 > 系统设置），两处皆空返回 400 提示先配置 |
| POST | `/api/groups/{id}/fp-check/stop` | 停止分组指纹模板检测：取消后台任务并等待指纹浏览器关闭，结果落为「已停止」；无活跃任务且无「检测中」残留时 409 |
| GET / POST | `/api/accounts` | 账号列表（`?group_id=`，行内含 `proxy_name`、`remote_status`（已转中文，仅展示）、`remote_remark`、`reset_credits`（反序列化后的重置明细数组；次数由数组长度推导）、`browser_open`）/ 新建（同分组内按账号名大小写不敏感查重，已存在返回 `exists:true` 并跳过；含 `enabled` 启用状态、`proxy_id` 账号级代理；新建空环境时 `browser_mode=inherit`、`phone_platform=inherit`、`proxy_id=null`、`fingerprint={}`，分别继承分组/系统模式、分组/系统接码平台、分组代理和分组指纹模板） |
| PUT / DELETE | `/api/accounts/{id}` | 更新（含 `proxy_id` 关联代理）/ 删除账号 |
| PUT | `/api/accounts/{id}/enabled` | 启用/停用账号（`queued` / `running` / `token_queued` / `token_running` 禁止停用；停用账号仅允许编辑/删除） |
| POST | `/api/accounts/{id}/open-browser` | 按账号已保存指纹打开常驻交互浏览器（本地 SDK 引擎专用，CDP 配置时 409 拒绝；停用或运行态账号 409 拒绝）。代理按账号 > 分组解析，有头模式，按账号幂等（`reused:true` 表示复用已开窗口） |
| POST | `/api/accounts/{id}/close-browser` | 关闭该账号的常驻交互浏览器（无会话时 `closed:false`，幂等） |
| POST | `/api/accounts/start` | 按账号批量执行任务（自动跳过停用账号和四种运行态账号，`blocked` 返回跳过计数；入队后最新状态为 `queued`）。执行前校验密码必填；2FA 选填，已配置时须是可生成验证码的有效 TOTP |
| POST | `/api/accounts/{id}/stop` | 优雅停止任务：队列中直接移除；执行中取消后续流程并等待指纹浏览器关闭，任务与账号最新状态落为 `cancelled`。仅支持账号任务，不支持刷新 Token |
| POST | `/api/accounts/{id}/refresh-token` | 账号级刷新 Token；要求启用、上游状态「正常」、过期时间可解析且非运行态，忽略批量用的 30 分钟窗口；成功入队后写入 `token_refresh` 任务日志 |
| POST | `/api/accounts/{id}/reset-credits` | 手动刷新重置明细；要求已同步上游 ID。当前仅 CPR 实现适配器查询，返回反序列化后的 `reset_credits`（`id` / `expires_at` / `status`，状态不做映射）并整体落库；不单独存储次数，展示次数由数组长度推导。同步与账号列表轮询不触发上游查询 |
| POST | `/api/accounts/batch-delete` | 批量删除选中账号；`account_ids` 必填，任一账号处于四种运行态时整批 409 拒绝 |
| POST | `/api/accounts/{id}/regenerate-fingerprint` | 重新生成指纹；四种运行态账号 409 拒绝 |
| POST | `/api/accounts/{id}/fp-check` | 触发指纹检测（后台浏览器打开检测站→点 #retest→读 #risk-badge/#score-value，结果写回 `fp_check_result`，形如 高风险/80）；四种运行态账号 409 拒绝；前置校验检测地址（分组覆盖 > 系统设置），两处皆空返回 400 提示先配置 |
| POST | `/api/accounts/{id}/fp-check/stop` | 停止账号指纹检测：取消后台任务并等待指纹浏览器关闭，结果落为「已停止」；无活跃任务且无「检测中」残留时 409 |
| GET | `/api/accounts/{id}/tasks` | 该账号的任务记录 |
| GET | `/api/tasks` | 任务列表（`?status=` `?limit=`） |
| GET | `/api/tasks/{id}` | 任务详情 |
| GET / POST | `/api/proxies` | 代理列表（含 `linked_accounts` 关联数与 `server_masked` 掩码地址）/ 新建（`name`、`server`、`custom_geo`、`country/region/city/timezone/locale`） |
| PUT / DELETE | `/api/proxies/{id}` | 更新（`server` 留空保留原地址）/ 删除（仍被账号关联时返回 409） |
| POST | `/api/proxies/{id}/test` | 测试连接：经代理请求 ipify 检测出口 IP 与耗时，后台执行，结果写回 `exit_ip` / `latency_ms` / `check_at` / `check_error` |
| GET / PUT | `/api/settings` | 系统设置读写（含 `log_retention_days` 日志保留天数，默认 3；`token_refresh_interval_seconds` Token 自动刷新间隔秒数，默认 3600，范围 60–2592000；`fp_check_url` 指纹检测站点，分组可用 `fp_check_url` 覆盖；`phone_verification_mode` OpenAI 手机号验证模式，默认 `manual`；`auto` 必须配置国家与加密 Key，运行时缺失自动回退 manual；`phone_verification_platform` 默认接码平台，分组 `phone_platform` 空值时生效；`default_geo_country/region/city/timezone/locale` 全局默认时区位置，代理弹窗开启「自定义时区位置」时预填；`site_page_title/site_main_title/site_subtitle` 站点品牌原始配置，空值回退默认） |
| GET | `/api/site-settings` | 公开站点品牌生效值（`site_page_title/site_main_title/site_subtitle`）；无需登录，空配置返回内置默认 |
| GET | `/api/settings/phone-countries` | 读取当前接码适配器的 `get_countries`；可选 `?platform=` 覆盖已保存平台、`?api_key=` 覆盖已保存 Key；返回 `{countries:[{code,name}]}`。Key 缺失或调用失败时返回空数组 |
| GET | `/api/settings/phone-balance` | 查询接码平台余额；可选 `?platform=` 覆盖已保存平台、`?api_key=` 覆盖已保存 Key，返回 `{balance}`。无 Key 或平台不支持返回空字符串 |
| GET | `/api/settings/page-countries` | 读取 OpenAI 页面国家映射；返回 `{countries:[{code,name,dial_code}]}`，`code` 是两位 ISO 国家编码，区别于接码平台国家 ID |
| GET | `/api/geo/lookup` | IP 地理解析（ipwho.is，仅代理弹窗「按出口 IP 解析」使用）：`?ip=` 指定地址；不带参数时先经 ipify 取本机出口 IP 再解析，ipify 不可达时回退裸 `ipwho.is`。返回 `{ok, ip, country, region, city, timezone, locale, error}`（locale 按国家代码映射 BCP47，未知回退 en-US） |
| POST | `/api/logs/prune` | 手动触发日志清理（正常由后台每小时自动清理） |

所有接口响应中的时间字段统一为 Unix 毫秒时间戳（含任务步骤时间 `steps[].t` 和嵌套明细 `expires_at`）；空值保持空值。浏览器按本地时区格式化展示。

### 代理生效链路（2026-09-21）

- 优先级：**账号 `accounts.proxy_id` > 分组 `groups.proxy_id`**，两者皆空 = 直连。
- 解析入口 `browser.resolve_proxy(account_proxy_id, group_proxy_id)` 返回完整代理 URL；`scheduler._execute`（账号任务）与 `fpcheck.run_check` / `run_group_check`（指纹检测）都会先解析再传给 `browser.launch_for_account(..., proxy_server=...)`。
- 指纹检测地址解析入口 `fpcheck.resolve_check_url(group_row)`：**分组 `fp_check_url` > 系统设置 `fp_check_url`**；两处皆空返回 `None`（不再静默回退内置默认），调用方须提示 `fpcheck.NO_URL_MSG`。后台任务兜底会把「失败: 未配置…」写回 `fp_check_result`；API 层在启动前已用同一逻辑拦截（400）。
- 三个引擎均支持：cloakserve CDP 以 `&proxy=<url>` 查询参数下发；CloakBrowser SDK 与 Playwright 用 `proxy={"server": url}` 启动参数。

### 指纹变更二次确认 + 常驻浏览器（2026-09-21）

- **保存前指纹确认**：账号与分组表单在提交前用 `frontend/src/utils/fingerprint.js` 的 `fpChangedFields()` 对比新旧指纹（账号用 `fingerprint`，分组模板用 `fingerprint_template`），任一字段差异即用 `ElMessageBox.confirm` 列出中文变更项（`FP_FIELD_LABEL`）。前端把关，后端不加锁。
- **常驻浏览器**：`browser.open_managed_browser(fp, mode, key, proxy_server)` 维护 `_MANUAL_SESSIONS`（分组键 `g{group_id}_manual`、账号键 `a{account_id}_manual`，每键一个；新开窗口会释放其他手动会话座位），内部 `asyncio.Task` 持有 context，取消时经 `finally` 关浏览器；`close_managed_session` 幂等。API：`/open-browser`（CDP 已配置 → 409；headed 模式）与 `/close-browser`。Vue 页面用 `appStore.localEngine` 控制浏览器按钮显隐 —— **仅本地 SDK 模式（CDP 为空）可见**。

### 三个已知的响应格式陷阱

1. `GET /api/tasks/{id}` **只返回 `tasks` 表原始行**，不含 `group_name` / `username`。详情标题必须由列表行带入。
2. 同一接口的 `steps` 是 **JSON 字符串**，而列表接口的 `steps` 已被解析成数组。两处要分别处理。
3. `result_json` 默认值是 `{}`（truthy）。判断"有无结果"时必须判空对象，不能只判断真值。

### 回调与适配器约定（2026-09 起）

- 分组不再有「回调地址 / Header JSON」：上游集成全部在**流程适配器内部**完成，不在页面暴露。
- 适配器可选实现 6 个凭证操作：`list_accounts` / `get_account` / `auth_link` / `redeem_token` / `refresh_token` / `get_reset_credits`（见 `app/automation/flows/adapters/base.py`）。每次调用写 `adapter_logs` 表；当前 `refresh_token` 与 `get_reset_credits` 由账号页面 API 触发，其余凭证操作仍仅供同步/任务执行内部调用。
- `groups.callback_url` / `header_json` 为遗留列：数据库保留、接口不再接受、列表不再返回。

### Token 自动刷新（2026-09-22）

- 应用启动后运行内部 asyncio 定时任务：启动时先巡检一次，之后按系统设置 `token_refresh_interval_seconds` 休眠，默认 3600 秒。
- 巡检范围是所有适配器真正实现 `refresh_token` 的分组；每组先同步上游，再复用一键批量筛选规则（启用 + 上游正常 + Token 过期时间可解析 + 剩余寿命 ≤30 分钟）。
- 多个分组的到期账号合并为一个串行队列，账号间仍随机间隔 5–20 秒；正在刷新的账号跳过本轮。
- 账号最新运行态包括 `never`（未运行）、`queued`（任务队列中）、`running`（正在执行）、`token_queued`（刷新 Token 队列中）、`token_running`（正在刷新 Token）、`success`（已完成）、`failed`（失败）和 `cancelled`（已手动停止）；四种运行态统一禁止重复执行、刷新、停用、删除、换指纹和指纹检测。

### OpenAI 授权任务（sub2api / cpr 通用架构，2026-09-22）

复刻 s2accheck 浏览器插件（`/Users/ibean/Documents/s2accheck`）的 10 步授权链路。**OpenAI 浏览器授权段全适配器通用**，执行任务时唯一差异是「拿授权 URL / 回调换凭证」的上游 API：

- **共享浏览器段** `app/automation/flows/adapters/_openai_browser.py` 的 `run_browser_auth(ctx, auth_url, email, password, totp_secret, steps, *, cdp_engine=False, phone_handler=None)`：清 openai/chatgpt cookie → 打开授权页 → 自动填邮箱/密码/TOTP（选择器与插件一致：`button[data-dd-action-name="Continue"]` 等；打开页面/邮箱 Continue 后 5–10 秒，fill 与 click 间 3–8 秒，元素未就绪检查 5 次、间隔 5–10 秒）→ 持续点 Continue → 轮询等 localhost 回调（120s 超时）→ 返回 `{callback_url, code, state}`。另有 `parse_callback` / `is_localhost` 工具。新增 OpenAI 类适配器禁止重写这段。
- **手机号验证门**：精确匹配 `https://auth.openai.com/add-phone`（忽略 query/hash）。CDP 环境立即终止任务；本地 SDK 保持页面不动、不点 Continue，无限等待用户输入手机号/验证码，URL 离开该页后重置回调等待并继续。自动接码平台统一实现 `automation/phone/base.py` 的 `get_balance` / `get_number` / `get_code` / `confirm_received`，返回规范 `PhoneOrder(phone, provider_order_id)`；注册表在 `automation/phone/registry.py`，当前仅登记 HeroSMS 骨架（底层协议未实现）。系统设置 `phone_verification_mode=auto` 且平台/国家/Key 齐全时，调度器注入 `_phone_verification.provider_phone_verification`；平台不支持、配置缺失或自动执行失败时回退手动。`phone_handler(page, email, steps)` 仍是自动服务的注入点。
- **flow = 纯编排**：`auth_link`（上游拿授权 URL）→ `run_browser_auth`（共享段）→ `redeem_token`（上游换凭证）。sub2api 与 cpr 的 `run_async` 结构完全相同；`run_sync` 一律报「仅支持异步引擎」。无上游 ID 的本地手动账号可参与一键执行；CPR 请求授权链接时省略 `accountId`。
- **执行冷却**：单个账号任务结束并回写结果后，调度器保留该组并发槽位随机等待 15–30 秒，再让该槽位的下一个排队账号获取。
- **上游差异只在凭证操作**：
  - sub2api：`POST {login_url}/api/v1/openai/generate-auth-url {account_id}` → `{session_id, auth_url}`；`POST /openai/exchange-code {code, state, session_id}`（重试 5 次）；成功后 best-effort `recover-state` + `schedulable`。Header `x-api-key`；响应 envelope 宽容解析；账号按 email 匹配、`accounts.remote_id` 优先；`refresh_token` / `get_reset_credits` 未实现。
  - cpr：`POST /api/admin/accounts/oauth/start` → `{flowId, authorizationUrl}`；`POST /api/admin/accounts/oauth/complete {flowId, callbackUrl}`；见文件头 wire contract。
- **flow 签名扩展**：`run_flow(..., group=..., account=..., cdp_engine=...)` 把分组/账号行和引擎策略透传给 flow。scheduler 是唯一调用方。
- `upstream_key`（上游 API Key）必填，缺失时任务/同步均报错提示。sub2api 的 `login_url` 填站点根（自动补 `/api/v1/admin` 前缀，已带则原样）。

---

## 4. 新增一个页面 / 区块

当前使用 Vue Router，不使用旧版 `TAB_META` / `switchTab()` 流程。标准见 `DESIGN.md` §2：

1. 在 `frontend/src/router/index.js` 添加懒加载路由和 `meta.title` / `meta.sub`。
2. 在 `frontend/src/components/SideNav.vue` 的 `items` 里登记导航项和 Element Plus 图标。
3. 在 `frontend/src/views/` 建页面；主操作放在页面自身的 `.panel-head` 右侧。
4. 跨页面共享请求放 `frontend/src/stores/app.js`，状态文案放 `frontend/src/utils/status.js`。

---

## 5. 高频 token 速查

| 要什么 | 用什么 |
| --- | --- |
| 页面底色 / 表面 | `--fa-page` / `--fa-surface` |
| 主文字 / 次级文字 | `--fa-ink` / `--fa-muted` |
| 描边 | `--fa-line` |
| 品牌强调 / 浅底 | `--fa-brand` / `--fa-brand-soft` |
| 成功 / 危险 / 警告 / 中性 | Element Plus 的 `--el-color-success` / `--el-color-danger` / `--el-color-warning` / `--el-color-info` |

完整清单见 `DESIGN.md` §3。新增颜色先复用 token 或 Element Plus 语义变量。

---

## 6. 业务状态 → 视觉

状态映射集中在 `frontend/src/utils/status.js` 的 `STATUS_MAP` / `CALLBACK_MAP`。**新增状态必须在这两张表登记**，否则会落到兜底文案。状态一律「颜色 + 文字」双重编码，不靠颜色单独表意。

---

## 7. 提交前自检清单

- [ ] `cd frontend && npm run build` 通过
- [ ] 没有新增硬编码业务色值；新颜色走 `--fa-*` 或 Element Plus 语义变量
- [ ] 新状态已登记到 `frontend/src/utils/status.js`
- [ ] 表格长文本截断、空状态中文文案、加载和错误反馈完整
- [ ] Element Plus 组件形态与既有页面一致（主操作唯一，行内操作紧凑）
- [ ] 明暗两套模式下都看过（左侧导航底部切换）
- [ ] `1100px` / `820px` 断点下没有水平溢出或关键控件不可用
- [ ] 接口路径与载荷字段未变
- [ ] 破坏性操作走 `ElMessageBox.confirm`，未使用原生 `confirm()`

---

## 8. 参考

| 资源 | 位置 |
| --- | --- |
| 前端规范（权威） | `DESIGN.md` |
| 前端入口文档 | `frontend/README.md` |
| 设计 token 与全局样式 | `frontend/src/styles/main.css` |
| 状态映射 | `frontend/src/utils/status.js` |
| 共享状态与 API 编排 | `frontend/src/stores/app.js` |

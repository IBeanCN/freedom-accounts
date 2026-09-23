# AGENTS.md — freedom-accounts 开发约定

> 本文件面向**所有在此仓库上工作的开发者与 AI 编码进程**，是仓库的强制契约入口。
> 前端（`web/`）的任何改动都必须符合 [`DESIGN.md`](./DESIGN.md)。
> 本文件是**执行摘要 + 强制流程**，`DESIGN.md` 是**权威详规**；两者冲突时以 `DESIGN.md` 为准。

---

## 0. 改前端之前，先做这三件事

1. **读规范**：至少读完 `DESIGN.md` 的 §0（怎么用）、§1（设计原则）、§7（组件规范）、§11（接入指南）。
2. **复用，不发明**：需要按钮 / 徽标 / 表格 / 对话框时，先翻 `DESIGN.md` §7 找现成类名。只有确实不存在的组件才新增到 `web/style.css`，并回写进 `DESIGN.md` §7。
3. **改完必跑校验**：

```bash
node scripts/design-lint.mjs
```

校验输出 **0 ERROR** 才允许提交。这不是建议，是硬门槛。WARN 不阻断，但应逐条判断。

**涉及布局 / 间距 / 卡片结构的改动，还要跑几何校验**（结构断言查不出"卡片高度参差、按钮不贴底"这类问题）：

```bash
FA_PORT=8123 .venv/bin/python -m uvicorn app.main:app --port 8123 &   # 勿占用用户正在跑的 8000
.venv/bin/python scripts/layout-check.py --base http://127.0.0.1:8123
```

当前覆盖设置页：同排卡片等高、操作按钮贴底、无水平溢出、无过大空白、≤960px 收成单列。

---

## 1. 三条铁律

| # | 规则 | 反例 | 正例 |
| --- | --- | --- | --- |
| 1 | 业务样式禁止硬编码色值 | `color: #6e6e73` | `color: var(--fa-text-2)` |
| 2 | 卡片不使用层级阴影，靠 1px 描边 + 底色区分 | `.card { box-shadow: 0 2px 8px … }` | `border: 1px solid var(--fa-hairline)` |
| 3 | 全站只有一个强调色 | 新开一个蓝 `#0a84ff` | 一律 `var(--fa-accent)` |

> 例外：对话框与 Toast 可用 `--fa-shadow-modal` / `--fa-shadow-toast`；选中态可用 `box-shadow: 0 0 0 1px` 模拟加粗描边（不改变布局尺寸）。详见 `DESIGN.md` §6。

---

## 2. 文件职责（不要越界）

| 文件 | 可以改 | 不可以改 |
| --- | --- | --- |
| `web/tokens.css` | 新增变量 | 改已有变量的值（等于改全站，需评审） |
| `web/style.css` | 新增组件类 | 改已有组件类的视觉规格（先查引用点） |
| `web/index.html` | 自由 | — |
| `web/app.js` | 自由 | **`/api/*` 路径与请求 / 响应字段** |
| `scripts/design-lint.mjs` | 扩充规则 | 收紧规则前需先修掉存量问题 |
| `scripts/layout-check.py` | 扩充断言、加页面 | 放宽阈值（阈值就是规范本身） |

引入顺序固定为 `tokens.css` → `style.css`，样式统一挂载在 `/static` 下。**页面不写内联样式。**

---

## 3. 后端契约（冻结）

前端依赖以下接口，**路径与字段均不得改动**。需要扩展时改后端，并同步更新本表、`DESIGN.md` 与 `scripts/design-lint.mjs` 的白名单。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录，返回 token |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/auth/me` | 当前用户（未登录返回 401） |
| POST | `/api/auth/change-password` | 修改管理员密码 |
| GET | `/api/meta` | 注册表下发：`login_types`（流程适配器）/ `group_types`（平台注册表），驱动前端下拉 |
| GET / POST | `/api/groups` | 分组列表 / 新建（含 `fingerprint_template` 指纹模板、`proxy_id` 分组级代理） |
| PUT / DELETE | `/api/groups/{id}` | 更新（含 `proxy_id`）/ 删除分组 |
| POST | `/api/groups/{id}/start` | 分组一键执行；body 可选 `account_ids`，有值只处理选中账号，空/缺省处理全部账号。仍先同步，且入队上游状态 `error` 或无上游账号 ID 的本地手动启用账号。执行前校验密码必填；2FA 选填，已配置时须是可生成验证码的有效 TOTP |
| POST | `/api/groups/{id}/open-browser` | 打开常驻交互浏览器（本地 SDK 引擎专用：配置了 `cloak_cdp_url` 时 409 拒绝）。用分组指纹模板（无模板则全随机，seed 必随机）+ 分组代理、有头模式；按组幂等（`reused:true` 表示复用已开窗口），不自动关闭，`/close-browser` 或服务停止时关闭 |
| POST | `/api/groups/{id}/close-browser` | 关闭该分组的常驻交互浏览器（无会话时 `closed:false`，幂等） |
| POST | `/api/groups/{id}/regenerate-fingerprints` | 批量换指纹（`mode`: seed_only / from_template / random；body 可选 `account_ids`，有值只改选中账号，空/缺省改全部账号） |
| POST | `/api/groups/{id}/sync-accounts` | 同步上游账号，身份键=上游 `remote_id`：已存在→仅更新上游字段（username 显示名取 email、`remote_status`/`remote_remark` 独立列；密码/2FA/指纹/代理等本地属性不动）；上游没有的 synced 行删除；新增按分组指纹模板落库；与上游账号（email/用户名）重复的本地账号全部停用（body 可选 `dry_run`，返回含 `disabled` 计数）。上游状态由适配器转中文（normal/quota_exhausted/rate_limited/disabled/error/refresh_backoff → 正常/配额耗尽/限流中/已停用/错误/退避中），仅展示、不影响本地 enabled |
| POST | `/api/groups/{id}/refresh-tokens` | 一键刷新 Token；先同步上游，再按 `account_ids`（空/缺省=全部）筛选启用且上游状态「正常」的账号。批量只处理 Token 已可解析、剩余寿命 ≤30 分钟且非四种运行态的账号，账号间随机间隔 5–20 秒；全局只允许一个 Token 刷新队列，执行过程写入 `operation=token_refresh` 任务日志并回写 `token_refresh_result` / `token_refresh_at` / 新过期时间 |
| POST | `/api/groups/{id}/fp-check` | 指纹模板检测：用分组模板生成代表性指纹验证可用性（后台执行，结果写 `groups.fp_check_result`）；前置校验检测地址（分组覆盖 > 系统设置），两处皆空返回 400 提示先配置 |
| GET / POST | `/api/accounts` | 账号列表（`?group_id=`，行内含 `proxy_name`、`remote_status`（已转中文，仅展示）、`remote_remark`）/ 新建（同分组内按账号名大小写不敏感查重，已存在返回 `exists:true` 并跳过；含 `enabled` 启用状态、`proxy_id` 账号级代理；新建空环境时 `browser_mode=inherit`、`proxy_id=null`、`fingerprint={}`，分别继承分组/系统模式、分组代理和分组指纹模板） |
| PUT / DELETE | `/api/accounts/{id}` | 更新（含 `proxy_id` 关联代理）/ 删除账号 |
| PUT | `/api/accounts/{id}/enabled` | 启用/停用账号（`queued` / `running` / `token_queued` / `token_running` 禁止停用；停用账号仅允许编辑/删除） |
| POST | `/api/accounts/start` | 按账号批量执行任务（自动跳过停用账号和四种运行态账号，`blocked` 返回跳过计数；入队后最新状态为 `queued`）。执行前校验密码必填；2FA 选填，已配置时须是可生成验证码的有效 TOTP |
| POST | `/api/accounts/{id}/stop` | 优雅停止任务：队列中直接移除；执行中取消后续流程并等待指纹浏览器关闭，任务与账号最新状态落为 `cancelled`。仅支持账号任务，不支持刷新 Token |
| POST | `/api/accounts/{id}/refresh-token` | 账号级刷新 Token；要求启用、上游状态「正常」、过期时间可解析且非运行态，忽略批量用的 30 分钟窗口；成功入队后写入 `token_refresh` 任务日志 |
| POST | `/api/accounts/batch-delete` | 批量删除选中账号；`account_ids` 必填，任一账号处于四种运行态时整批 409 拒绝 |
| POST | `/api/accounts/{id}/regenerate-fingerprint` | 重新生成指纹；四种运行态账号 409 拒绝 |
| POST | `/api/accounts/{id}/fp-check` | 触发指纹检测（后台浏览器打开检测站→点 #retest→读 #risk-badge/#score-value，结果写回 `fp_check_result`，形如 高风险/80）；四种运行态账号 409 拒绝；前置校验检测地址（分组覆盖 > 系统设置），两处皆空返回 400 提示先配置 |
| GET | `/api/accounts/{id}/tasks` | 该账号的任务记录 |
| GET | `/api/tasks` | 任务列表（`?status=` `?limit=`） |
| GET | `/api/tasks/{id}` | 任务详情 |
| GET / POST | `/api/proxies` | 代理列表（含 `linked_accounts` 关联数与 `server_masked` 掩码地址）/ 新建（`name`、`server`、`custom_geo`、`country/region/city/timezone/locale`） |
| PUT / DELETE | `/api/proxies/{id}` | 更新（`server` 留空保留原地址）/ 删除（仍被账号关联时返回 409） |
| POST | `/api/proxies/{id}/test` | 测试连接：经代理请求 ipify 检测出口 IP 与耗时，后台执行，结果写回 `exit_ip` / `latency_ms` / `check_at` / `check_error` |
| GET / PUT | `/api/settings` | 系统设置读写（含 `log_retention_days` 日志保留天数，默认 3；`token_refresh_interval_seconds` Token 自动刷新间隔秒数，默认 3600，范围 60–2592000；`fp_check_url` 指纹检测站点，分组可用 `fp_check_url` 覆盖；`default_geo_country/region/city/timezone/locale` 全局默认时区位置，代理弹窗开启「自定义时区位置」时预填） |
| GET | `/api/geo/lookup` | IP 地理解析（ipwho.is，仅代理弹窗「按出口 IP 解析」使用）：`?ip=` 指定地址；不带参数时先经 ipify 取本机出口 IP 再解析，ipify 不可达时回退裸 `ipwho.is`。返回 `{ok, ip, country, region, city, timezone, locale, error}`（locale 按国家代码映射 BCP47，未知回退 en-US） |
| POST | `/api/logs/prune` | 手动触发日志清理（正常由后台每小时自动清理） |

### 代理生效链路（2026-09-21）

- 优先级：**账号 `accounts.proxy_id` > 分组 `groups.proxy_id`**，两者皆空 = 直连。
- 解析入口 `browser.resolve_proxy(account_proxy_id, group_proxy_id)` 返回完整代理 URL；`scheduler._execute`（账号任务）与 `fpcheck.run_check` / `run_group_check`（指纹检测）都会先解析再传给 `browser.launch_for_account(..., proxy_server=...)`。
- 指纹检测地址解析入口 `fpcheck.resolve_check_url(group_row)`：**分组 `fp_check_url` > 系统设置 `fp_check_url`**；两处皆空返回 `None`（不再静默回退内置默认），调用方须提示 `fpcheck.NO_URL_MSG`。后台任务兜底会把「失败: 未配置…」写回 `fp_check_result`；API 层在启动前已用同一逻辑拦截（400）。
- 三个引擎均支持：cloakserve CDP 以 `&proxy=<url>` 查询参数下发；CloakBrowser SDK 与 Playwright 用 `proxy={"server": url}` 启动参数。

### 指纹变更二次确认 + 常驻浏览器（2026-09-21）

- **保存前指纹确认**：`app.js` 的 `confirmFpChange(oldFp, newFp, what)` 对比编辑前后的指纹（分组模板用 `fingerprint_template`，账号用 `fingerprint`），任一字段差异（含增删、`fpNorm` 归一空值/空白）即弹 `confirmDialog` 列出变更字段中文名（`FP_FIELD_LABEL`）。前端把关，后端不加锁。
- **常驻浏览器**：`browser.open_managed_browser(fp, mode, key, proxy_server)` 维护 `_MANUAL_SESSIONS`（键 `g{group_id}_manual`，每键一个），内部 `asyncio.Task` 持有 context，取消时经 `finally` 关浏览器；`close_managed_session` 幂等。API：`/open-browser`（CDP 已配置 → 409；headed 模式）与 `/close-browser`。前端按钮 `data-act="open-browser"` 默认 `hidden`，`applyOpenBrowserVisibility(cloak_cdp_url)` 在 `loadEngine`/`loadSettings`/CDP 保存后控制显隐 —— **仅本地 SDK 模式（CDP 为空）可见**。

### 三个已知的响应格式陷阱

1. `GET /api/tasks/{id}` **只返回 `tasks` 表原始行**，不含 `group_name` / `username`。详情标题必须由列表行带入。
2. 同一接口的 `steps` 是 **JSON 字符串**，而列表接口的 `steps` 已被解析成数组。两处要分别处理。
3. `result_json` 默认值是 `{}`（truthy）。判断"有无结果"时必须判空对象，不能只判断真值。

### 回调与适配器约定（2026-09 起）

- 分组不再有「回调地址 / Header JSON」：上游集成全部在**流程适配器内部**完成，不在页面暴露。
- 适配器可选实现 5 个凭证操作：`list_accounts` / `get_account` / `auth_link` / `redeem_token` / `refresh_token`（见 `flows/adapters/base.py`）。每次调用写 `adapter_logs` 表；当前仅 `refresh_token` 由账号页面 API 触发，其余凭证操作仍仅供同步/任务执行内部调用。
- `groups.callback_url` / `header_json` 为遗留列：数据库保留、接口不再接受、列表不再返回。

### Token 自动刷新（2026-09-22）

- 应用启动后运行内部 asyncio 定时任务：启动时先巡检一次，之后按系统设置 `token_refresh_interval_seconds` 休眠，默认 3600 秒。
- 巡检范围是所有适配器真正实现 `refresh_token` 的分组；每组先同步上游，再复用一键批量筛选规则（启用 + 上游正常 + Token 过期时间可解析 + 剩余寿命 ≤30 分钟）。
- 多个分组的到期账号合并为一个串行队列，账号间仍随机间隔 5–20 秒；正在刷新的账号跳过本轮。
- 账号最新运行态包括 `never`（未运行）、`queued`（任务队列中）、`running`（正在执行）、`token_queued`（刷新 Token 队列中）、`token_running`（正在刷新 Token）、`success`（已完成）、`failed`（失败）和 `cancelled`（已手动停止）；四种运行态统一禁止重复执行、刷新、停用、删除、换指纹和指纹检测。

### OpenAI 授权任务（sub2api / cpr 通用架构，2026-09-22）

复刻 s2accheck 浏览器插件（`/Users/ibean/Documents/s2accheck`）的 10 步授权链路。**OpenAI 浏览器授权段全适配器通用**，执行任务时唯一差异是「拿授权 URL / 回调换凭证」的上游 API：

- **共享浏览器段** `flows/adapters/_openai_browser.py` 的 `run_browser_auth(ctx, auth_url, email, password, totp_secret, steps)`：清 openai/chatgpt cookie → 打开授权页 → 自动填邮箱/密码/TOTP（选择器与插件一致：`button[data-dd-action-name="Continue"]` 等）→ 持续点 Continue → 轮询等 localhost 回调（300s 超时）→ 返回 `{callback_url, code, state}`。另有 `parse_callback` / `is_localhost` 工具。新增 OpenAI 类适配器禁止重写这段。
- **flow = 纯编排**：`auth_link`（上游拿授权 URL）→ `run_browser_auth`（共享段）→ `redeem_token`（上游换凭证）。sub2api 与 cpr 的 `run_async` 结构完全相同；`run_sync` 一律报「仅支持异步引擎」。无上游 ID 的本地手动账号可参与一键执行；CPR 请求授权链接时省略 `accountId`。
- **执行冷却**：单个账号任务结束并回写结果后，调度器保留该组并发槽位随机等待 15–30 秒，再让该槽位的下一个排队账号获取。
- **上游差异只在凭证操作**：
  - sub2api：`POST {login_url}/api/v1/openai/generate-auth-url {account_id}` → `{session_id, auth_url}`；`POST /openai/exchange-code {code, state, session_id}`（重试 5 次）；成功后 best-effort `recover-state` + `schedulable`。Header `x-api-key`；响应 envelope 宽容解析；账号按 email 匹配、`accounts.remote_id` 优先；`refresh_token` 未实现（上游无端点）。
  - cpr：`POST /api/admin/accounts/oauth/start` → `{flowId, authorizationUrl}`；`POST /api/admin/accounts/oauth/complete {flowId, callbackUrl}`；见文件头 wire contract。
- **flow 签名扩展**：`run_flow(..., group=..., account=...)` 把分组/账号行透传给 flow（registry.py，`TypeError` 兜底老 6 参签名）。scheduler 是唯一调用方。
- `upstream_key`（上游 API Key）必填，缺失时任务/同步均报错提示。sub2api 的 `login_url` 填站点根（自动补 `/api/v1/admin` 前缀，已带则原样）。

---

## 4. 新增一个页面 / 区块

`DESIGN.md` §11.2 有可直接复制的骨架代码。标准流程：

1. `.rail-nav` 内加 `<button class="rail-item" data-tab="reports">`，图标用 16px 内联 SVG。
2. 该页**有**主操作时，在 `.page-actions` 内加 `<div class="act-set hidden" data-for="reports">` 放该页主操作；没有主操作就不加（分组页即如此，其新建分组的唯一入口挂在标题行 `.section-head`）。
3. `app.js` 的 `TAB_META` 登记 `reports: { title, sub }`。
4. `app.js` 的 `switchTab()` 内按需追加 `if (tab === "reports") loadReports();`。

导航高亮、页面显隐、顶栏按钮、标题文案会全部自动生效。

---

## 5. 高频 token 速查

| 要什么 | 用什么 |
| --- | --- |
| 页面底色 / 卡片底色 | `--fa-parchment` / `--fa-canvas` |
| 主文字 / 次级 / 三级 | `--fa-ink` / `--fa-text-2` / `--fa-text-3` |
| 描边 / 分隔线 | `--fa-hairline` / `--fa-divider`（悬停加深用 `--fa-hairline-strong`） |
| 强调（按钮、链接、选中） | `--fa-accent`（悬停 `--fa-accent-hover`，浅底 `--fa-accent-soft`） |
| 成功 / 危险 / 警告 | `--fa-success` / `--fa-danger` / `--fa-warning`（各配 `-soft` 底色） |
| 正文 / 表格 / 标签 / 徽标 | `--fa-fs-body` / `--fa-fs-table` / `--fa-fs-label` / `--fa-fs-micro` |
| 间距 | `--fa-space-1`…`--fa-space-7`（4/8/12/16/24/32/48） |
| 圆角 | `--fa-radius-xs` / `-sm` / `-md` / `-lg` / `-pill` |
| 控件高度 | `--fa-control-height`（38px） |

完整清单见 `DESIGN.md` §3–§5。

---

## 6. 业务状态 → 视觉

状态映射集中在 `app.js` 的 `STATUS_MAP` / `CALLBACK_MAP`。**新增状态必须在这两张表登记**，否则会落到灰色兜底。状态一律「颜色 + 文字」双重编码，不靠颜色单独表意。

---

## 7. 提交前自检清单

- [ ] `node scripts/design-lint.mjs` 输出 0 ERROR
- [ ] 动了布局 / 卡片结构时，`scripts/layout-check.py` 全通过
- [ ] 没有新增硬编码色值、裸 px 字号 / 圆角
- [ ] 间距引用了 `--fa-space-*`（存量区块可暂缓，新代码不允许）
- [ ] 设置卡保持三段结构（`.setting-head` / `.setting-body` / `.setting-foot`），按钮收在 `.setting-foot` 内
- [ ] 新组件已回写进 `DESIGN.md` §7
- [ ] 明暗两套模式下都看过（顶栏 `#theme-btn` 切换）
- [ ] ≤960px 断点下导航收成图标条后仍可用
- [ ] 接口路径与载荷字段未变
- [ ] 破坏性操作走 `confirmDialog({ danger: true })`，未使用原生 `confirm()`

---

## 8. 参考

| 资源 | 位置 |
| --- | --- |
| 设计规范（权威） | `DESIGN.md` |
| 设计变量 | `web/tokens.css` |
| 组件库 | `web/style.css` |
| 规范校验器 | `scripts/design-lint.mjs` |
| 布局几何校验 | `scripts/layout-check.py`（需服务运行中） |
| 画布设计稿 | <https://ardot.tencent.com/file/728115104293393> |

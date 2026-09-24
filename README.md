# freedom-accounts

账号任务管理平台：分组管理 + 指纹浏览器（[CloakBrowser](https://github.com/CloakHQ/CloakBrowser) 方案）+ Playwright 页面自动化 + 流程适配器。Python FastAPI + asyncio 协程并发 + SQLite，开箱即用。

## 功能总览

| 模块 | 说明 |
|---|---|
| 分组管理 | 分组类型（如 `OpenAI-openai`）、名称、任务类型、任务地址、任务 Key 必填；并发数（默认 1）、账号间隔时间（默认 5000–10000ms 随机，填固定区间则按区间）、**指纹模板**（组内账号默认继承、seed 每账号自动随机——适配统一采购机型）可选 |
| 账号管理 | 账号 / 密码 / 可选 2FA（TOTP base32）；支持单条或批量入队任务 |
| 任务流程 | 流程适配器获取执行链接 → 指纹浏览器打开并完成页面流程（按需填账号、密码、TOTP）→ 适配器用回调凭证换取上游结果；上游集成全部在适配器内部完成 |
| 账号展示 | 默认按分组卡片展示，点击分组展开账号表格；分组卡片带一键执行 |
| 指纹设置 | 账号级指纹：seed、platform、brand、GPU 厂商/渲染器、CPU 核数、内存、分辨率、时区、语言、WebRTC、存储配额等（对应 CloakBrowser `--fingerprint-*` 全系列参数），支持一键随机生成；**分组级指纹模板**：新账号默认继承模板仅随机 seed；账号面板支持**批量换指纹**（仅换 seed / 按模板重建 / 完全随机） |
| 浏览器模式 | 有头/无头三级配置，**优先级：账号 > 分组 > 系统设置** |
| 系统设置 | 管理员改密、全局默认有头/无头、cloakserve CDP 地址；License Key 仅经 `.env` 文件配置（见下） |
| 架构 | asyncio 协程并发（每分组独立调度队列 + 并发信号量），SQLite(WAL) 存储，适配器 HTTP 请求由 httpx 异步发送 |

## 快速开始

```bash
cd freedom-accounts
./run.sh            # 首次运行自动创建 venv 并安装依赖
# 生产模式默认 http://127.0.0.1:10008  管理员用户名由 FA_ADMIN_USER 控制（默认 admin）
./run.sh --dev      # 后端 http://127.0.0.1:8000，前端 HMR http://127.0.0.1:5173
FA_PORT=8001 FRONTEND_PORT=5174 ./run.sh --dev
```

手动方式：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # 降级引擎需要；cloakbrowser 会自带二进制
(cd frontend && npm ci && npm run build)
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 启用 CloakBrowser（推荐）

**方式 A：cloakserve 远程 CDP（服务器部署推荐；与本地引擎互斥）**

```bash
docker run -d --name cloak -p 127.0.0.1:9222:9222 cloakhq/cloakbrowser cloakserve
```

然后在「系统设置」页填入 CDP 地址 `http://127.0.0.1:9222`。平台通过
`connect_over_cdp("/?fingerprint=<seed>")` 连接，每个账号 seed 对应独立隐身 Chrome
进程（源码级指纹伪装），运行结束自动调用 `/fingerprint/{seed}/close` 回收进程。
有头模式可在容器内经 Xvfb 渲染：`cloakserve --headless=false`。

**方式 B：本地 SDK（已预装）**

SDK 已装入项目 venv（cloakbrowser 0.5.10），隐身 Chromium 二进制（v145, darwin-arm64, free 层）已装至 `~/.cloakbrowser/`。使用 `launch_persistent_context_async` 原生异步 API，profile 持久化保留登录态。

> 安装排障：若 `python -m cloakbrowser install` 因网络失败（官方 CDN / github.com 直连被阻断），可走 `api.github.com` 的 release asset 通道手动下载：
> ```bash
> curl -L -H "Accept: application/octet-stream" -o cloak.tar.gz \
>   "https://api.github.com/repos/CloakHQ/CloakBrowser/releases/assets/<asset_id>"
> tar -xzf cloak.tar.gz -C ~/.cloakbrowser/chromium-<version>/
> xattr -dr com.apple.quarantine ~/.cloakbrowser/chromium-<version>/Chromium.app
> ```
> macOS 首次运行如被 Gatekeeper 拦截：右键 Chromium.app → 打开（仅一次）。

- Wrapper 免费（MIT）；新版二进制需免费 GitHub Key（1 并发）或 Pro Key（多并发）。
- 引擎选择是互斥模式：配置 CDP 时只使用 cloakserve CDP，失败不会降级本地 SDK/Playwright；CDP 留空时才使用本地 cloakbrowser SDK，未安装 SDK 时降级 Playwright Chromium + 上下文级伪装（UA/时区/语言/视口 + `--fingerprint-*` 参数透传，反检测能力弱于源码级方案）。
- 强防护站点（DataDome/Turnstile）建议**有头模式**运行。

## 适配器协议

分组不再配置回调地址或 Header JSON。适配器可选实现下列凭证操作，调用结果只写本地 `adapter_logs`，不暴露对外 HTTP 端点：

| 方法 | 用途 |
|---|---|
| `list_accounts` | 拉取上游账号，用于同步 |
| `get_account` | 查询单个上游账号 |
| `auth_link` | 获取上游授权链接 |
| `redeem_token` | 用浏览器回调中的授权凭证换取上游结果 |
| `refresh_token` | 刷新上游凭证；无对应上游端点时可不实现 |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `FA_ADMIN_PASSWORD` | admin123 | 初始管理员密码 |
| `FA_ADMIN_USER` | admin | 初始管理员用户名 |
| `FA_JWT_SECRET` | 随机占位 | 生产环境必须修改 |
| `FA_HOST` / `FA_PORT` | 127.0.0.1 / 8000 | 监听地址 |
| `FA_MAX_CONCURRENCY` | 5 | 单分组并发硬上限 |
| `FA_CALLBACK_TIMEOUT` | 15 | 上游适配器请求超时秒数 |

## 目录结构

```
app/
  core/       config / database(SQLite) / auth(JWT+argon2) / settings
  routers/    auth / groups / accounts / system(tasks+settings)
  automation/ fingerprint(指纹生成与参数映射) / browser(引擎启动与降级)
              flows(流程适配器，可按 group_type 插件化) / scheduler(并发调度)
frontend/    Vue 3 + Element Plus 前端（Vite 页面级拆分）
data/         platform.db 与浏览器 profile
```

前端构建产物输出到 `frontend/dist`，由 FastAPI 在 `/` 与 `/static` 下服务。

## 自定义登录流程

若目标站点需要新流程，在 `app/automation/flows/registry.py` 注册适配器，并把它追加到 `ADAPTERS`。当前内置类型为 `sub2api` 和 `cpr`。

## ⚠️ 使用边界

- 平台明文存储账号密码于本地 SQLite（自动化必需），请确保部署机安全；生产环境建议全盘加密与最小权限。
- 请仅用于你有合法授权的账号与站点；遵守目标站点条款与当地法律法规。

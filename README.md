# freedom-accounts · 批量上号平台

账号批量上号平台：分组管理 + 指纹浏览器（[CloakBrowser](https://github.com/CloakHQ/CloakBrowser) 方案）+ Playwright 页面自动化 + 上游回调。Python FastAPI + asyncio 协程并发 + SQLite，开箱即用。

## 功能总览

| 模块 | 说明 |
|---|---|
| 分组管理 | 分组类型（如 `OpenAI-openai`）、名称、上号类型、上号地址、上号 Key 必填；Header JSON、并发数（默认 1）、账号间隔时间（默认 5000–10000ms 随机，填固定区间则按区间）、**指纹模板**（组内账号默认继承、seed 每账号自动随机——适配统一采购机型）可选 |
| 账号管理 | 账号 / 密码 / 可选 2FA（TOTP base32）；支持单条或批量入队上号 |
| 上号流程 | 指纹浏览器打开上号地址 → Playwright 填账号密码 →（按需自动填 TOTP）→ 提交验证 → 结果 POST 回调至分组绑定的回调地址 |
| 账号展示 | 默认按分组卡片展示，点击分组展开账号表格；分组卡片带一键上号 |
| 指纹设置 | 账号级指纹：seed、platform、brand、GPU 厂商/渲染器、CPU 核数、内存、分辨率、时区、语言、WebRTC、存储配额等（对应 CloakBrowser `--fingerprint-*` 全系列参数），支持一键随机生成；**分组级指纹模板**：新账号默认继承模板仅随机 seed；账号面板支持**批量换指纹**（仅换 seed / 按模板重建 / 完全随机） |
| 浏览器模式 | 有头/无头三级配置，**优先级：账号 > 分组 > 系统设置** |
| 系统设置 | 管理员改密、全局默认有头/无头、cloakserve CDP 地址；License Key 仅经 `.env` 文件配置（见下） |
| 架构 | asyncio 协程并发（每分组独立调度队列 + 并发信号量），SQLite(WAL) 存储，回调 httpx 异步发送 |

## 快速开始

```bash
cd freedom-accounts
./run.sh            # 首次运行自动创建 venv 并安装依赖
# 默认 http://127.0.0.1:8000  管理员 admin / admin123（请立即在系统设置中修改）
```

手动方式：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # 降级引擎需要；cloakbrowser 会自带二进制
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 启用 CloakBrowser（推荐）

**方式 A：cloakserve 远程 CDP（服务器部署推荐，引擎优先级最高）**

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
- 引擎选择优先级：cloakserve CDP > 本地 cloakbrowser SDK > Playwright 降级。
- 未安装 cloakbrowser 时自动降级 Playwright Chromium + 上下文级伪装（UA/时区/语言/视口 + `--fingerprint-*` 参数透传，反检测能力弱于源码级方案）。
- 强防护站点（DataDome/Turnstile）建议**有头模式**运行。

## 回调协议

上号完成后，平台向分组配置的 `回调地址` 发送：

```json
POST <callback_url>
Authorization: Bearer <上号Key>
X-Upstream-Key: <上号Key>
<Header JSON 中配置的自定义头>

{
  "task_id": 1, "group_id": 1, "account_id": 1,
  "group_type": "OpenAI-openai", "username": "acc@example.com",
  "status": "success",          // success | failed
  "error": "",
  "result": {"logged_in": true, "url": "...", "title": "..."},
  "browser_mode": "headless", "engine": "cloakbrowser",
  "finished_at": "2026-09-21 10:00:00"
}
```

响应状态码 < 400 视为回调成功。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `FA_ADMIN_PASSWORD` | admin123 | 初始管理员密码 |
| `FA_JWT_SECRET` | 随机占位 | 生产环境必须修改 |
| `FA_HOST` / `FA_PORT` | 127.0.0.1 / 8000 | 监听地址 |
| `FA_MAX_CONCURRENCY` | 5 | 单分组并发硬上限 |
| `FA_CALLBACK_TIMEOUT` | 15 | 回调超时秒数 |

## 目录结构

```
app/
  core/       config / database(SQLite) / auth(JWT+argon2) / settings
  routers/    auth / groups / accounts / system(tasks+settings)
  automation/ fingerprint(指纹生成与参数映射) / browser(引擎启动与降级)
              flows(登录流程，可按 group_type 插件化) / scheduler(并发调度+回调)
web/          单页前端（原生 JS，无构建步骤）
data/         platform.db 与浏览器 profile
```

## 自定义登录流程

通用流程按常见选择器自动填写表单。若目标站点特殊，在 `app/automation/flows.py` 注册：

```python
FLOWS["OpenAI-openai"] = my_flow   # async def my_flow(ctx, username, password, totp, url, steps)
```

## ⚠️ 使用边界

- 平台明文存储账号密码于本地 SQLite（自动化必需），请确保部署机安全；生产环境建议全盘加密与最小权限。
- 请仅用于你有合法授权的账号与站点；遵守目标站点条款与当地法律法规。

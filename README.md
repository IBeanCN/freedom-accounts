# freedom-accounts

账号任务管理平台，用于把“分组配置、账号数据、指纹浏览器、页面流程和上游适配器”组织成可重复执行的任务。后端使用 FastAPI + asyncio + SQLite，前端使用 Vue 3 + Element Plus + Vite。

## 核心能力

- **分组与账号**：按分组配置任务地址、上游凭证、并发与节奏；账号支持单条或批量添加，并可同步上游账号。
- **指纹浏览器**：只用 CloakBrowser；未配置远程 CDP 时使用本地 SDK。不做 Playwright 降级——SDK 不可用或席位占满时直接报出原因。
- **任务调度**：每个分组有独立队列和并发控制，支持任务执行、Token 刷新、停止、任务日志和最近状态展示。
- **账号列表**：展示上游错误、指纹检测、代理和重置明细；重置次数由存储的明细数组推导，只在手动点击刷新时请求上游。
- **CPR 自动上号**：账号数据自动刷新成功后，上游状态为「错误」的启用账号，已配置密码且可选 2FA 有效时自动进入上号队列；排队或运行中的账号跳过。关闭账号数据自动刷新（间隔设为 0）即关闭此触发。CPR 上号失败时停用本地账号；成功后对有上游 ID 的账号查询详情，仍为「错误」时也停用，避免后续自动重复上号。手动停止不触发停用；详情校验失败只记录日志，不按旧状态停用。
- **扩展适配器**：上游账号同步、授权链接、凭证兑换、Token 刷新、重置明细查询等能力按适配器实现，新增流程不需要改动调度层。

## 快速开始

### Docker 一键启动

适合服务器或长期运行环境。

```bash
cp .env.example .env
./install.sh
```

`install.sh` 会交互式生成必要配置，并使用 Docker Compose 启动应用和 CloakBrowser 浏览器服务。

### 更新部署

已有 Docker 部署可以拉取最新代码后重新执行安装脚本：

```bash
git pull --ff-only
./install.sh
```

如果配置不需要变动，所有交互提示直接按回车即可保留现有 `.env` 和 `data/` 数据目录；脚本会自动重新构建镜像并启动服务。

### 本地开发

适合调试后端接口或前端页面。

```bash
test -f .env || cp .env.example .env
# 首次运行前在 .env 中填写 FA_ENCRYPTION_KEY
./run.sh
```

开发模式会启动 FastAPI 和 Vite 开发服务器。端口可通过环境变量覆盖：

```bash
FA_PORT=8001 FRONTEND_PORT=5174 ./run.sh
```

生产式本地运行：

```bash
./run.sh --prod
```

该命令会先构建前端，再由 FastAPI 托管 `frontend/dist`。

### 手动启动

如果不使用 `run.sh`，可以按依赖顺序执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cd frontend
npm ci
npm run build
cd ..

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

项目不做 Playwright Chromium 降级，因此无需执行 `playwright install chromium`；Playwright 仅作为操作浏览器上下文/远程 CDP 的驱动库使用。

## 配置

首次配置建议复制 `.env.example` 为 `.env`，不要把真实 `.env` 提交到仓库。

| 变量 | 是否必填 | 说明 |
|---|---|---|
| `FA_ENCRYPTION_KEY` | 必填 | Fernet 密钥，用于加密本地数据库中的密码、2FA 密钥、代理地址和上游 Key 等敏感字段 |
| `FA_ADMIN_USER` | 建议 | 初始管理员用户名，首次启动后可在系统设置中维护 |
| `FA_ADMIN_PASSWORD` | 生产必填 | 初始管理员密码；非本机监听时不允许使用开发默认值 |
| `FA_JWT_SECRET` | 生产必填 | 登录会话签名密钥；非本机监听时不允许使用内置默认值 |
| `FA_LISTEN_IP` / `FA_PORT` | 可选 | Docker 场景控制宿主机监听地址和端口；默认只监听本机 |
| `FA_DEBUG` | 可选 | 设为 `1` 才记录手机号验证页 DOM 诊断；`./run.sh --dev` 默认开启，`--prod` 和线上默认关闭 |
| `FA_MAX_CONCURRENCY` | 可选 | 单分组并发硬上限 |
| `FA_CALLBACK_TIMEOUT` | 可选 | 上游适配器请求超时秒数 |
| `CLOAKBROWSER_LICENSE_KEY` | 可选 | CloakBrowser 授权；只从 `.env` 读取，不能在页面中配置 |

生成 `FA_ENCRYPTION_KEY` 的通用方式：

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

生产环境还应准备独立的强随机 `FA_JWT_SECRET`：

```bash
openssl rand -hex 32
```

## 浏览器引擎

| 模式 | 触发条件 | 说明 |
|---|---|---|
| CloakBrowser CDP | 系统设置中配置了 cloakserve CDP 地址 | 适合容器或远程浏览器；失败时直接报错，不切到本地引擎 |
| CloakBrowser SDK | CDP 留空且本地已安装 SDK | 使用本机 SDK 与持久化浏览器上下文 |

**没有 Playwright 兜底**：自带 Chromium 不识别任何 `--fingerprint-*` 开关，降级运行等于指纹配置全部失效，
因此在 SDK 缺失或启动失败时直接报出原因，而不是悄悄换一个「看起来能跑」的浏览器。席位（套餐并发会话数）
占满时同样禁止启动并提示先关闭其他指纹浏览器窗口。

CloakBrowser 安装、镜像、授权和版本管理请参考官方项目：<https://github.com/CloakHQ/CloakBrowser>。

本地引擎中，同一账号的手动浏览器与自动授权任务共用
`data/browser_profiles/a{账号ID}_manual`，任务启动前先关闭该账号的手动窗口。
分组手动浏览器和指纹检测仍使用各自的独立目录；远程 CDP 的数据由远端服务管理。
系统设置 → 指纹配置 → 浏览器模式中的「自动授权前清理 Cookie」默认勾选，
该选项是系统默认；分组和账号表单支持「跟随上级 / 清理 / 不清理」，按账号 > 分组 > 系统覆盖。
账号和分组没有覆盖时，取消系统勾选并保存后，后续自动授权会保留 Cookie；此选项不清理 LocalStorage 等其他数据。
存量账号和分组迁移后默认跟随上级，旧客户端更新时省略覆盖字段会保留原配置。
原自动任务目录 `g{分组ID}_a{账号ID}` 保留在磁盘，但不再用于账号自动授权。

## 适配器扩展

适配器注册在 `app/automation/flows/registry.py`。当前内置 `sub2api` 和 `cpr`。

| 能力 | 用途 |
|---|---|
| `list_accounts` | 拉取上游账号并同步本地映射 |
| `get_account` | 查询单个上游账号 |
| `auth_link` | 获取浏览器流程需要的授权链接 |
| `redeem_token` | 用浏览器回调凭证换取上游结果 |
| `refresh_token` | 刷新上游 Token；上游不支持时不实现 |
| `get_reset_credits` | 查询重置次数与明细；当前 CPR 已实现，Sub2API 暂未对接 |

适配器调用会写入本地 `adapter_logs`，用于审计和排障；这些操作不直接暴露为公开上游接口。

## 目录结构

```text
app/
  core/        配置、SQLite、认证、加密和系统设置
  routers/     登录、分组、账号、系统与代理 API
  automation/  调度器、浏览器引擎、指纹、任务与流程适配器
frontend/      Vue 3 + Element Plus + Vite 前端
data/          本地数据库和浏览器运行数据
logs/          本地运行日志
```

前端构建产物输出到 `frontend/dist`，生产模式由 FastAPI 托管。

## 常用验证

后端语法检查：

```bash
.venv/bin/python -m compileall -q app
```

前端构建检查：

```bash
cd frontend
npm run build
```

## 安全与使用边界

- 本项目会处理账号凭据、2FA 密钥、上游 Key 和代理配置。数据库中的这些敏感字段使用 `FA_ENCRYPTION_KEY` 加密，但密钥、数据库和浏览器数据仍应视为高敏资产。
- 备份数据库时必须同时保护好备份文件和 `FA_ENCRYPTION_KEY`；丢失密钥会导致加密字段无法恢复。
- 生产环境使用强管理员密码、独立 JWT Secret、防火墙和 HTTPS 反向代理；避免直接把未受保护的服务暴露到公网。
- 请只处理你有明确授权的账号和站点，并遵守目标服务条款与当地法律法规。

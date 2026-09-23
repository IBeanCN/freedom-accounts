# freedom-accounts 设计规范

> 本文件是 **freedom-accounts（账号任务平台）** 视觉与交互的唯一权威说明，供后续前端开发直接参照。
> 配套的可执行文件为 `web/tokens.css`（设计变量）与 `web/style.css`（组件库）；画布设计稿见文末「设计稿索引」。

---

## 0. 这份文档怎么用

| 你要做的事 | 该看哪里 |
| --- | --- |
| **前端改动提交前** | 运行 `node scripts/design-lint.mjs`，必须 **0 ERROR** |
| 新写一个页面 / 区块 | 第 11 章「前端接入指南」，拿骨架代码起步 |
| 需要一个颜色 / 字号 / 间距 | 第 3–5 章查 token 名，**不要**凭感觉取值 |
| 需要一个现成控件 | 第 7 章「组件规范」，直接复用 `style.css` 里的类名 |
| 不确定某个业务状态用什么色 | 第 3.7 节「语义状态映射表」 |
| 想知道为什么这么设计 | 第 1 章「设计原则」、第 2 章「视觉基线」 |

**三条铁律**（违反即视为不符合规范）：

1. 业务样式里**禁止出现硬编码色值**（`#fff`、`rgb(...)`），一律引用 `var(--fa-*)`。
2. **卡片不使用阴影**。层级只由 1px 描边 + 底色变化区分（对话框、浮层除外）。
3. 全站**只有一个强调色** `--fa-accent`。语义色只允许出现在徽标、状态文字与危险操作上。

---

## 1. 设计原则

1. **内容优先，装饰退后。** 这是一个运维控制台，用户来这里是「看清状态、快速操作」，不是来欣赏界面的。任何不承载信息的视觉元素都应删掉。
2. **用留白和描边表达结构，而不是用线条和阴影堆砌。** 页面底色（羊皮纸灰）与卡片底色（纯白）之间的 1px 差异，已经足够划出层级。
3. **一屏之内只允许一个主操作。** 每个页面右上角只有一个 `btn-primary`；分组卡操作区的「一键执行」是局部主操作，用同色但降一档尺寸（`btn-sm`）表达。账号面板头部批量操作统一用 `.btn-secondary.btn-sm`。
4. **危险操作必须二次确认，且用颜色和措辞共同提示后果。** 确认框文案要说清「会连带删除什么」，而不是只问「确定吗」。
5. **状态用颜色 + 文字双重编码。** 色盲用户仅靠红色无法区分「失败」与「回调失败」，所以徽标里始终带文字。

---

## 2. 视觉基线

采用 **Apple 设计体系**，并针对控制台的信息密度做局部适配：

| 维度 | Apple 原生 | 本项目适配 | 理由 |
| --- | --- | --- | --- |
| 页面底色 | `#f5f5f7` 羊皮纸灰 | 沿用 | 与白色卡片的层级对比恰到好处 |
| 卡片底色 | `#ffffff` 纯白 | 沿用 | — |
| 强调色 | 单一 Action Blue | `#0066cc` | 全站唯一强调色 |
| 正文字号 | 17px | **14px** | 控制台需要一屏容纳更多信息 |
| 表格字号 | — | **13px** | 表格是信息最密的区域 |
| 控件高度 | 44px | **38px** | 缩小触控目标以提升密度（桌面端为主） |
| 卡片阴影 | 有 | **无** | 大面积阴影在密集列表里会显得脏 |
| 圆角 | 大圆角 | 8 / 11 / 18 / 999 | 按控件体量分档 |

**没有使用纯黑 `#000`。** 主文字用 `#1d1d1f`，保留一点影像质感，长时间阅读更舒适。

---

## 3. 色彩系统

所有色值定义在 `web/tokens.css`，前缀统一为 `--fa-`。下表 `Light` 与 `Dark` 两列分别是 `[data-theme="light"]` / `[data-theme="dark"]` 下的取值。

### 3.1 表面 Surface

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `--fa-canvas` | `#ffffff` | `#0b0b0c` | 卡片、对话框、表格、输入框 |
| `--fa-parchment` | `#f5f5f7` | `#131315` | 页面底色 |
| `--fa-pearl` | `#fafafc` | `#1a1a1c` | 次级表面：表头、空状态瓦片 |
| `--fa-rail` | `#1d1d1f` | `#17171a` | 左侧导航底 |
| `--fa-tile` | `#272729` | `#1f1f21` | 导航内的深色信息瓦片 |
| `--fa-rail-hover` | `#2f2f31` | `#26262a` | 导航项悬停 / 选中底色 |
| `--fa-tile-line` | `#3a3a3c` | `#34343a` | 深色表面上的描边 |

### 3.2 文字 Text

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `--fa-ink` | `#1d1d1f` | `#f5f5f7` | 主文字、表格内容、输入值 |
| `--fa-text-2` | `#6e6e73` | `#a1a1a6` | 次级文字：字段标签、行内说明 |
| `--fa-text-3` | `#86868b` | `#8e8e93` | 第三级：表头、占位符、时间戳、提示 |
| `--fa-on-accent` | `#ffffff` | `#ffffff` | 强调色之上的文字 |
| `--fa-on-rail` | `#f5f5f7` | `#f5f5f7` | 导航主文字 |
| `--fa-on-rail-2` | `#a1a1a6` | `#a1a1a6` | 导航次级文字 |
| `--fa-on-rail-3` | `#8e8e93` | `#8e8e93` | 导航第三级文字 |

> 只有三级文字灰。新增第四级灰意味着信息层级没想清楚 —— 请重新组织内容。

### 3.3 线条 Line

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `--fa-hairline` | `#e0e0e0` | `#2f2f31` | 卡片 / 输入框 / 表格外描边（默认态） |
| `--fa-hairline-strong` | `#d2d2d7` | `#45454a` | 卡片悬停态描边（比默认加深一档） |
| `--fa-divider` | `#f0f0f0` | `#232325` | 表格行分隔线、区块分隔线 |
| `--fa-segment-bg` | `#efeff1` | `#232325` | 分段控件底槽 |

### 3.4 强调色 Accent

| Token | Light | Dark | 用途 |
| --- | --- | --- | --- |
| `--fa-accent` | `#0066cc` | `#2997ff` | 主按钮底、链接、选中态、文字按钮 |
| `--fa-accent-hover` | `#0071e3` | `#409cff` | 悬停 |
| `--fa-accent-focus` | `#0071e3` | `#409cff` | 键盘焦点环 + 输入框聚焦描边 |
| `--fa-accent-soft` | `#e8f1fb` | `#0d1b2a` | 信息类徽标底 |

### 3.5 语义色 Semantic

| Token | Light | Dark | 含义 |
| --- | --- | --- | --- |
| `--fa-success` / `--fa-success-soft` | `#248a3d` / `#e9f6ee` | `#30d158` / `#10251a` | 成功、正常运行 |
| `--fa-danger` / `--fa-danger-soft` | `#d70015` / `#fdecee` | `#ff453a` / `#2a1113` | 失败、删除、不可逆操作 |
| `--fa-danger-hover` | `#b80012` | `#ff6961` | 危险实心按钮悬停 |
| `--fa-warning` / `--fa-warning-soft` | `#b25000` / `#fff3e6` | `#ff9f0a` / `#2a1c08` | 降级、排队中、已跳过 |
| `--fa-muted-soft` | `#f0f0f0` | `#232325` | 中性徽标底 |

### 3.6 暗色模式

- 切换方式：`<html data-theme="dark">`。**业务样式不需要任何改动**，因为所有组件都只引用 token。
- 首屏防闪白：`index.html` 的 `<head>` 内有一段同步脚本，在样式生效前确定主题。优先级为「用户显式选择（localStorage 的 `fa_theme`）> 系统外观偏好 `prefers-color-scheme`」。
- 暗色下强调色**调亮**（`#0066cc` → `#2997ff`），因为深底上蓝色需要更高亮度才能达到同等对比度。
- 暗色下卡片与页面底色的对比刻意做得比浅色更弱，避免深色界面出现「一块块黑斑」。

### 3.7 语义状态映射表

业务状态到视觉的映射集中定义在 `web/app.js` 的 `STATUS_MAP` / `CALLBACK_MAP` / `REMOTE_STATUS_CLS`。**新增状态时必须在对应表里登记**，否则会落到灰色兜底。

**账号最近状态（`accounts.last_status`）**

| 值 | 文案 | 徽标类 | 颜色 |
| --- | --- | --- | --- |
| `never` | 未运行 | `chip-muted` | 中性灰 |
| `queued` | 任务队列中 | `chip-warning` | 橙 |
| `running` | 正在执行 | `chip-info` | 强调蓝 |
| `token_queued` | 刷新Token队列中 | `chip-warning` | 橙 |
| `token_running` | 正在刷新Token | `chip-info` | 强调蓝 |
| `success` | 已完成 | `chip-success` | 绿 |
| `failed` | 失败 | `chip-danger` | 红 |
| `cancelled` | 已停止 | `chip-muted` | 中性灰 |

**上游账号状态（`accounts.remote_status`，适配器已转中文，仅展示、不影响本地 enabled）**

| 值（中文） | 徽标类 | 颜色 |
| --- | --- | --- |
| 正常 | `chip-success` | 绿 |
| 配额耗尽 / 限流中 / 退避中 | `chip-warning` | 橙 |
| 已停用 | `chip-muted` | 中性灰 |
| 错误 | `chip-danger` | 红 |
| （空，未同步/上游未返回） | `chip-muted`，文案「—」 | 中性灰 |

> 由 `app.js` 的 `REMOTE_STATUS_CLS` + `remoteStatusChip()` 渲染；映射表登记在 §3.7。

**任务状态（`tasks.status`）**

| 值 | 文案 | 徽标类 | 颜色 |
| --- | --- | --- | --- |
| `pending` | 排队中 | `chip-warning` | 橙 |
| `queued` | 任务队列中 / 刷新Token队列中* | `chip-warning` | 橙 |
| `running` | 正在执行 | `chip-info` | 强调蓝 |
| `success` | 已完成 | `chip-success` | 绿 |
| `failed` | 失败 | `chip-danger` | 红 |
| `callback_failed` | 回调失败 | `chip-danger` | 红 |
| `cancelled` | 已停止 | `chip-muted` | 中性灰 |

> `operation=token_refresh` 的 `queued` / `running` 由 `taskStatusChip()` 显示为「刷新Token队列中」/「正在刷新Token」；其他任务显示任务执行语义。账号侧四种运行态统一禁用重复操作按钮。

**回调状态（`tasks.callback_status`）**

| 值 | 文案 | 徽标类 | 颜色 |
| --- | --- | --- | --- |
| `none` | 未配置 | `chip-muted` | 中性灰 |
| `ok` | 回调成功 | `chip-success` | 绿 |
| `failed` | 回调失败 | `chip-danger` | 红 |
| `skipped` | 已跳过 | `chip-warning` | 橙 |

> 注意：`callback_failed` 归入「失败」统计，`pending` / `queued` / `running` / `token_queued` / `token_running` 归入「进行中」统计 —— 见 `renderTaskMetrics()`。

---

## 4. 字体与字阶

### 4.1 字体栈

```css
--fa-font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display",
  "PingFang SC", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif;
--fa-font-text:    -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
  "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif;
--fa-font-mono:    ui-monospace, SFMono-Regular, "SF Mono", "JetBrains Mono",
  Menlo, Consolas, monospace;
```

- **display** 用于页面标题、指标数字、对话框标题、品牌名。
- **text** 用于正文、表格、表单。
- **mono** 用于任务编号、指纹摘要、JSON 代码块、Header JSON 输入框。

> 不引入 Web Font。中文回退到苹方 / 思源黑体 / 微软雅黑，保证首屏不闪字。

### 4.2 字阶

| Token | 值 | 用途 |
| --- | --- | --- |
| `--fa-fs-display` | 26px | 页面标题、指标数字 |
| `--fa-fs-brand` | 22px | 登录页品牌标题 |
| `--fa-fs-dialog` | 18px | 对话框标题 |
| `--fa-fs-h2` | 17px | 区块标题、面板标题 |
| `--fa-fs-card` | 15px | 卡片标题 |
| `--fa-fs-body` | 14px | 正文、输入值 |
| `--fa-fs-table` | 13px | 表格单元格、按钮文字 |
| `--fa-fs-label` | 12px | 字段标签、行内说明、表头 |
| `--fa-fs-micro` | 11px | 徽标、元信息、步骤序号 |

### 4.3 字重

只有三档：`--fa-fw-regular` (400) / `--fa-fw-medium` (500) / `--fa-fw-semibold` (600)。

- 400：正文、表格内容、导航未选中项。
- 500：按钮、徽标、行内动作、分段控件。
- 600：所有标题、指标数字、导航选中项。

> **不要使用 700 及以上。** 中文在 700 字重下容易糊，Apple 体系本身也不使用。

### 4.4 字距

大字号必须收紧字距，否则中文标题会显得松散：

| 场景 | 字距 |
| --- | --- |
| 页面标题（26px） | `-0.6px` |
| 指标数字（26px） | `-0.6px` |
| 区块 / 面板标题（17px） | `-0.374px` |
| 卡片标题（15px） | `-0.3px` |
| 对话框标题（18px） | `-0.3px` |
| 正文 / 表格 | 不设置 |

数字一律加 `font-variant-numeric: tabular-nums`（`style.css` 的 `.tabular` 或组件内置），保证指标条与表格里的数字纵向对齐。

---

## 5. 间距 / 圆角 / 尺寸

### 5.1 间距（4 的倍数）

| Token | 值 | 典型场景 |
| --- | --- | --- |
| `--fa-space-1` | 4px | 图标与文字、标题与副标题 |
| `--fa-space-2` | 8px | 徽标组、按钮组 |
| `--fa-space-3` | 12px | 表单字段之间、卡片内小节 |
| `--fa-space-4` | 16px | 指标块内边距、卡片内边距基准 |
| `--fa-space-5` | 24px | 对话框内边距、页面区块间距 |
| `--fa-space-6` | 32px | 大区块分隔 |
| `--fa-space-7` | 48px | 空状态留白 |

> **迁移状态（进行中）**：组件库尚有约 90 处 `padding` / `gap` / `margin` 使用裸像素值。
> **新代码必须引用变量**；存量在改动对应区块时顺带迁移。运行 `node scripts/design-lint.mjs` 查看当前进度。

### 5.2 圆角

| Token | 值 | 用途 |
| --- | --- | --- |
| `--fa-radius-xs` | 3px | 行内文字动作的焦点环等贴边元素 |
| `--fa-radius-sm` | 8px | 导航项 |
| `--fa-radius-md` | 11px | 输入框、下拉框、深色瓦片、代码块 |
| `--fa-radius-lg` | 18px | 卡片、对话框、指标条 |
| `--fa-radius-pill` | 999px | 主/次按钮、徽标、分段控件 |

> 规则：**控件越高越接近药丸，容器越大圆角越明显。** 不要把 `radius-lg` 用在按钮上，也不要把 `999px` 用在卡片上。

### 5.3 尺寸

| Token | 值 | 说明 |
| --- | --- | --- |
| `--fa-rail-width` | 240px | 左侧导航宽度（≤960px 时收为 68px） |
| `--fa-control-height` | 38px | 按钮、输入框、下拉框统一高度 |
| `--fa-toast-z` | 200 | Toast 层级 |

> 对话框使用原生 `<dialog>.showModal()`，处于浏览器 top layer，**无需设置 `z-index`**，因此不提供对话框层级变量。

---

## 6. 层级（阴影规则）

| Token | 值 | 用途 |
| --- | --- | --- |
| `--fa-shadow-modal` | `0 24px 60px rgba(0,0,0,.18)`（暗色 `.55`） | 仅对话框 |
| `--fa-shadow-toast` | `0 12px 32px rgba(0,0,0,.28)`（暗色 `.6`） | 仅 Toast |
| `--fa-overlay` | `rgba(0,0,0,.4)`（暗色 `.62`） | 对话框遮罩 |

**除对话框和 Toast 之外，任何元素都不应使用 `box-shadow`。** 唯一的例外是卡片选中态：

```css
.group-card.is-selected { border-color: var(--fa-accent); box-shadow: 0 0 0 1px var(--fa-accent); }
```

这里用 `box-shadow` 是为了在不改变布局尺寸的前提下加粗描边（`border-width` 变化会导致 1px 抖动）。

---

## 7. 组件规范

所有组件类名定义在 `web/style.css`，本章只列关键规格。

### 7.1 按钮 `.btn`

基础：`height: 38px`、`padding: 0 16px`、`border-radius: 999px`、`font-size: 13px`、`font-weight: 500`、`gap: 6px`。

| 类名 | 外观 | 用途 |
| --- | --- | --- |
| `.btn-primary` | 蓝底白字 | 页面唯一主操作 |
| `.btn-secondary` | 白底 + 描边 + 蓝字 | 次级操作（刷新、保存 Key） |
| `.btn-secondary.is-danger` | 白底 + 描边 + 红字 | 卡片 / 面板内的破坏性操作（删除）。**与 `.btn-secondary` 完全同形态**，只换语义色 |
| `.btn-text` | 无底无框，蓝字 | 第三级操作（取消、收起、清空） |
| `.btn-danger-solid` | 红底白字 | **仅**二次确认框的确认动作 |
| `.btn-ghost` | 白底 + 描边 + 主文字色 | 中性操作 |
| `.btn-rail` | 透明底 + 深色描边 | 仅用于左侧导航内部 |

尺寸修饰：`.btn-sm`（高 32px / 13px 内边距 / 12px 字）、`.btn-block`（占满宽度）、`.btn-icon`（正方形 38px）。

> **同一行内的按钮必须同形态。** `.btn-text` 的横向内边距是 6px，与 `.btn-sm` 的 13px 并排会一紧一松、有无边框也参差 —— 所以：表格操作列用 `.link-btn`（§7.2），**卡片 / 面板操作区一律用 `.btn-sm` 描边形态**，破坏性操作加 `.is-danger`，不要降级成文字按钮。
>
> 原「无底无框红字」按钮变体（btn-danger，2026-09-21 已移除）的唯一用途是卡片内删除；改为 `.btn-secondary.is-danger` 后它便无引用，留着只会制造「什么时候该用它」的歧义。

**按下态全站统一为 `transform: scale(0.95)`。** 这是唯一的手感约定，任何新按钮都必须继承 `.btn` 才能获得。

### 7.2 行内文字动作 `.link-btn`

表格操作列、卡片次级入口专用。**比 `.btn` 更轻**：无高度、无内边距、无边框，只有色值与字重。

```html
<span class="cell-actions">
  <button class="link-btn" type="button">执行</button>
  <button class="link-btn" type="button">编辑</button>
  <button class="link-btn is-danger" type="button">删除</button>
</span>
```

> 为什么不用 `.btn`：`.btn` 的最小高度是 38px，放进表格会把行高撑到 60px，破坏表格的紧凑节奏。

### 7.3 徽标 `.chip`

固定 `height: 22px`、`padding: 0 9px`、`border-radius: 999px`、`font-size: 11px`、`font-weight: 500`。

变体：`.chip-plain` / `.chip-info` / `.chip-success` / `.chip-danger` / `.chip-warning` / `.chip-muted`。另有风险圆点 `.fp-badge`（纯色 15px 圆点，绿=低 / 橙黄=中 / 红=高，纯色取 `--fa-*-solid`，等级与分数放 `title` tooltip 展示，不写入圆内）。

### 7.4 指纹检测圆形徽标 `.fp-badge`

40px 正圆（`border-radius: 50%`），soft 底色 + 对应主色文字，圆内居中展示「等级/分数」（如 `中/51`）。用于账号表「检测结果」列与分组卡的模板检测结果。

| 变体 | 底色 / 文字 | 语义 |
| --- | --- | --- |
| `.fp-badge-success` | `--fa-success-soft` / `--fa-success` | 低（0–30） |
| `.fp-badge-warning` | `--fa-warning-soft` / `--fa-warning` | 中（31–60） |
| `.fp-badge-danger` | `--fa-danger-soft` / `--fa-danger` | 高（61–100） |

等级由 `app.js` 的 `fpLevel()` 从 `fp_check_result` 文案（`高/中等/极低风险`）提取；「检测中 / 失败 / 未检测」仍用 `.chip` 表达，不进圆形。

带状态点时在内部包一个 `.chip-dot`（6px 圆点，取 `currentColor`）：

```html
<span class="chip chip-info"><span class="chip-dot"></span>运行中 3</span>
```

### 7.5 卡片与面板 `.card` / `.panel`

- `.card`：`background: var(--fa-canvas)` + `1px var(--fa-hairline)` 描边 + `radius-lg`，**无阴影**。
- `.panel`：在 `.card` 基础上加 `overflow: hidden`，用于「带表头的表格容器」。
- `.panel-head`：`padding: 16px 20px`，标题 `flex: 1` 并单行省略，右侧依次放计数徽标和操作按钮。

### 7.6 指标条 `.metrics`

页面顶部的概览数字条。`flex` 布局、`padding: 6px 0`、外层与卡片同样式。

- `.metric`：`flex: 1`，纵向排列，`padding: 14px 22px`。
- `.metric-value`：26px / 600 / tabular-nums。
- `.metric-label`：12px / `--fa-text-2`。
- `.metric-divider`：1px 竖线，`align-self: stretch`。

**指标数字必须真实可算。** 任务页的指标固定基于「最近 100 条全量任务」，不随筛选变化 —— 否则「总任务」会在切换筛选时跳动，误导用户。

**只在数字本身构成决策依据时才用。** 当前只有任务页使用（总任务 / 成功 / 失败 / 进行中）。**分组页不设指标条**（2026-09-21 移除）：那里的「分组数」由 `.section-head` 的 `#group-count` 徽标给出，「账号数」在账号面板头部，「进行中」在任务页 —— 三个数字都已有归宿，再铺一条概述条只会把页面首个视觉焦点让给不承载任何操作的装饰性数字，并把 `.section-head`（真正的操作起点）挤到第二屏。

### 7.7 表格 `.tbl`

| 元素 | 规格 |
| --- | --- |
| 表头 `th` | `padding: 10px 20px`、底色 `--fa-pearl`、12px、400 字重、`--fa-text-3` |
| 单元格 `td` | `padding: 11px 20px`、`border-top: 1px var(--fa-divider)`、垂直居中 |
| 行悬停 | 底色 `--fa-pearl` |
| 空状态 | 单元格内放 `.empty-state`，`colspan` 覆盖全部列 |

**列宽**：**表格用 auto layout，列宽由内容决定，不写固定宽度**（此前文档里列出的 `col-account` / `col-sm` / `col-md` / `tbl-wide` 四个固定宽度类从未在 `style.css` 实现，2026-09-21 清理）。仅两个例外：

- `.col-actions` / `.col-actions-sm` —— 置 `width: 1%`，把操作列压缩到内容宽度，避免把前面的信息列挤窄。
- `.col-select` / `.col-account` —— 账号表固定左列。勾选列始终贴左，账号列跟随其后固定，横向滚动时选择入口和身份信息不丢失。
- 长文本列靠 `.cell-stack { max-width: 260px }` + 文本省略号控制，而不是给 `th` 定宽。

**单元格内容必须用 `<span>` 包裹。** 因为 `.tbl` 的结构约定是 `table > tr > td`，直接给 `td` 挂 `display: flex` 会破坏 `vertical-align: middle`。可用的单元格类：

- `.cell-stack` —— 两行堆叠（主信息 + 副信息），配合 `.cell-sub` 用 11px 灰色显示备注 / 账号名。
- `.cell-mono` —— 等宽字体（任务编号、指纹摘要）。
- `.cell-muted` —— 次级信息（时间戳、浏览器模式）。
- `.cell-actions` —— 行内动作容器（12px，间距 12px）。

### 7.8 分段控件 `.segmented`

同一组互斥选项的切换控件，用于「任务状态筛选」与「全局浏览器模式」。

- 容器：`padding: 3px`、底色 `--fa-segment-bg`、`border-radius: 999px`、`align-self: flex-start`。
- 选项 `.segmented-item`：高 28px、`padding: 0 16px`、12px / 500。
- 选中态 `.is-active`：底色切换到 `--fa-canvas`，文字转 `--fa-ink`。

> 视觉上模拟 iOS 分段控件：底槽 + 浮起的白色滑块。**不要给选中项加边框或阴影。**

### 7.9 表单

- `.field`：纵向，`gap: 6px`。`.field-label` 12px / `--fa-text-2`。
- `.field-row`：`grid` + `auto-fit minmax(150px, 1fr)` + `gap: 12px`，让字段在窄屏自动折行。
- `.input` / `.select` / `.textarea`：高 38px、`radius-md`、13px、描边 `--fa-hairline`。
- **聚焦态**：描边转 `--fa-accent-focus`，并叠加 `0 0 0 3px` 的 16% 透明度光环。
- `.textarea`：`font-family: var(--fa-font-mono)`，用于 Header JSON 输入，可纵向拉伸。
- `.fieldset`：分组容器，`padding: 16px` + 描边 + `radius-md`；头部用 `.fieldset-title` + `.fieldset-hint`（自动推到右侧）。
- `.form-section`：表单内的大区块，区块之间用 `border-top: 1px var(--fa-divider)` 分隔，标题用 `.form-section-title`。

**校验交给浏览器**：带 `required` 的字段通过原生校验拦截提交（监听 `<form>` 的 `submit` 而不是按钮的 `click`），不要自己写一套校验气泡。业务规则（如「密码不能为空」）用 `toast()` 提示。

### 7.10 对话框 `dialog`

- 默认宽度 `min(620px, calc(100vw - 32px))`；详情类加 `.wide` 变宽到 `min(820px, ...)`。
- 结构固定三段：`.dlg-head`（22px 24px，标题 + 副标题）/ `.dlg-body`（22px 24px，上下都有分隔线，`max-height: min(60vh, 520px)` 超出滚动）/ `.dlg-foot`（18px 24px，右对齐）。
- 关闭按钮统一加 `data-close` 属性，由 `app.js` 统一绑定 `closest("dialog").close()`。

详情类内容专用类：

| 类名 | 用途 |
| --- | --- |
| `.detail-grid` | 概览键值对网格（`auto-fit minmax(170px, 1fr)`） |
| `.detail-item` / `.detail-key` / `.detail-val` | 单个键值对 |
| `.detail-block` / `.detail-block-title` | 带标题的内容块 |
| `.code-block` | 等宽代码 / JSON 块，`max-height: 240px` 内滚动 |
| `.step-list` / `.step-item` / `.step-index` / `.step-text` / `.step-time` | 执行步骤时间线；失败步骤加 `.is-error` 使文字转红 |
| `.hist-list` / `.hist-row` | 可点击的历史记录列表 |

### 7.11 Toast `.toast`

- 位置：底部居中（`bottom: 28px`），药丸形状，深色底（`--fa-rail`）+ 浅色字。
- 错误态加 `.is-error`，底色转 `--fa-danger`。
- 显示 2600ms 后自动消失。层级 `--fa-toast-z` 保证它在对话框之上。

```js
toast("分组已保存");            // 成功
toast("密码不能为空", true);    // 错误
```

### 7.12 左侧导航 `.rail`

- 固定 240px 宽、100vh 高、墨黑底（`--fa-rail`），`position: sticky`。
- 结构：`.rail-brand`（盾形 SVG + 品牌名 + 副标题）→ `.rail-nav`（`.rail-item[data-tab]`）→ `.rail-spacer` → `.rail-foot`。
- `.rail-item` 选中态 `.is-active`：底色 `--fa-rail-hover`，文字转 `--fa-on-rail`，字重升到 600。
- `.rail-foot` 内是引擎状态卡（`.engine-card`）+ 退出登录 + 主题切换。

**引擎状态卡**的圆点 `.engine-dot` 用颜色表达健康度：正常为 `--fa-success`，降级（CloakBrowser 不可用）加 `.is-off` 转 `--fa-warning`，同时徽标文字追加「· 降级」。

### 7.13 搜索框 `.search-box` / `.search-input`

- 区块标题行内的行内检索控件：36px 高、药丸描边输入框，左侧 14px 放大镜 SVG 绝对定位（`--fa-text-3`）。
- 布局：`.section-head` 内通过 `margin-left: auto` 贴右；≤960px 时宽度转 100%、标题行换行。
- 过滤逻辑纯前端（对已拉取列表按名称 `includes` 过滤），不调接口。

### 7.14 图标按钮 `.icon-btn`

- 表格操作列的纯图标动作按钮：30×30 圆角药丸，透明底，`--fa-text-2` 着色的 15px 内联 SVG。
- 悬停转 `--fa-accent-soft` 底 + `--fa-accent` 图标；危险动作 `.is-danger` 用 `--fa-danger` 系。
- 必须带 `title` + `aria-label`（图标规范 §9）；测试进行中置 `disabled`。

### 7.15 设置卡 `.setting-card`

系统设置页的基本单元。**卡内固定三段结构**，缺任何一段都会退回到"六张框子各自为政"的旧问题：

```html
<div class="setting-card">
  <div class="setting-head">  <!-- 标题区：.setting-title + .setting-desc，下缘一条 --fa-divider 收口 -->
  <div class="setting-body">  <!-- 内容区：flex:1，负责把操作区压到卡片底部 -->
  <div class="setting-foot">  <!-- 操作区：右对齐，只放与这张卡相关的按钮 -->
</div>
```

- **页面骨架**：`.settings-group`（语义分组）> `.settings-group-head`（`.section-title` + `.settings-group-hint`）+ `.settings-grid`（两列 `repeat(2, minmax(0, 1fr))`，`align-items: stretch`）。
- **同排卡片等高、操作按钮贴底**：由 `.setting-body { flex: 1 }` + `.setting-foot { margin-top: var(--fa-space-4) }` 保证，**不要**给 `.setting-card` 写死高度。
- **分组按语义划分，同排按体量配对**：内容体量悬殊的两张卡（"一个输入框" 配 "五行状态 + 输入框"）放同一行，短卡会留下大片空白。当前三组为 **任务环境 / 指纹环境 / 数据与安全**。
- **只读状态用 `.status-list`**：两列键值规格块（列定义 `max-content minmax(0, 1fr)` ×2），键 12px `--fa-text-3`、值 13px `--fa-ink` 带 `tabular-nums`；`align-items: baseline` 保证同基线对齐；≤960px 收成单列键值。
- **单值字段用 `.field-narrow`**（≤180px）：数值型输入占满整行会与说明文字比例失衡。
- 卡片内的动作按钮**必须**收在 `.setting-foot` 内 —— `scripts/layout-check.py` 会断言这一点。

### 7.16 分组页标题行与分组卡 `.group-card`

分组页的主体是卡片网格。**页面唯一的操作（新建分组）挂在标题行上** —— 不占顶栏，也不做网格末尾的磁贴（理由见 §8.2）。

**标题行 `.section-head` = 标题 + 计数徽标 + 主操作**，三者同排垂直居中：

```html
<div class="section-head">
  <h2 class="section-title">分组</h2>
  <span class="chip chip-plain" id="group-count">2 个分组</span>
  <button id="btn-new-group" class="btn btn-secondary btn-sm">…新建分组</button>
  <span class="section-hint">…</span>   <!-- margin-left:auto，自动被推到最右 -->
</div>
```

- 操作按钮**紧跟计数徽标**：标题 → 数量 → 动作，读起来是一句话。`scripts/layout-check.py` 断言按钮 `left > chip.right`、两者 `centerY` 差 ≤ 2px，且按钮确在 `.section-head` 内。
- 按钮用 `.btn .btn-secondary .btn-sm`（32px 高），与页内其他次级按钮同规格。图标为内联 SVG 加号，`stroke="currentColor"`。

**`.group-grid`**：`repeat(auto-fill, minmax(320px, 1fr))`，间距 16px，`align-items: start`（同行的收起卡片不被展开卡片拉伸）。实测 1600px 下 3 列、900px 下 2 列。

**`.group-card` 头部**：`.group-avatar`（40px 字母块）+ `.group-name-row`（风险圆点 + 名称）+ `.group-sub`（类型 · 登录方式 · 账号数）+ 运行中徽标 + `.group-toggle`。收起态高约 75px（`padding --fa-space-4` ×2 + 头部 40px + 上下边框）。

- **风险圆点在分组名左侧**：`.group-name-row` 是 `flex + gap --fa-space-2` 的行，圆点在前、名称在后（名称 `flex:1` + `min-width:0` 以保留省略号）。
- **没有检测结果时圆点不渲染**（`groupRiskDot()` 返回空串），名称自然回到行首 —— **不要输出「未检测」占位文字**，分组名左侧是稀缺位置。`layout-check.py` 断言无圆点的卡片 `name.left == .group-head-text.left`。
- 圆点用 `.fp-badge`（15px 实心圆），配色走语义：`.fp-badge-success` 低 / `.fp-badge-warning` 中 / `.fp-badge-danger` 高 / `.fp-badge-info` 检测中 / `.fp-badge-muted` 失败。风险等级与分数只放在 `title` 里，不占版面。注意上游文案是「中等风险」而非「中风险」，`fpLevel()` 用 `/高|中|低/` 判断。
- **选中态** `.is-selected`：`border-color: --fa-accent` + `box-shadow: 0 0 0 1px --fa-accent` 模拟加粗描边 —— 属于 §6 的 ring 例外，不是层级阴影。**不换底色**。
- **展开箭头 `.group-toggle` 复用 `.icon-btn`**：自身只保留 `flex:none` / `margin-left:auto` 与 chev 图标切换，尺寸、底色、悬停、按下态全部继承 `.icon-btn`（30×30 药丸）。**不要为它另写一套几何** —— 那正是它此前与页内其他图标按钮不一致的原因。
- **操作区 `.group-actions` 内按钮形态必须统一**：全部 `.btn .btn-sm`，并通过 `.group-actions .btn-sm` 覆盖为紧凑规格（28px 高、`--fa-space-2` 水平内边距与间距、999px 圆角），只有语义色不同 —— 主操作 `.btn-primary`，其余 `.btn-secondary`，删除再加 `.is-danger`。**不允许把「编辑」「删除」降级成无底无框的文字按钮**：紧凑规格用于降低操作区视觉重量；标题行等普通 `.btn-sm` 仍是 32px。`layout-check.py` 断言同页所有操作按钮的 `height` / `paddingLeft` / `borderTopLeftRadius` 各自唯一。

**交互解耦：箭头是操作项的开关，卡体是账号列表的开关。** 两者是**两个独立控件**，一次点击只能触发其中一个：

| 点击目标 | 触发 | 不触发 |
| --- | --- | --- |
| 卡体任意位置（头像 / 名称 / 元信息行 / 空白） | 选中该分组 + 打开下方账号列表 | 操作项展开 |
| 右侧箭头 `.group-toggle` | 本卡操作项 `.group-actions` 展开 / 收起 | 账号列表、选中态 |

- 两个状态的载体是分开的：`is-selected`（卡体写入）、`is-open`（箭头写入）。**`selectGroup()` 里不允许出现 `is-open` 或 `expandedGroups`** —— 只要写一行，点卡体就会顺带把操作项摊开。这是本节最容易写错的地方。
- 反过来同样成立：`toggleGroupCard()` 不碰 `is-selected` 与 `#accounts-panel`。操作项已展开时点卡体，展开态**保持不变**（不会顺手收起）。
- 语义归属随之调整：`aria-expanded` + `aria-controls`（指向 `group-actions-{id}`）挂在**箭头**上，卡体挂 `aria-current`。卡体不再是「可展开」，它只是一个可选择项。
- **箭头必须可键盘聚焦**（去掉 `tabindex="-1"`）—— 它现在是操作项的唯一入口，不可聚焦等于键盘用户拿不到「一键执行」。随之需要一条事件守卫：卡体的 `keydown` 处理器在 `e.target !== el` 时立即返回，否则焦点停在箭头上按 Enter 会同时触发「展开操作项」和「打开账号列表」。
- 取舍：这个模型让「一键执行」从一次点击变成两次。换来的是一次走神不会让卡片炸开六行按钮 —— 卡片高度稳定，网格不跳。

**不要在这一页加指标条**，理由见 §7.6。

`scripts/layout-check.py` 对分组页断言：无指标条、首元素是 `.section-head`、顶栏无可见操作按钮、顶栏未塌陷、「新建分组」按钮在标题行内且紧接计数徽标并垂直居中、网格无水平溢出、首行卡片等宽且顶部对齐、浏览器按钮按引擎成对显隐（本地 7 个 / CDP 5 个）、操作区按钮高度/内边距/圆角各自一致、箭头为 30×30、风险圆点在分组名左侧且垂直居中、无圆点分组名回到行首。

同一脚本的**交互解耦**一节用真实浏览器点按并断言：初始操作项收起且卡片未选中、箭头 `aria-expanded=false` 且 `aria-controls` 指向本卡操作区且 `tabIndex=0`；点卡体 → 账号列表展开 + 卡片选中，但操作项 `display` 仍为 `none`；点箭头 → 操作项展开，而选中态与账号列表不变；操作项已展开时点卡体不会被收起；再点箭头可正常收起。

### 7.17 账号自动刷新 `.panel-title-row`

账号面板头部左侧用 `.panel-title-row` 承载分组名和自动刷新入口：`.panel-title` 保持可省略，右侧依次是 `.auto-refresh-label` 和紧凑下拉 `.select.select-sm`。默认「关闭」，可选 5 / 10 / 15 / 30 秒；仅停留在分组页且账号面板展开时轮询当前分组的账号列表。上一次列表请求完成后再排下一次定时器，避免短间隔下请求堆叠。

---

## 8. 布局与响应式

### 8.1 主体结构

```
.shell  (flex, min-height 100vh, 底色 parchment)
├─ .rail   左侧导航（240px，固定）
└─ .main   flex:1, 纵向
   ├─ .topbar   页面标题 + 副标题（flex:1）+ 按 tab 切换的 .act-set
   └─ .content  页面区块容器（gap 20px, padding 4px 28px 28px）
      └─ .page  单个页面（gap 20px）
```

### 8.2 断点

| 断点 | 变化 |
| --- | --- |
| ≤ 1180px | 表格列宽收窄（账号列 180px、操作列 210px） |
| ≤ 960px | **导航收成 68px 图标条**（隐藏品牌文字、导航文字、引擎卡文字）；顶栏 `.content` 内边距收窄；页面标题降到 22px；设置页网格与 `.status-list` 均转单列 |
| ≤ 640px | 指标条换行（`metric` 占 40% 宽并隐藏分隔线）；顶栏操作按钮占满整行 |

> `.act-set[data-for]` 的显隐由 `switchTab()` 统一控制 —— 每个页面的主操作按钮放在自己的 `.act-set` 里，切换 tab 时自动跟随。**没有主操作的页面不放 `.act-set`**（如分组页：新建分组的唯一入口挂在标题行 `.section-head`，顶栏不放重复按钮）。`.page-actions` 无子项时高度为 0，顶栏不会因此塌陷 —— `scripts/layout-check.py` 会断言这一点。

---

## 9. 图标规范

1. **必须使用 SVG 节点，禁止 emoji 或 Unicode 字符充当图标。** emoji 在不同系统上渲染差异极大（本项目已移除全部 emoji）。
2. 统一使用 `stroke="currentColor"`，让图标继承父级文字颜色，便于主题切换与状态联动。
3. 描边宽度 `1.3–1.7`，圆角端点（`stroke-linecap="round"` / `stroke-linejoin="round"`）。
4. 尺寸：导航 16px、按钮内 14px、品牌标识 28px（导航）/ 44px（登录页）。
5. 装饰性图标加 `aria-hidden="true"`；纯图标按钮必须给 `title` 和 `aria-label`。

---

## 10. 动效

| Token | 值 |
| --- | --- |
| `--fa-ease` | `cubic-bezier(0.4, 0, 0.2, 1)` |
| `--fa-dur` | `150ms` |

- 只对 `background` / `border-color` / `color` / `opacity` / `transform` 做过渡。
- 按下反馈统一 `transform: scale(0.95)`（按钮）与 `opacity: 0.6`（行内文字动作）。
- 键盘焦点用 `:focus-visible` + 2px `--fa-accent-focus` 外描边，不影响鼠标用户。
- **不做入场动画、不做骨架屏闪烁。** 控制台追求「点完立刻有反应」。

---

## 11. 前端接入指南

### 11.1 文件职责

| 文件 | 职责 | 是否可直接改 |
| --- | --- | --- |
| `web/tokens.css` | 设计变量（颜色、字号、圆角、间距、层级、动效） | 加变量可以；改已有变量的值等于改全站，需评审 |
| `web/style.css` | 组件库（按钮、徽标、卡片、表格、表单、对话框……） | 加新组件可以；修改已有组件类需确认所有引用点 |
| `web/index.html` | 页面结构 | 自由 |
| `web/app.js` | 业务逻辑：调用 `/api/*` 并渲染 | 自由；**不得改动接口路径与载荷字段**（新增接口须同步 AGENTS.md 契约表与本文件，并登记 `design-lint.mjs` 白名单，如 `/api/meta` 注册表下发接口） |
| `scripts/design-lint.mjs` | 规范校验器：把本文档的规则变成可执行的断言 | 可扩充规则；收紧规则前需先修掉存量问题 |

页面按 `tokens.css` → `style.css` 的顺序引入，样式统一挂载在 `/static` 下。

### 11.2 新增页面骨架

```html
<section id="tab-reports" class="page hidden">
  <!-- 概览数字：可选，且只在数字本身构成决策依据时才用（见 §7.6） -->
  <div class="metrics">
    <div class="metric">
      <span class="metric-value" id="r-total">0</span>
      <span class="metric-label">总记录</span>
    </div>
  </div>

  <!-- 区块标题 + 右侧提示 -->
  <div class="section-head">
    <h2 class="section-title">上报记录</h2>
    <span class="chip chip-plain" id="r-count">0 条</span>
    <span class="section-hint">点击行查看详情</span>
  </div>

  <!-- 带表头的表格容器 -->
  <div class="card panel">
    <header class="panel-head">
      <h2 class="panel-title">明细</h2>
      <button class="btn btn-secondary btn-sm" type="button" id="btn-export">导出</button>
    </header>
    <div class="table-wrap">
      <table class="tbl" id="reports-table">
        <thead>
          <tr>
            <th>编号</th>
            <th>名称</th>
            <th>状态</th>
            <th class="col-actions-sm">操作</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</section>
```

接入步骤：

1. 在 `.rail-nav` 里加一个 `<button class="rail-item" data-tab="reports">`（图标用 16px SVG）。
2. 该页**有**主操作时，在 `.page-actions` 里加 `<div class="act-set hidden" data-for="reports">` 放该页主操作；没有主操作就不加（分组页即如此）。
3. 在 `app.js` 的 `TAB_META` 里登记 `reports: { title, sub }`。
4. 在 `switchTab()` 里按需追加 `if (tab === "reports") loadReports();`。

这样导航高亮、页面显隐、顶栏按钮、标题文案会全部自动生效。

### 11.3 禁止清单

| ✗ 不要 | ✓ 应该 |
| --- | --- |
| `color: #6e6e73` | `color: var(--fa-text-2)` |
| `border-radius: 10px` | `border-radius: var(--fa-radius-md)` |
| `font-size: 13px` | `font-size: var(--fa-fs-table)` |
| 给卡片加 `box-shadow` | 用 1px 描边 + 底色区分层级 |
| 引入第二个强调色 | 一律用 `--fa-accent` |
| 用 emoji 当图标 | 内联 SVG + `currentColor` |
| 给 `td` 直接挂 `display: flex` | 用 `.cell-stack` / `.cell-actions` 包裹 |
| 破坏性操作用 `confirm()` | `confirmDialog({ danger: true, okText: "删除…" })` |
| 在 `.btn` 上改按下反馈 | 统一 `scale(0.95)` |

### 11.4 账号 Token 刷新（2026-09-22）

账号面板的批量操作区使用既有的 `.btn-secondary.btn-sm`，账号行使用既有的 `.link-btn`，不新增组件。批量入口标题随勾选范围变化；四种运行态禁用任务执行、刷新、换指纹、指纹检测和删除按钮，批量 Token 刷新在有账号运行时禁用。新增 API 为 `/api/groups/:id/refresh-tokens` 与 `/api/accounts/:id/refresh-token`，业务约束以后端契约为准。
系统设置卡复用 `.setting-card` 三段结构，新增「Token 自动刷新」执行间隔输入；定时巡检复用同一套后端规则。

### 11.5 账号添加弹窗（2026-09-22）

添加账号复用 `.segmented` 切换「单个添加」与「批量添加」，批量输入使用既有 `.textarea`，每行格式为 `邮箱|密码|2FA密钥`（2FA 可选）。同分组重复账号由后端跳过；批量输入中的重复行直接去重，结果文案区分新增与跳过数量。浏览器模式、代理和指纹配置收进「分组默认环境」折叠区；折叠区未修改时分别提交 `inherit`、`null` 和 `{}`，由后端按分组浏览器模式、分组代理和分组指纹模板落库。账号表单不展示代理可选项，仅以徽标显示「跟随分组代理」或已有账号代理；编辑时原样保留既有 `proxy_id`，不提供账号级修改入口。

### 11.6 任务停止（2026-09-23）

账号行在任务队列中或执行中显示既有 `.link-btn`「停止」入口，二次确认后调用 `/api/accounts/:id/stop`。队列中直接移除；执行中由后端中断后续流程、关闭指纹浏览器后返回。结果复用既有账号/任务状态徽标，新增 `cancelled` 显示为「已停止」。

指纹检测复用同一操作位：检测中显示「停止检测」，账号与分组分别调用 `/api/accounts/:id/fp-check/stop` 与 `/api/groups/:id/fp-check/stop`；检测结果沿用既有徽标，「已停止」使用 muted 语义。

### 11.7 手机验证国家选择（2026-09-23）

系统设置中的「国家列表」继续来自接码平台适配器，HeroSMS 选项值保持供应商数字 ID。页面使用的「国家编码」独立调用 `/api/settings/page-countries`，由内置 ISO 国家映射生成，并以既有 `.select` 下拉展示；选项保存两位国家编码，不再手填。

---

## 12. 设计稿索引

画布设计稿（Ardot）：<https://ardot.tencent.com/file/728115104293393>

分组卡交互规范（独立画布，2026-09-21 新增）：<https://ardot.tencent.com/file/728218120871246>
—— 只讲一件事：**箭头 = 操作项开关、卡体 = 账号列表开关**。三态并列（A 默认收起 / B 点卡体 / C 点箭头），附两个点击目标图例与硬约定。**这份画布与代码同步，可作为 §7.16「交互解耦」的可视化对照。**

| 画板 | 内容 |
| --- | --- |
| 01 登录页 | 品牌盾形标识 + 账号密码 + 默认凭据提示 |
| 02 分组与账号 | 左侧导航 + 标题行（标题 / 计数徽标 / 新建分组）+ 分组卡片网格 + 账号表格。顶栏无操作按钮、无指标条。**注：此画板仍是"网格末尾瓦片"的旧版，与 §7.16 已不一致，以代码为准** |
| 03 关键区域 | 任务日志与系统设置的局部放大。⚠️ **其中的系统设置段仍是重排前的旧扁平布局**，尚未同步 §7.15 的三段结构 |
| 04 设计规范 | 色板、字阶、间距、圆角、组件总览 |
| 05 表单与弹窗 | 分组表单、账号表单（含指纹配置）、任务详情、危险确认 |

---

## 附：设计变量完整导出

需要把设计变量接入其他消费端（如代码生成、Figma 同步）时，可在设计文件中执行变量导出，得到 CSS / SCSS / W3C DTCG JSON 三种格式。`web/tokens.css` 即 CSS 格式的落地版本。

| 变量集 | 变量数 | 模式 |
| --- | --- | --- |
| FAUI | 37 | Light / Dark |

---

*本规范与 `web/tokens.css`、`web/style.css` 保持同步。修改任一组件规格时，请同时更新本文件对应章节。*

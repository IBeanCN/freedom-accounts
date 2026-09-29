# DESIGN.md — 前端规范（Vue 3 + Element Plus）

> 本文件约束 `frontend/` 的界面结构、组件选型和视觉基调。当前实现不是旧版静态
> `web/` 架构；`frontend/dist/` 由 Vite 生成，不要手工维护。

## 1. 基本原则

1. **先复用 Element Plus，再考虑自定义。** 表格、表单、按钮、标签、下拉、分页、
   对话框、抽屉、消息和确认框优先使用现有 Element Plus 组件。
2. **操作密度优先。** 这是管理控制台：标题、数量、主操作和表格状态要一眼可读，
   不做营销页、装饰性插画和无信息量的分层。
3. **状态必须可读。** 状态用「文字 + 颜色」表达，只用颜色表意不合格。
4. **层级轻量。** 页面和卡片主要靠 `1px` 描边、背景色和间距区分；卡片不用大阴影。
   选中态可用 `box-shadow: 0 0 0 1px` 模拟加粗描边。
5. **单品牌色。** 自定义样式统一使用 `--fa-brand`；语义状态使用 Element Plus 的
   `--el-color-success|warning|danger|info` 或组件语义类型。
6. **可访问。** 纯图标按钮必须有 `title` 和 `aria-label`；长文本用 tooltip 或省略
   展示，不能撑破表格。

## 2. 架构与文件职责

| 位置 | 职责 |
| --- | --- |
| `frontend/src/main.js` | 创建应用，集中注册 Element Plus 组件和深色样式 |
| `frontend/src/App.vue` | 应用外壳、中文 locale、顶栏标题与副标题 |
| `frontend/src/router/index.js` | hash 路由、页面元信息、登录守卫 |
| `frontend/src/components/SideNav.vue` | 左侧导航、主题切换、退出登录 |
| `frontend/src/views/` | 路由页面；组织页面视图 |
| `frontend/src/dialogs/` | 表单、详情、批量操作弹窗；归属于对应业务页 |
| `frontend/src/components/` | 跨页面复用的业务控件 |
| `frontend/src/stores/app.js` | reactive 共享状态和 `/api/*` 编排 |
| `frontend/src/api/client.js` | fetch 封装、401 广播和统一错误对象 |
| `frontend/src/utils/status.js` | 任务、回调、上游、指纹状态映射 |
| `frontend/src/utils/format.js` | 时间、模式、JSON、URL 和账号输入清理 |
| `frontend/src/utils/fingerprint.js` | 指纹默认值、字段名和差异计算 |
| `frontend/src/styles/main.css` | 全局布局、设计 token 和少量共享类 |
| `frontend/src/**/*.vue` 的 `<style scoped>` | 只属于该组件的局部样式 |

新增页面流程：

1. 在 `router/index.js` 添加懒加载路由和 `meta.title` / `meta.sub`。
2. 在 `components/SideNav.vue` 的 `items` 里登记导航。
3. 在 `views/` 建页面；跨页面共享请求放 `stores/app.js`，单页请求可直接调用 `api`。
4. 业务状态文案加入 `utils/status.js`，不要在模板里重复硬编码状态映射。

`frontend/dist/` 只由 `npm run build` 生成；生产挂载路径仍是 `/static/`。

## 3. 设计 token

全局 token 定义在 `frontend/src/styles/main.css`：

| 变量 | 用途 |
| --- | --- |
| `--fa-page` | 应用页面底色 |
| `--fa-surface` | 侧栏、顶栏、卡片、表格等表面 |
| `--fa-ink` | 主文字 |
| `--fa-muted` | 次级说明、表内辅助文字 |
| `--fa-line` | 自定义卡片、按钮、分隔线描边 |
| `--fa-brand` / `--fa-brand-soft` | 品牌强调色与浅底 |

深色模式通过 `html.dark` 切换。`main.js` 已引入 Element Plus dark CSS vars，组件内
优先继承 Element Plus 变量；新增自定义颜色必须接入 token，不要散落硬编码值。

基线：

- 正文 `14px`，辅助说明 `12px`，表格内容跟随 Element Plus 默认。
- 页面外壳 padding 为 `24px`；卡片、面板、表单间距以 `10–16px` 为主。
- 常用圆角：控件 `6px`，卡片 `8px`；表格行内小按钮可为圆形。
- 长文本用 `ellipsis-cell` + `el-tooltip`；ID、种子、日志使用 `mono`。

## 4. 组件约定

### 布局

- 页面头部用 `.panel-head`：左侧 `.panel-title-row` 放标题、计数和说明，右侧放操作。
- 主列表用 `el-card shadow="never"` 包 `el-table`。
- 指标区用现有 `.metrics` / `.metric`；设置页网格用 `.settings-grid`。
- 表格单元格用 `.cell-stack` 做主/副信息，用 `.ellipsis-cell` 防止撑宽。

### 按钮

- 每个面板只保留一个 `type="primary"` 主操作；其余默认按钮。
- 表格行操作用 `link size="small"`；高频危险操作用 `type="danger"` 或
  `type="danger" plain`。
- 分组卡等紧凑区域可用 `text size="small"`；纯图标按钮使用 `@element-plus/icons-vue`。
- 加载中用 `loading`；不可用原因能用按钮状态表达时不要额外弹提示。

### 表格

- `el-table` 必须给中文 `empty-text`。
- 固定列只用于选择、账号名和行操作，避免小屏过度横向锁定。
- 可排序字段提供稳定的 `sort-method`；数字和枚举不要直接依赖默认字符串排序。
- 状态列渲染 `el-tag`；同一行可补充小号 `size="small" effect="plain"` 标签。

### 表单与弹窗

- 表单弹窗用 `el-dialog`；长流程详情可用 `el-drawer`。
- `destroy-on-close` 适合包含临时状态或异步回填的表单。
- 保存、删除、覆盖指纹等操作失败时用 `ElMessage.error(error.message)`。
- 原生 `confirm()` / `alert()` 禁用；删除用 `ElMessageBox.confirm`，确认按钮加
  `el-button--danger`；普通覆盖用 `type: 'warning'`。

### 状态

- 任务状态映射在 `STATUS_MAP`，回调映射在 `CALLBACK_MAP`，渲染入口分别是
  `statusMeta()`、`callbackMeta()`、`taskStatusMeta()`。
- 上游状态由后端适配器/API 统一转成中文；前端不重建完整上游状态列，当前账号表
  只把后端返回的 `错误` 值提升为「上游错误」标签。
- 指纹检测结果用 `fpBadgeMeta()`；不要在页面内重新判断风险等级。

## 5. 数据与请求

1. 页面组件不直接裸写 `fetch`；统一走 `frontend/src/api/client.js`。
2. 跨视图共享的列表、设置和操作编排放 `stores/app.js`；局部弹窗状态留在组件内。
3. 不得随意改动冻结的 `/api/*` 请求和响应字段；扩展时先更新 `AGENTS.md` 契约表。
4. 后端约定为数组的字段（如 `reset_credits`）直接确认 `Array.isArray`；遗留 JSON
   字符串字段在渲染前用 `safeJson()` 归一。
5. 后台任务完成后按业务节奏刷新对应列表；刷新失败要有用户可见提示。

## 6. 响应式

- 当前断点：`1100px` 收缩卡片网格，`820px` 将侧栏改为顶部区块，网格改为单列。
- 表格列要保留最小可读宽度；长标题、ID 和代理地址必须截断并提供 tooltip。
- 明暗模式都要检查；主题切换在左侧导航底部，不引入页面级重复入口。

## 7. 验证

没有独立的 design lint。前端最低验证：

```bash
cd frontend
npm ci        # 依赖变化或干净环境
npm run build # 模板、组件导入和生产构建检查
```

涉及交互或布局时，用 `npm run dev` 配合后端实际检查关键页面；后端改动按
`AGENTS.md` 的后端验证要求执行。文档本身修改后至少确认不再引用不存在的旧文件。

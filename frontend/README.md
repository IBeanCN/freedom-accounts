# freedom-accounts Frontend

Vue 3 + Element Plus + Vue Router + Vite。页面按路由拆分，共享状态、API 封装和业务工具不放在页面组件里。

## Commands

```bash
npm ci
npm run dev       # http://127.0.0.1:5173，/api 代理到 127.0.0.1:8000
npm run build     # 输出 dist/，FastAPI 从该目录服务
npm run preview
```

## Structure

- `src/views/` — login, groups/accounts, tasks, proxies, settings pages.
- `src/dialogs/` — form and detail dialogs owned by their related pages.
- `src/components/` — shared controls.
- `src/stores/app.js` — reactive application state and API orchestration.
- `src/api/client.js` — fetch wrapper and 401 session handling.
- `src/utils/` — formatting, status mapping, and fingerprint helpers.

The production base is `/static/`; hash routing keeps direct refresh compatible with the FastAPI entrypoint.

## Jev DOM Selection Helper

`scripts/jev-dom-select.mjs` is a local browser-automation helper. TypeSafe Jev
selects one candidate from visible DOM metadata; application code enforces
confidence thresholds and performs the actual coordinate-based mouse click.
Set `TYPESAFE_API_KEY` in the local environment. Run it through `ego-browser`:

```js
const { jevClick } = await import('./frontend/scripts/jev-dom-select.mjs')
await jevClick(page, '打开添加账号表单', { threshold: 0.8 })
```

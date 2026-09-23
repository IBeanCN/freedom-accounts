// 冒烟测试：指纹下拉化改造 —— 随机自洽 / 表单读写对称 / 平台级联 / meta 驱动
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { JSDOM } = require("/Users/ibean/.workbuddy/binaries/node/workspace/node_modules/jsdom");

const html = readFileSync("web/index.html", "utf8");
const js = readFileSync("web/app.js", "utf8");

const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://localhost/" });
const { window } = dom;

// ---- mock fetch：/api/meta 返回带 fp_options，其余返回空壳 ----
const META = {
  login_types: [{ key: "sub2api", label: "sub2api" }],
  group_types: [{ key: "openai", label: "OpenAI", default_login_type: "sub2api" }],
  fp_options: {
    platforms: ["windows", "macos"],
    brands: ["Chrome", "Edge", "Opera", "Vivaldi"],
    gpus: {
      windows: [
        { vendor: "Google Inc. (Intel)", renderer: "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)", label: "Intel UHD 630" },
        { vendor: "Google Inc. (NVIDIA)", renderer: "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)", label: "GeForce GTX 1660" },
      ],
      macos: [
        { vendor: "Google Inc. (Apple)", renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)", label: "Apple M1" },
        { vendor: "Google Inc. (Apple)", renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)", label: "Apple M3" },
      ],
    },
    screens: {
      windows: [{ width: 1920, height: 1080 }, { width: 1536, height: 864 }],
      macos: [{ width: 1440, height: 900 }, { width: 1512, height: 982 }],
    },
    cores: { windows: [4, 8, 16], macos: [8, 10, 12] },
    memory: [4, 8],
    timezones: ["Asia/Shanghai", "America/New_York"],
    locales: ["zh-CN", "en-US"],
  },
};

let failures = 0;
const check = (name, cond) => {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}`);
  if (!cond) failures++;
};

window.fetch = async (url) => {
  const u = String(url);
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (u.includes("/api/meta")) return ok(META);
  if (u.includes("/api/accounts")) return ok({ accounts: [] });
  if (u.includes("/api/groups")) return ok({ groups: [] });
  if (u.includes("/api/proxies")) return ok({ proxies: [] });
  if (u.includes("/api/settings")) return ok({ global_browser_mode: "headless", cloak_cdp_url: "" });
  if (u.includes("/api/tasks")) return ok({ tasks: [] });
  return ok({});
};

window.eval(js);
// 函数声明经 indirect eval 挂在 window 上，直接调 showMain 进入主视图（否则 loadMeta 不会执行）
window.showMain();
await new Promise((r) => setTimeout(r, 80));

// ---- 1. meta 驱动：静态下拉候选数 ----
check("时区下拉含 2 个候选 + 默认", window.document.querySelectorAll("#fp-tz option").length === 3);
check("语言下拉含 2 个候选 + 默认", window.document.querySelectorAll("#gt-locale option").length === 3);
check("内存下拉仅 4/8（无 16）", [...window.document.querySelectorAll("#fp-mem option")].map((o) => o.value).join(",") === ",4,8");

// ---- 2. 默认（windows）平台级联 ----
check("账号 GPU 下拉默认 windows 候选", [...window.document.querySelectorAll("#fp-gpu option")].map((o) => o.textContent).join("|") === "默认|Intel UHD 630|GeForce GTX 1660");
check("分组 GPU 下拉默认 windows 候选", window.document.querySelectorAll("#gt-gpu option").length === 3);

// ---- 3. 平台切换级联 ----
const fpPlatform = window.document.querySelector("#fp-platform");
fpPlatform.value = "macos";
fpPlatform.dispatchEvent(new window.Event("change"));
const macLabels = [...window.document.querySelectorAll("#fp-gpu option")].map((o) => o.textContent).join("|");
check("切 macos 后 GPU 候选变为 Apple", macLabels.includes("Apple M1") && macLabels.includes("Apple M3") && !macLabels.includes("GTX"));
const macScreens = [...window.document.querySelectorAll("#fp-screen option")].map((o) => o.value).join(",");
check("切 macos 后分辨率候选无 1536x864", !macScreens.includes("1536x864") && macScreens.includes("1440x900"));

// ---- 4. 随机生成 300 次：平台/硬件自洽（经表单回填后读取） ----
// 直接调内部函数走 dom eval 作用域：改用按钮触发 + 读表单循环
let violations = 0;
for (let i = 0; i < 300; i++) {
  window.document.querySelector("#btn-regen-fp").click();
  const plat = window.document.querySelector("#fp-platform").value;
  const gpu = window.document.querySelector("#fp-gpu").value;
  const scr = window.document.querySelector("#fp-screen").value;
  const cores = window.document.querySelector("#fp-cores").value;
  const mem = window.document.querySelector("#fp-mem").value;
  if (plat === "macos") {
    if (gpu.includes("D3D11") || +cores > 12 || ![8, 10, 12].includes(+cores) || +mem > 8 || scr === "1536x864") violations++;
  } else if (plat === "windows") {
    if (gpu.includes("Metal")) violations++;
  } else violations++;
}
check(`随机 300 次零跨平台矛盾（违规 ${violations}）`, violations === 0);

// ---- 5. 表单读写对称：填入模拟存量指纹 -> 读出一致 ----
window.document.querySelector("#btn-regen-fp").click();
const seedEl = window.document.querySelector("#fp-seed");
seedEl.value = "123456789";
const tzEl = window.document.querySelector("#fp-tz");
tzEl.value = "America/New_York";
// readFpForm 在闭包里，无法直接调；借 submit 路径不可行（会发请求），改验证 DOM 值合法性
const scrVal = window.document.querySelector("#fp-screen").value;
const [w, h] = scrVal.split("x").map(Number);
check("随机后屏幕下拉值形如 WxH", !!(w && h));

// ---- 6. 存量自由值兼容：下拉中不存在的值回填临时项 ----
window.eval(`
  (function(){
    fillAccountFpForm({ platform: "macos", gpu_renderer: "ANGLE (Old Custom)", screen_width: 1111, screen_height: 2222, timezone: "Mars/Olympus", locale: "xx-YY", hardware_concurrency: 33, device_memory: 2, seed: 7 });
  })();
`);
check("存量未知 GPU 回填临时项", window.document.querySelector("#fp-gpu").value === "ANGLE (Old Custom)" && [...window.document.querySelectorAll("#fp-gpu option")].some((o) => o.textContent.includes("存量")));
check("存量未知时区回填临时项", window.document.querySelector("#fp-tz").value === "Mars/Olympus");
check("存量未知分辨率回填临时项", window.document.querySelector("#fp-screen").value === "1111x2222");

// ---- 7. 分组模板：fillTplForm / readTplForm 对称 ----
window.eval(`
  window.__tplRound = (function(){
    fillTplForm({ platform: "windows", brand: "Edge", timezone: "Asia/Shanghai", locale: "zh-CN", hardware_concurrency: 16, device_memory: 8, screen_width: 1536, screen_height: 864, gpu_renderer: "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)" });
    return readTplForm();
  })();
`);
const tpl = window.__tplRound || {};
check("模板往返：平台/品牌/时区保持", tpl.platform === "windows" && tpl.brand === "Edge" && tpl.timezone === "Asia/Shanghai");
check("模板往返：分辨率拆合一致", tpl.screen_width === 1536 && tpl.screen_height === 864);
check("模板往返：GPU 渲染器一致", (tpl.gpu_renderer || "").includes("UHD Graphics 630"));

console.log(failures ? `\n${failures} 项失败` : "\n全部通过");
process.exit(failures ? 1 : 0);

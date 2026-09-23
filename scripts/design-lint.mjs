#!/usr/bin/env node
/* ==========================================================================
   freedom-accounts · 前端设计规范校验器
   --------------------------------------------------------------------------
   把 DESIGN.md 里的规则变成可执行的断言。任何 AI 或人工进程在提交前端
   改动前运行本脚本，规则违背会被定位到文件与行号。

   用法：
     node scripts/design-lint.mjs           # 校验
     node scripts/design-lint.mjs --quiet   # 只输出问题

   退出码：0 = 无 ERROR（可能有 WARN）；1 = 存在 ERROR
   ========================================================================== */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const WEB = path.join(ROOT, "web");
const QUIET = process.argv.includes("--quiet");

const F = {
  tokens: path.join(WEB, "tokens.css"),
  style: path.join(WEB, "style.css"),
  html: path.join(WEB, "index.html"),
  js: path.join(WEB, "app.js"),
};

/* ---------- 终端着色（非 TTY 自动关闭） ---------------------------------- */
const TTY = process.stdout.isTTY;
const c = (code, s) => (TTY ? `\x1b[${code}m${s}\x1b[0m` : s);
const dim = (s) => c("2", s);
const red = (s) => c("31", s);
const yel = (s) => c("33", s);
const grn = (s) => c("32", s);
const bld = (s) => c("1", s);

/* ---------- 收集结果 ------------------------------------------------------ */
const errors = [];
const warns = [];
let currentRule = null;
const ruleStats = [];

const rule = (id, title) => {
  currentRule = { id, title, errors: 0, warns: 0 };
  ruleStats.push(currentRule);
};
const err = (file, line, msg, snippet) => {
  errors.push({ file, line, msg, snippet });
  if (currentRule) currentRule.errors++;
};
const warn = (file, line, msg, snippet) => {
  warns.push({ file, line, msg, snippet });
  if (currentRule) currentRule.warns++;
};

/* ---------- 读文件 -------------------------------------------------------- */
const missing = Object.entries(F).filter(([, p]) => !fs.existsSync(p));
if (missing.length) {
  console.error(red("缺少必需文件：") + missing.map(([k, p]) => `${k} → ${p}`).join(", "));
  process.exit(1);
}
const src = Object.fromEntries(Object.entries(F).map(([k, p]) => [k, fs.readFileSync(p, "utf8")]));
const rel = (p) => path.relative(ROOT, p);

/* ---------- 文本预处理：剥离注释但保留行号 -------------------------------- */
const blank = (m) => m.replace(/[^\n]/g, " ");
const stripCss = (s) => s.replace(/\/\*[\s\S]*?\*\//g, blank);
const stripHtml = (s) => s.replace(/<!--[\s\S]*?-->/g, blank);
const stripJs = (s) =>
  s.replace(/\/\*[\s\S]*?\*\//g, blank).replace(/(^|[^:\\])\/\/[^\n]*/g, (m, p1) => p1 + " ".repeat(m.length - p1.length));

const CLEAN = {
  tokens: stripCss(src.tokens),
  style: stripCss(src.style),
  html: stripHtml(src.html),
  js: stripJs(src.js),
};

const eachLine = (text, fn) => text.split("\n").forEach((l, i) => fn(l, i + 1));

/* ==========================================================================
   R1 · 禁止硬编码色值（tokens.css 是唯一合法来源）
   ========================================================================== */
rule("R1", "禁止硬编码色值，一律引用 var(--fa-*)");
{
  const HEX = /#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])/g;
  const FUNC = /\b(?:rgba?|hsla?)\(/g;

  // style.css：只检查声明值，跳过选择器（含 #id 与伪类）
  eachLine(CLEAN.style, (line, n) => {
    const decl = line.includes("{") ? line.slice(line.indexOf("{") + 1) : line;
    for (const re of [HEX, FUNC]) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(decl))) err(rel(F.style), n, `硬编码色值 ${m[0]}`, line.trim());
    }
  });

  // index.html / app.js：剔除 SVG 的 currentColor 与 CSS 变量名后检查
  for (const key of ["html", "js"]) {
    eachLine(CLEAN[key], (line, n) => {
      for (const re of [HEX, FUNC]) {
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(line))) {
          // 允许：SVG 命名空间、锚点引用、ID 选择器字符串
          const around = line.slice(Math.max(0, m.index - 12), m.index + m[0].length + 4);
          if (/xmlns|http|xlink|href|url\(#|^#[/-]/.test(around)) continue;
          err(rel(F[key]), n, `硬编码色值 ${m[0]}`, line.trim());
        }
      }
    });
  }
}

/* ==========================================================================
   R2 · 卡片不得使用阴影（对话框 / Toast / 焦点环除外）
   ========================================================================== */
rule("R2", "卡片与面板不得使用 box-shadow");
{
  const CARDISH = /(^|[\s,>])(\.card|\.panel|\.group-card|\.setting-card|\.metric|\.table-wrap)([\s,:.>]|$)/;
  // 允许：对话框 / Toast 的层级阴影（DESIGN.md §6）
  const ELEVATION = /var\(--fa-shadow-(modal|toast)\)/;
  // 允许：`0 0 0 <n>px` 形式的描边模拟 —— 选中态加粗边框，不改变布局尺寸（DESIGN.md §6）
  const RING = /box-shadow\s*:\s*0\s+0\s+0\s+/;

  const lines = CLEAN.style.split("\n");
  let selector = "";
  let depth = 0;

  lines.forEach((line, i) => {
    const n = i + 1;
    const open = (line.match(/\{/g) || []).length;
    const close = (line.match(/\}/g) || []).length;

    if (open > 0) {
      const head = line.slice(0, line.indexOf("{")).trim();
      if (head) selector = head;
    }

    if (/box-shadow\s*:/.test(line) && CARDISH.test(selector) && !ELEVATION.test(line) && !RING.test(line)) {
      err(rel(F.style), n, `卡片选择器 ${selector} 使用了层级阴影`, line.trim());
    }

    depth += open - close;
    if (depth <= 0) {
      depth = 0;
      selector = "";
    }
  });
}

/* ==========================================================================
   R3 · var(--fa-*) 引用必须已定义
   ========================================================================== */
rule("R3", "引用的设计变量必须已在 tokens.css 定义");
const DEFINED = new Set([...CLEAN.tokens.matchAll(/^\s*(--fa-[a-z0-9-]+)\s*:/gim)].map((m) => m[1]));
{
  for (const key of ["style", "html", "js"]) {
    eachLine(CLEAN[key], (line, n) => {
      for (const m of line.matchAll(/var\(\s*(--fa-[a-z0-9-]+)/g)) {
        if (!DEFINED.has(m[1])) err(rel(F[key]), n, `未定义的变量 ${m[1]}`, line.trim());
      }
    });
  }
}

/* ==========================================================================
   R4 · 未被引用的设计变量（提示）
   ========================================================================== */
rule("R4", "定义但未被引用的设计变量");
{
  const used = new Set();
  for (const key of ["style", "html", "js"]) {
    for (const m of CLEAN[key].matchAll(/var\(\s*(--fa-[a-z0-9-]+)/g)) used.add(m[1]);
  }
  // 变量之间互相引用也算使用
  for (const m of CLEAN.tokens.matchAll(/var\(\s*(--fa-[a-z0-9-]+)/g)) used.add(m[1]);

  const unreferenced = [];
  eachLine(CLEAN.tokens, (line, n) => {
    const m = line.match(/^\s*(--fa-[a-z0-9-]+)\s*:/);
    if (m && !used.has(m[1])) unreferenced.push({ name: m[1], line: n });
  });

  // 间距刻度属于「待接入」而非「冗余」：组件库仍有大量位置写裸像素值。
  // 聚合为一条带进度数据的提示，避免每次运行刷出 7 行同性质的告警。
  const rawSpacing = (
    CLEAN.style.match(/(padding|gap|margin|row-gap|column-gap)(-top|-right|-bottom|-left)?\s*:\s*[0-9]+px/g) || []
  ).length;
  const spacingTokens = unreferenced.filter((v) => v.name.startsWith("--fa-space-"));

  for (const v of unreferenced.filter((u) => !u.name.startsWith("--fa-space-"))) {
    warn(rel(F.tokens), v.line, `变量 ${v.name} 已定义但全项目未引用`);
  }
  if (spacingTokens.length) {
    warn(
      rel(F.tokens),
      spacingTokens[0].line,
      `间距刻度暂未接入组件库：仍有 ${rawSpacing} 处 padding/gap/margin 使用裸像素值。` +
        `新代码必须引用变量，存量在改动该区块时顺带迁移（DESIGN.md §11.3）`,
    );
  }
}

/* ==========================================================================
   R5 · JS / HTML 使用的类名必须已在 CSS 中定义
   ========================================================================== */
rule("R5", "使用的类名必须已在 CSS 中定义");
{
  const declared = new Set(
    [...CLEAN.style.matchAll(/\.([a-zA-Z][a-zA-Z0-9_-]*)/g), ...CLEAN.tokens.matchAll(/\.([a-zA-Z][a-zA-Z0-9_-]*)/g)].map(
      (m) => m[1],
    ),
  );
  const usedMap = new Map();
  const add = (cls, file, n) => {
    if (!cls || /[^A-Za-z0-9_-]/.test(cls)) return;
    if (!usedMap.has(cls)) usedMap.set(cls, { file, line: n });
  };

  // 模板字符串类名：`${...}` 内部的字面量也是类名候选（如 `class="chip ${cls}"` 或
  // `class="step-item${ok ? "" : " is-error"}"`），而 `${...}` 中的变量表达式本身不是
  // 类名，必须先摘除再按空白切分，否则会把 `tab-${tab}` 之类的片段误判为类名。
  const expandTemplate = (raw) => {
    const out = [];
    for (const m of raw.matchAll(/\$\{([^}]*)\}/g)) {
      for (const s of m[1].matchAll(/["'`]([^"'`]+)["'`]/g)) out.push(...s[1].split(/\s+/));
    }
    out.push(...raw.replace(/\$\{[^}]*\}/g, " ").split(/\s+/));
    return out;
  };

  eachLine(CLEAN.js, (line, n) => {
    for (const m of line.matchAll(/class(?:Name)?\s*=\s*["'`]([^"'`]+)["'`]/g))
      expandTemplate(m[1]).forEach((cls) => add(cls, rel(F.js), n));
    // classList.add/remove/toggle 只取紧跟左括号的第一个字符串字面量参数：
    // toggle 的第二个参数是布尔条件，其中的字符串不是类名。
    for (const m of line.matchAll(/classList\.(?:add|remove|toggle)\(\s*["'`]([^"'`]+)["'`]/g))
      m[1].split(/\s+/).forEach((cls) => add(cls, rel(F.js), n));
  });

  eachLine(CLEAN.html, (line, n) => {
    for (const m of line.matchAll(/class\s*=\s*"([^"]+)"/g)) m[1].split(/\s+/).forEach((cls) => add(cls, rel(F.html), n));
  });

  for (const [cls, loc] of usedMap) {
    if (!declared.has(cls)) err(loc.file, loc.line, `类名 .${cls} 在 CSS 中无定义`);
  }
}

/* ==========================================================================
   R6 · 字号与圆角不得写裸像素（提示）
   ========================================================================== */
rule("R6", "字号 / 圆角应引用变量而非裸像素");
{
  eachLine(CLEAN.style, (line, n) => {
    const m = line.match(/^\s*(font-size|border-radius)\s*:\s*([0-9.]+px)/);
    if (m && parseFloat(m[2]) !== 0) {
      warn(rel(F.style), n, `${m[1]}: ${m[2]} 建议改用 var(--fa-fs-* | --fa-radius-*)`, line.trim());
    }
  });
}

/* ==========================================================================
   R7 · 禁止用 emoji 充当图标
   ========================================================================== */
rule("R7", "禁止用 emoji 充当图标，应使用内联 SVG");
{
  const EMOJI =
    /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{1F1E6}-\u{1F1FF}\u{2700}-\u{27BF}]/gu;
  for (const key of ["html", "js"]) {
    eachLine(CLEAN[key], (line, n) => {
      const m = line.match(EMOJI);
      if (m) err(rel(F[key]), n, `出现 emoji ${JSON.stringify(m[0])}，图标请用内联 SVG`, line.trim());
    });
  }
}

/* ==========================================================================
   R8 · 后端接口路径必须落在冻结白名单内
   ========================================================================== */
rule("R8", "接口路径须在冻结白名单内");
const API_ALLOWLIST = [
  "/api/auth/login",
  "/api/auth/logout",
  "/api/auth/me",
  "/api/auth/change-password",
  "/api/meta",
  "/api/groups",
  "/api/groups/:id",
  "/api/groups/:id/start",
  "/api/groups/:id/open-browser",
  "/api/groups/:id/close-browser",
  "/api/groups/:id/regenerate-fingerprints",
  "/api/groups/:id/sync-accounts",
  "/api/groups/:id/refresh-tokens",
  "/api/groups/:id/fp-check",
  "/api/accounts",
  "/api/accounts/:id",
  "/api/accounts/:id/enabled",
  "/api/accounts/:id/fp-check",
  "/api/accounts/start",
  "/api/accounts/:id/stop",
  "/api/accounts/:id/refresh-token",
  "/api/accounts/batch-delete",
  "/api/accounts/:id/regenerate-fingerprint",
  "/api/accounts/:id/tasks",
  "/api/tasks",
  "/api/tasks/:id",
  "/api/proxies",
  "/api/proxies/:id",
  "/api/proxies/:id/test",
  "/api/geo/lookup",
  "/api/settings",
  "/api/logs/prune",
];
{
  const norm = (p) =>
    p
      .replace(/\$\{[^}]*\}/g, ":id")
      .split("?")[0]
      .replace(/\/+$/, "");
  const found = new Map();
  eachLine(CLEAN.js, (line, n) => {
    for (const m of line.matchAll(/(["'`])(\/api\/[^"'`]*)\1/g)) found.set(norm(m[2]), n);
  });

  for (const [p, n] of found) {
    if (!API_ALLOWLIST.includes(p)) err(rel(F.js), n, `接口 ${p} 不在白名单（如需新增请同步 DESIGN.md 与本脚本）`);
  }
  const unusedApi = API_ALLOWLIST.filter((p) => !found.has(p));
  if (unusedApi.length) {
    warns.push({
      file: rel(F.js),
      line: 0,
      msg: `白名单中未被前端调用（正常，可能由其他入口使用）：${unusedApi.join(", ")}`,
      _raw: true,
    });
  }
}

/* ==========================================================================
   R9 · 破坏性操作不得使用原生 confirm()
   ========================================================================== */
rule("R9", "破坏性操作须使用 confirmDialog，而非原生 confirm()");
{
  eachLine(CLEAN.js, (line, n) => {
    if (/(?<![\w.$])confirm\s*\(/.test(line)) err(rel(F.js), n, "使用了原生 confirm()，请改用 confirmDialog()", line.trim());
    if (/(?<![\w.$])alert\s*\(/.test(line)) warn(rel(F.js), n, "使用了原生 alert()，请改用 toast()", line.trim());
  });
}

/* ==========================================================================
   汇总报告
   ========================================================================== */
const lineCount = Object.values(src).reduce((a, s) => a + s.split("\n").length, 0);

if (!QUIET) {
  console.log("");
  console.log(bld("freedom-accounts · 前端设计规范校验"));
  console.log(dim("─".repeat(62)));
  console.log(`  规范来源  DESIGN.md`);
  console.log(`  扫描范围  web/tokens.css · style.css · index.html · app.js`);
  console.log(`  代码规模  ${Object.keys(F).length} 个文件 · ${lineCount} 行 · ${DEFINED.size} 个设计变量`);
  console.log(dim("─".repeat(62)));
  for (const r of ruleStats) {
    const status = r.errors ? red("✗") : r.warns ? yel("!") : grn("✓");
    const tally = [
      r.errors ? red(`${r.errors} ERROR`) : null,
      r.warns ? yel(`${r.warns} WARN`) : null,
    ]
      .filter(Boolean)
      .join("  ");
    console.log(`  ${status} ${r.id}  ${r.title.padEnd(40, " ")} ${tally || dim("通过")}`);
  }
  console.log(dim("─".repeat(62)));
}

const detail = (list, label, colorize) => {
  if (!list.length) return;
  console.log("");
  console.log(bld(colorize(`${label} (${list.length})`)));
  for (const e of list) {
    const loc = e.line ? `${e.file}:${e.line}` : e.file;
    console.log(`  ${colorize("›")} ${loc.padEnd(24, " ")} ${e.msg}`);
    if (e.snippet && !QUIET) console.log(`    ${dim(e.snippet.slice(0, 110))}`);
  }
};

detail(errors, "ERROR", red);
detail(warns, "WARN", yel);

console.log("");
if (errors.length) {
  console.log(red(bld(`✗ 未通过：${errors.length} 个 ERROR、${warns.length} 个 WARN`)));
  console.log(dim("  修复依据见 DESIGN.md §11.3 禁止清单"));
  process.exit(1);
}
console.log(grn(bld(`✓ 通过：0 ERROR、${warns.length} 个 WARN`)));

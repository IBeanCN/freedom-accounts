#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""freedom-accounts · 布局几何校验

jsdom 能验 DOM 结构，但验不了几何：卡片是否等高、按钮是否贴底、有没有溢出、
顶栏会不会塌陷，都必须用真实排版引擎量。本脚本用项目已有的 Playwright
（后端依赖，无需新增）打开运行中的实例，对各页面做几何断言，输出为文本。

判定标准：
  - 分组页 —— DESIGN.md §7.16（无指标条、首元素为 .section-head、新建按钮贴在计数徽标右侧、
    操作区按钮形态统一、风险圆点在分组名左侧），指标条规则见 §7.6
  - 分组卡交互 —— DESIGN.md §7.16「交互解耦」：点箭头只开操作项、点卡体只开账号列表
  - 任务页 —— DESIGN.md §7.6（指标条 4 项、数字真实可算）
  - 设置页 —— DESIGN.md §7.15（三段结构、同排等高、按钮贴底）

用法：
    # 先起服务（不要占用你正在跑的 8000）
    FA_PORT=8123 .venv/bin/python -m uvicorn app.main:app --port 8123
    .venv/bin/python scripts/layout-check.py [--base http://127.0.0.1:8123]

退出码：0 = 全部通过；1 = 存在失败项
"""
import argparse
import sys
from playwright.sync_api import sync_playwright

FAIL = []


def check(ok, msg):
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        FAIL.append(msg)


# --------------------------------------------------------------------------
# 分组页
# --------------------------------------------------------------------------
MEASURE_GROUPS_JS = """
() => {
  const page = document.querySelector('#tab-groups');
  const grid = document.querySelector('#groups-grid');
  const out = { overflow: [], cards: [], risk: [], actionBtnH: [], actionBtnPad: [], actionBtnRadius: [] };
  const first = page.firstElementChild;
  out.firstChildClass = first ? String(first.className) : '';
  out.metricsCount = page.querySelectorAll('.metrics').length;
  out.sectionHeadTitle = page.querySelector('.section-head .section-title').textContent.trim();
  out.groupCountText = page.querySelector('#group-count').textContent.trim();

  // 标题行的「新建分组」按钮：必须与计数徽标同处 .section-head 并垂直居中
  const btn = document.querySelector('#btn-new-group');
  const chip = document.querySelector('#group-count');
  if (btn && chip) {
    const b = btn.getBoundingClientRect(), c = chip.getBoundingClientRect();
    out.newBtn = {
      w: Math.round(b.width), h: Math.round(b.height),
      left: Math.round(b.left),
      centerY: Math.round(b.top + b.height / 2),
      chipCenterY: Math.round(c.top + c.height / 2),
      chipRight: Math.round(c.right),
      text: btn.textContent.trim(),
      inSectionHead: !!btn.closest('.section-head'),
    };
  } else out.newBtn = null;

  out.gridCols = getComputedStyle(grid).gridTemplateColumns;
  out.topbarHeight = Math.round(document.querySelector('.topbar').getBoundingClientRect().height);
  out.visibleActions = [...document.querySelectorAll('.page-actions .act-set')]
    .filter((s) => !s.classList.contains('hidden'))
    .reduce((n, s) => n + s.querySelectorAll('button').length, 0);
  out.titleTop = Math.round(document.querySelector('#page-title').getBoundingClientRect().top + window.scrollY);
  out.contentTop = Math.round(grid.getBoundingClientRect().top + window.scrollY);

  // 操作区默认收起（display:none），量按钮前必须先展开。幂等：只展开未展开的卡片
  grid.querySelectorAll('.group-card').forEach((c) => {
    if (!c.classList.contains('is-open')) c.querySelector('.group-toggle').click();
  });

  // 夹具：库里可能一个分组都没有检测结果，此时圆点不渲染。临时注入一个来验证
  // 「圆点在分组名左侧」这条几何契约，量完即移除。
  let injected = false;
  if (!grid.querySelector('.group-name-row .fp-badge')) {
    const row = grid.querySelector('.group-name-row');
    if (row) {
      const s = document.createElement('span');
      s.className = 'fp-badge fp-badge-warning';
      row.insertBefore(s, row.firstChild);
      injected = true;
    }
  }

  grid.querySelectorAll('.group-card').forEach((c) => {
    const r = c.getBoundingClientRect();
    const nameEl = c.querySelector('.group-name');
    const nr = nameEl.getBoundingClientRect();
    const dot = c.querySelector('.group-name-row .fp-badge');
    const toggle = c.querySelector('.group-toggle');
    const tr = toggle.getBoundingClientRect();
    const btns = [...c.querySelectorAll('.group-actions .btn')]
      .filter((b) => !b.classList.contains('hidden'));   // 本地 SDK 专属按钮在 CDP 模式下隐藏，不计入
    const headText = c.querySelector('.group-head-text').getBoundingClientRect();
    out.cards.push({
      name: nameEl.textContent.trim(),
      w: Math.round(r.width), h: Math.round(r.height),
      top: Math.round(r.top + window.scrollY), left: Math.round(r.left),
      btnCount: btns.length,
      openBtn: btns.filter((b) => b.dataset.act === 'open-browser' && !b.classList.contains('hidden')).length,
      closeBtn: btns.filter((b) => b.dataset.act === 'close-browser' && !b.classList.contains('hidden')).length,
      toggleW: Math.round(tr.width), toggleH: Math.round(tr.height),
      hasDot: !!dot,
      headTextLeft: Math.round(headText.left),
      nameLeft: Math.round(nr.left),
    });
    btns.forEach((b) => {
      const br = b.getBoundingClientRect();
      const bs = getComputedStyle(b);
      out.actionBtnH.push(Math.round(br.height));
      out.actionBtnPad.push(bs.paddingLeft);
      out.actionBtnRadius.push(bs.borderTopLeftRadius);
    });
    if (dot) {
      const dr = dot.getBoundingClientRect();
      out.risk.push({
        group: nameEl.textContent.trim(),
        dotRight: Math.round(dr.right), dotW: Math.round(dr.width),
        dotCenterY: Math.round(dr.top + dr.height / 2),
        nameLeft: Math.round(nr.left), nameCenterY: Math.round(nr.top + nr.height / 2),
      });
    }
  });

  if (injected) grid.querySelectorAll('.group-name-row .fp-badge').forEach((n) => n.remove());

  grid.querySelectorAll('*').forEach((el) => {
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) out.overflow.push(String(el.className));
  });
  return out;
}
"""


def audit_groups(data, label):
    print("\n" + "=" * 68)
    print("分组页布局几何校验 · %s" % label)
    print("=" * 68)
    print("网格列定义:", data["gridCols"].strip())
    print("顶栏高度:", data["topbarHeight"], "px ｜ 可见操作按钮:", data["visibleActions"])
    print("首元素:", data["firstChildClass"], "｜ 分区标题:", data["sectionHeadTitle"],
          "｜ 计数徽标:", data["groupCountText"])

    check(data["metricsCount"] == 0, "分组页无指标条（已移除：数字与计数徽标 / 账号面板重复）")
    check("section-head" in data["firstChildClass"], "分组页首元素是 .section-head")
    check(data["visibleActions"] == 0, "分组页顶栏无操作按钮（新建入口在标题行）")
    check(data["topbarHeight"] >= 56, "顶栏未塌陷（h=%s ≥ 56）" % data["topbarHeight"])
    check(data["contentTop"] > data["titleTop"], "内容区位于顶栏之下")

    # 「新建分组」按钮：贴在计数徽标右侧、垂直居中
    nb = data["newBtn"]
    check(nb is not None, "标题行存在「新建分组」按钮")
    if nb:
        print("\n[新建分组按钮] %r w=%s h=%s left=%s centerY=%s ｜ 计数徽标 right=%s centerY=%s"
              % (nb["text"], nb["w"], nb["h"], nb["left"], nb["centerY"], nb["chipRight"], nb["chipCenterY"]))
        check(nb["inSectionHead"], "「新建分组」按钮位于 .section-head 内（跟随标题与计数）")
        check(nb["left"] > nb["chipRight"],
              "「新建分组」按钮紧接计数徽标右侧 (left=%s > chip.right=%s)" % (nb["left"], nb["chipRight"]))
        check(abs(nb["centerY"] - nb["chipCenterY"]) <= 2,
              "「新建分组」按钮与计数徽标垂直居中 (Δ%s)" % abs(nb["centerY"] - nb["chipCenterY"]))
        check(nb["h"] == 32, "「新建分组」沿用 .btn-sm 高度（h=%s）" % nb["h"])
        check(nb["text"] == "新建分组", "按钮文案为「新建分组」")

    cards = data["cards"]
    print("\n分组卡片 %d 张" % len(cards))
    for c in cards:
        print("  %-16s w=%-5s h=%-4s top=%-5s left=%-5s 操作按钮=%s 箭头=%s×%s 圆点=%s"
              % (c["name"], c["w"], c["h"], c["top"], c["left"],
                 c["btnCount"], c["toggleW"], c["toggleH"], "有" if c["hasDot"] else "无"))
    print("水平溢出:", data["overflow"] if data["overflow"] else "无")
    check(not data["overflow"], "分组网格无水平溢出")

    # 有 / 无检测结果的两种分组名必须左对齐到同一基线：无圆点时名字回到行首，不留空位
    no_dot = [c for c in cards if not c["hasDot"]]
    if no_dot:
        print("无圆点分组名 left=%s ｜ 标题区 left=%s"
              % ([c["nameLeft"] for c in no_dot], [c["headTextLeft"] for c in no_dot]))
        check(all(abs(c["nameLeft"] - c["headTextLeft"]) <= 1 for c in no_dot),
              "无检测结果时圆点不占位，分组名回到行首")

    if cards:
        first_row = [c for c in cards if c["top"] == cards[0]["top"]]
        check(all(c["top"] == first_row[0]["top"] for c in first_row), "首行分组卡顶部对齐")
        check(all(c["w"] == first_row[0]["w"] for c in first_row), "首行分组卡等宽")
        check(all(c["btnCount"] == 7 for c in cards),
              "每张卡片 7 个操作按钮（5 个基础 + 打开/关闭浏览器）（实际 %s）" % sorted({c["btnCount"] for c in cards}))
        # 本地 SDK 专属按钮：未配置 CDP 时均应显示；此处服务无 CDP，应有且仅各 1 个
        check(all(c["openBtn"] == 1 for c in cards),
              "本地 SDK 模式下每卡出现 1 个「打开浏览器」按钮（实际 %s）" % sorted({c["openBtn"] for c in cards}))
        check(all(c["closeBtn"] == 1 for c in cards),
              "本地 SDK 模式下每卡出现 1 个「关闭浏览器」按钮（实际 %s）" % sorted({c["closeBtn"] for c in cards}))
        check(all(c["toggleW"] == 30 and c["toggleH"] == 30 for c in cards),
              "展开箭头复用 .icon-btn 尺寸 30×30（实际 %s）" % sorted({(c["toggleW"], c["toggleH"]) for c in cards}))

    # 操作区按钮形态统一 —— 本次改动的核心断言。
    # 旧版「编辑」用 .btn-text（padding 6px）、「删除」用 .btn-danger（padding 6px），
    # 与其余 .btn-sm（13px）并排，同一行里出现两种内边距与有无边框的混搭。
    if data["actionBtnH"]:
        uniq_h = sorted(set(data["actionBtnH"]))
        uniq_pad = sorted(set(data["actionBtnPad"]))
        uniq_r = sorted(set(data["actionBtnRadius"]))
        print("\n操作区按钮 共 %d 个 ｜ 高度 %s ｜ 左内边距 %s ｜ 圆角 %s"
              % (len(data["actionBtnH"]), uniq_h, uniq_pad, uniq_r))
        check(len(uniq_h) == 1 and uniq_h[0] == 32, "操作区按钮高度一致且为 .btn-sm（%s）" % uniq_h)
        check(len(uniq_pad) == 1, "操作区按钮水平内边距一致（%s）" % uniq_pad)
        check(len(uniq_r) == 1, "操作区按钮圆角一致（%s）" % uniq_r)

    # 风险圆点在分组名左侧、与名称垂直居中
    if data["risk"]:
        print("\n风险圆点 %d 个" % len(data["risk"]))
        for r in data["risk"]:
            print("  %-16s dot.right=%-5s name.left=%-5s dot.centerY=%-5s name.centerY=%s"
                  % (r["group"], r["dotRight"], r["nameLeft"], r["dotCenterY"], r["nameCenterY"]))
            check(r["dotRight"] <= r["nameLeft"],
                  "%s：风险圆点在分组名左侧 (dot.right=%s ≤ name.left=%s)"
                  % (r["group"], r["dotRight"], r["nameLeft"]))
            check(abs(r["dotCenterY"] - r["nameCenterY"]) <= 2,
                  "%s：风险圆点与分组名垂直居中 (Δ%s)"
                  % (r["group"], abs(r["dotCenterY"] - r["nameCenterY"])))
    else:
        check(False, "风险圆点几何未能测量（无分组卡片）")


# --------------------------------------------------------------------------
# 任务页
# --------------------------------------------------------------------------
MEASURE_TASKS_JS = """
() => {
  const page = document.querySelector('#tab-tasks');
  const out = { metrics: [], overflow: [] };
  page.querySelectorAll('.metric').forEach((m) => {
    const r = m.getBoundingClientRect();
    out.metrics.push({
      label: m.querySelector('.metric-label').textContent.trim(),
      value: m.querySelector('.metric-value').textContent.trim(),
      w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top + window.scrollY),
    });
  });
  out.dividerCount = page.querySelectorAll('.metric-divider').length;
  out.filterCount = page.querySelectorAll('#task-filter .segmented-item').length;
  out.bodyRows = page.querySelectorAll('#tasks-table tbody tr').length;
  page.querySelectorAll('*').forEach((el) => {
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0 && el.clientWidth > 60) {
      out.overflow.push(String(el.className));
    }
  });
  return out;
}
"""


def audit_tasks(data, label):
    print("\n" + "=" * 68)
    print("任务页布局几何校验 · %s" % label)
    print("=" * 68)
    for m in data["metrics"]:
        print("  %-8s %-6s w=%-5s h=%-4s top=%s" % (m["label"], m["value"], m["w"], m["h"], m["top"]))
    print("任务行数:", data["bodyRows"], "｜ 筛选段数:", data["filterCount"])
    print("水平溢出:", data["overflow"] if data["overflow"] else "无")

    check(len(data["metrics"]) == 4, "任务页指标条 4 项（实际 %s）" % len(data["metrics"]))
    check(data["dividerCount"] == 3, "指标条分隔线 3 条（实际 %s）" % data["dividerCount"])
    if data["metrics"]:
        tops = {m["top"] for m in data["metrics"]}
        check(len(tops) == 1, "指标条同排顶部对齐")
        check(data["metrics"][0]["h"] >= 40, "指标块有足够高度（h=%s）" % data["metrics"][0]["h"])
    check(data["filterCount"] == 4, "任务筛选 4 段（实际 %s）" % data["filterCount"])
    check(not data["overflow"], "任务页无水平溢出")


# --------------------------------------------------------------------------
# 设置页
# --------------------------------------------------------------------------
MEASURE_SETTINGS_JS = """
() => {
  const out = { groups: [], overflow: [] };
  document.querySelectorAll('#tab-settings .settings-group').forEach((g) => {
    const head = g.querySelector('.settings-group-head');
    const cards = [...g.querySelectorAll('.setting-card')].map((c) => {
      const cs = getComputedStyle(c);
      const r = c.getBoundingClientRect();
      const head = c.querySelector('.setting-head');
      const body = c.querySelector('.setting-body');
      const foot = c.querySelector('.setting-foot');
      return {
        title: c.querySelector('.setting-title').textContent.trim(),
        top: Math.round(r.top + window.scrollY),
        height: Math.round(r.height),
        width: Math.round(r.width),
        padding: cs.paddingTop,
        footBottom: Math.round(foot.getBoundingClientRect().bottom + window.scrollY),
        bodyFlex: getComputedStyle(body).flexGrow,
        headBorder: getComputedStyle(head).borderBottomWidth,
        // 内容区末元素到操作区顶部的留白：过大说明这张卡整体被撑出了空白
        slack: Math.round(foot.getBoundingClientRect().top - body.lastElementChild.getBoundingClientRect().bottom),
      };
    });
    out.groups.push({ name: head ? head.querySelector('.section-title').textContent.trim() : '?', cards });
  });
  document.querySelectorAll('#tab-settings .setting-card *').forEach((el) => {
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
      out.overflow.push(el.className + ' :: ' + el.textContent.trim().slice(0, 24));
    }
  });
  const grid = document.querySelector('#tab-settings .settings-grid');
  out.gridCols = getComputedStyle(grid).gridTemplateColumns;
  return out;
}
"""

SLACK_LIMIT = 80  # 单张卡内容区末元素到操作区的留白上限（px）


def audit_settings(data, label):
    print("\n" + "=" * 68)
    print("设置页布局几何校验 · %s" % label)
    print("=" * 68)
    print("网格列定义:", data["gridCols"].strip())

    total = 0
    for g in data["groups"]:
        print("\n[%s]" % g["name"])
        for c in g["cards"]:
            print("  %-20s w=%-5s h=%-4s top=%-5s foot=%-5s slack=%s"
                  % (c["title"], c["width"], c["height"], c["top"], c["footBottom"], c["slack"]))
        cards = g["cards"]
        total += len(cards)
        if len(cards) == 2:
            a, b = cards
            check(a["width"] == b["width"], "%s：两列等宽 (%s/%s)" % (g["name"], a["width"], b["width"]))
            check(abs(a["top"] - b["top"]) <= 1, "%s：同排顶部对齐 (Δ%s)" % (g["name"], abs(a["top"] - b["top"])))
            check(a["height"] == b["height"], "%s：同排等高 (%s/%s)" % (g["name"], a["height"], b["height"]))
            check(abs(a["footBottom"] - b["footBottom"]) <= 2,
                  "%s：操作按钮贴底对齐 (Δ%s)" % (g["name"], abs(a["footBottom"] - b["footBottom"])))
        for c in cards:
            check(c["bodyFlex"] == "1", "%s：内容区 flex:1" % c["title"])
            check(c["headBorder"] == "1px", "%s：标题区有收口分隔线" % c["title"])
            check(c["slack"] <= SLACK_LIMIT, "%s：无过大空白 (slack=%s ≤ %s)" % (c["title"], c["slack"], SLACK_LIMIT))

    print("\n卡片总数:", total)
    print("水平溢出:", data["overflow"] if data["overflow"] else "无")
    check(total == 6, "设置卡数量 = 6")
    check(not data["overflow"], "卡片内无水平溢出")


# --------------------------------------------------------------------------
# 分组卡交互解耦（真实浏览器行为断言，非几何）
# --------------------------------------------------------------------------
INTERACTION_STATE_JS = """
() => {
  const card = document.querySelector('#groups-grid .group-card');
  const t = card.querySelector('.group-toggle');
  const actions = card.querySelector('.group-actions');
  return {
    open: card.classList.contains('is-open'),
    selected: card.classList.contains('is-selected'),
    current: card.getAttribute('aria-current'),
    ariaExpanded: t.getAttribute('aria-expanded'),
    controls: t.getAttribute('aria-controls'),
    actionsId: actions.id,
    actionsDisplay: getComputedStyle(actions).display,
    panel: !document.querySelector('#accounts-panel').classList.contains('hidden'),
    toggleTabIndex: t.tabIndex,
  };
}
"""


def audit_group_interaction(page):
    """点箭头只开操作项、点卡体只开账号列表 —— 两件事必须互不牵连。"""
    print("\n" + "=" * 68)
    print("分组卡交互解耦校验 · 箭头 vs 卡体")
    print("=" * 68)

    # 显式触发一次 loadSettings，确保「打开浏览器」按钮显隐已按当前引擎模式应用
    page.evaluate("() => loadSettings()")
    page.wait_for_timeout(600)

    page.click('.rail-item[data-tab="groups"]')
    page.wait_for_selector("#groups-grid .group-card", timeout=8000)
    page.wait_for_timeout(400)

    # 归零：收起全部操作项 + 关闭账号面板
    page.evaluate("""() => {
      document.querySelectorAll('#groups-grid .group-card.is-open .group-toggle')
        .forEach((b) => b.click());
      const c = document.querySelector('#btn-close-accounts');
      if (c) c.click();
    }""")
    page.wait_for_timeout(300)

    s0 = page.evaluate(INTERACTION_STATE_JS)
    print("\n[初始]      操作项=%s 选中=%s 账号面板=%s"
          % ("展开" if s0["open"] else "收起", "是" if s0["selected"] else "否",
             "展开" if s0["panel"] else "关闭"))
    check(not s0["open"], "初始：操作项收起")
    check(not s0["selected"], "初始：分组未被选中")
    check(not s0["panel"], "初始：账号面板关闭")
    check(s0["ariaExpanded"] == "false", "箭头 aria-expanded=false")
    check(bool(s0["actionsId"]) and s0["controls"] == s0["actionsId"],
          "箭头 aria-controls 指向本卡操作区 (%s → %s)" % (s0["controls"], s0["actionsId"]))
    check(s0["toggleTabIndex"] == 0,
          "箭头可键盘聚焦（tabIndex=%s，不再是 -1）" % s0["toggleTabIndex"])

    # ① 点卡体（分组元信息行）—— 只应打开账号列表
    page.click("#groups-grid .group-card .group-sub")
    page.wait_for_timeout(500)
    s1 = page.evaluate(INTERACTION_STATE_JS)
    print("[点卡体]    操作项=%s 选中=%s 账号面板=%s"
          % ("展开" if s1["open"] else "收起", "是" if s1["selected"] else "否",
             "展开" if s1["panel"] else "关闭"))
    check(s1["panel"], "① 点卡体：账号列表展开")
    check(s1["selected"] and s1["current"] == "true", "① 点卡体：卡片进入选中态")
    check(not s1["open"] and s1["actionsDisplay"] == "none",
          "★ 点卡体不展开操作项（.group-actions display=%s）" % s1["actionsDisplay"])

    # ② 点箭头 —— 只应打开操作项，不动账号列表与选中态
    page.click("#groups-grid .group-card .group-toggle")
    page.wait_for_timeout(350)
    s2 = page.evaluate(INTERACTION_STATE_JS)
    print("[点箭头]    操作项=%s 选中=%s 账号面板=%s"
          % ("展开" if s2["open"] else "收起", "是" if s2["selected"] else "否",
             "展开" if s2["panel"] else "关闭"))
    check(s2["open"] and s2["actionsDisplay"] != "none", "★ 点箭头展开操作项")
    check(s2["ariaExpanded"] == "true", "② 点箭头后 aria-expanded=true")
    check(s2["selected"], "② 点箭头不改变选中态")
    check(s2["panel"], "② 点箭头不关闭账号列表")

    # ③ 操作项已展开时再点卡体 —— 不应把它收起
    page.click("#groups-grid .group-card .group-sub")
    page.wait_for_timeout(500)
    check(page.evaluate(INTERACTION_STATE_JS)["open"],
          "★ 操作项已展开时点卡体不会把它收起")

    # ④ 再点箭头收起
    page.click("#groups-grid .group-card .group-toggle")
    page.wait_for_timeout(350)
    check(not page.evaluate(INTERACTION_STATE_JS)["open"], "④ 再次点箭头收起操作项")

    # 归零，避免影响其它检查
    page.evaluate("() => { const c = document.querySelector('#btn-close-accounts'); if (c) c.click(); }")
    page.wait_for_timeout(200)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8123")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(args.base + "/", wait_until="networkidle")
        page.fill("#login-user", "admin")
        page.fill("#login-pass", "admin123")
        page.click("#login-form button[type=submit]")
        page.wait_for_selector("#view-main:not(.hidden)", timeout=8000)

        # --- 分组页 ---
        page.wait_for_selector("#groups-grid .group-card", timeout=8000)
        page.wait_for_timeout(500)
        # 先等 loadSettings 拉到引擎模式，「打开浏览器」显隐就位后再量卡片
        page.evaluate("() => loadSettings()")
        page.wait_for_timeout(600)
        audit_groups(page.evaluate(MEASURE_GROUPS_JS), "viewport 1600×1000")

        # --- 任务页 ---
        page.click('.rail-item[data-tab="tasks"]')
        page.wait_for_selector("#tab-tasks:not(.hidden)", timeout=5000)
        page.wait_for_timeout(500)
        audit_tasks(page.evaluate(MEASURE_TASKS_JS), "viewport 1600×1000")

        # --- 设置页：两级宽度 ---
        page.click('.rail-item[data-tab="settings"]')
        page.wait_for_selector("#tab-settings:not(.hidden)", timeout=5000)
        page.wait_for_timeout(700)
        audit_settings(page.evaluate(MEASURE_SETTINGS_JS), "viewport 1600×1000")

        page.set_viewport_size({"width": 1280, "height": 900})
        page.wait_for_timeout(350)
        audit_settings(page.evaluate(MEASURE_SETTINGS_JS), "viewport 1280×900")

        # --- 窄屏：设置网格与状态块收成单列 ---
        page.set_viewport_size({"width": 900, "height": 1000})
        page.wait_for_timeout(400)
        cols = len(page.evaluate(
            "() => getComputedStyle(document.querySelector('#tab-settings .settings-grid')).gridTemplateColumns").split())
        status_cols = len(page.evaluate(
            "() => getComputedStyle(document.querySelector('#tab-settings .status-list')).gridTemplateColumns").split())
        check(cols == 1, "≤960px 设置网格收成单列")
        check(status_cols == 2, "≤960px 引擎状态块收成单列键值（2 列定义）")

        # --- 窄屏下的分组页：顶栏按钮区为空不应塌陷 ---
        page.click('.rail-item[data-tab="groups"]')
        page.wait_for_timeout(400)
        page.evaluate("() => loadSettings()")
        page.wait_for_timeout(600)
        g = page.evaluate(MEASURE_GROUPS_JS)
        audit_groups(g, "viewport 900×1000")

        # --- 分组卡交互解耦：点箭头只开操作项、点卡体只开账号列表 ---
        audit_group_interaction(page)

        browser.close()

    print("\n" + "=" * 68)
    if FAIL:
        print("✗ 未通过 %d 项：" % len(FAIL))
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print("✓ 全部通过")


if __name__ == "__main__":
    main()

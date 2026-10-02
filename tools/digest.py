#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""digest —— 生成「注入面」（≤60 行的小文件），供宿主在会话开始注入上下文。

为什么需要它（承外部独立评估 · 2026-10-02）：
  「被持续想起」不是本库自身的功能 —— 它由**宿主侧接线**产生。
  但接线注入的内容必须**小、短、置顶**（长注入会稀释注意力：Context Rot / Lost-in-the-Middle）。
  ⇒ 本工具把「库的当前态」压成一页 digest：身份一句 ＋ 红线 ＋ 当前事项 ＋ **最后更新时间戳** ＋ **接线自证行**。
  「六件必读」降为 digest 里的一句指针 —— 需要细节时由模型自行按 MANIFEST 读取。

★ 2026-10-02 加「主人称呼」一行（由来＝**首见环节实测**「问完不知道叫主人什么」）：
  称呼从 `USER.md §1` 抽一行进注入面 ⇒ **每次注入必含该行**（注入时机由宿主定）；**缺项即给安全默认**，不留空。

自证式注入：
  digest 里带「库最后更新时间戳」与「本次由哪条接线注入」——
  于是「库已 N 天未更新」会出现在**每一轮**注入里，停滞对双方可见（不靠记性）。

用法：
  python tools/digest.py --root <库根> [--via "L1:SessionStart"] [--out FILE]
  python tools/digest.py --root <库根> --selftest

退出码：0 成功 ｜ 2 参数/IO 错误
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MAX_LINES = 60
MAX_CHARS = 3800          # 注入面硬上限（远低于各家注入截断阈值）
DEFAULT_CALL = "未定（默认使用「你」）"   # ★ 称呼缺项的安全默认（承外部实务「smart defaults」：
                                          #   缺项不空、给默认、且写出来 —— 2026-10-02 加）


def _first_lines(p: Path, n: int) -> list:
    """取正文前 n 条（**跳过首部 YAML frontmatter** 与**任意层级标题行**）。

    2026-10-02 修一：原版只跳 `---`／`# `，未跳 frontmatter 的 `key: value` 行
    ⇒ N0 库的 digest 里「红线」抓成了 `title:` / `summary:`（实测暴露）。
    2026-10-02 修二（`0.1.15`）：标题行**只跳一级**（`# `）⇒ `##` 及以下**漏进注入面**
    （本机接入实测暴露：注入面混入 `## 〇、新生儿态`）⇒ 改跳 `#{1,6}`。
    """
    if not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    i = 0
    if lines and lines[0].strip() == "---":          # 跳过 frontmatter 块
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                i = j + 1
                break
    out = []
    for ln in lines[i:]:
        s = ln.rstrip()
        if not s or s.startswith("---") or re.match(r"^#{1,6}\s", s):
            continue
        s = re.sub(r"^(\s*[-*]\s*)#{1,6}\s*", r"\1", s)      # `- ## 标题` ⇒ `- 标题`
        out.append(s)
        if len(out) >= n:
            break
    return out


def _principal_call(root: Path) -> str:
    """取主人在 `USER.md` 里的称呼（**缺项即给安全默认** —— 承外部实务「smart defaults」）。

    2026-10-02 加：原设计把称呼当作"首见时的顺带一句" ⇒ **实测最容易被漏**，
    漏了以后**没有任何一轮知道该叫什么**。本函数保证：**取不到/为空/仍是占位词 ⇒ 返回默认**，
    于是「叫主人什么」**每次注入都有答案**（该行必含）。
    """
    p = root / "01-记忆档案" / "USER.md"
    try:
        txt = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    except OSError:
        txt = ""
    m = re.search(r"^[-*]\s*\*\*称呼\*\*\s*[：:]\s*(.+?)\s*$", txt, re.M)
    if not m:
        return DEFAULT_CALL
    v = m.group(1).split("｜")[0].split("<!--")[0]
    v = re.sub(r"[（(][^）)]*[）)]", "", v)      # 去括注（如「（主人选…）」）—— 2026-10-02 修 A3
    v = v.replace("「", "").replace("」", "").replace('"', "").replace("“", "").replace("”", "")
    v = v.strip().strip("*").strip()
    if not v or v in ("待补", "待定", "未定"):
        return DEFAULT_CALL
    return v


def _section_lines(p: Path, key: str, n: int) -> list:
    """取 `## <key>` 段的正文前 n 条（**2026-10-02 加 · 治首见演练 A4**）。

    病根：原按"正文前 N 行"取样 ⇒ 文件一有内容，抓到的就是**文件头**（§〇 说明行），
    于是「三条行为」只能出 1 条。本函数按**段**取。

    返回：**有该段** ⇒ 列表（**可能为空**，即该段尚无内容）；**无该段** ⇒ `None`
    （调用方据此决定是否回退到 `_first_lines` —— 二者语义不同，别混）。
    """
    try:
        txt = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    except OSError:
        txt = ""
    m = re.search(r"^##\s*" + re.escape(key) + r".*?$(.*?)(?=^##\s|\Z)", txt, re.S | re.M)
    if not m:
        return None
    out = []
    for ln in m.group(1).splitlines():
        s = ln.rstrip()
        if not s or s.startswith("---") or s.startswith(">") or re.match(r"^#{1,6}\s", s):
            continue
        if s.strip().strip("`*_") in ("none",):
            continue
        s = re.sub(r"^(\s*[-*]\s*)#{1,6}\s*", r"\1", s)
        out.append(s)
        if len(out) >= n:
            break
    return out


def _qzone(p: Path, n: int) -> list:
    """取「会话速读包 §① 当前核心事项」区的前 n 条（按其 `- ` 开头行）。"""
    if not p.is_file():
        return []
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    m = re.search(r"##\s*①(.+?)(?=\n##\s|\Z)", txt, re.S)
    if not m:
        return []
    out = [ln.rstrip() for ln in m.group(1).splitlines() if ln.strip().startswith("- ")]
    return out[:n]


def _last_update(root: Path) -> "tuple[str, int, int]":
    """库最后更新时间戳（扫 01-记忆档案/**），返回 (ISO, 距今天数, 件数)。"""
    base = root / "01-记忆档案"
    newest, n = 0.0, 0
    if base.is_dir():
        for f in base.rglob("*"):
            if f.is_file() and f.name not in (".gitkeep",):
                n += 1
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    pass
    if newest <= 0:
        return ("（无）", -1, n)
    days = int((time.time() - newest) // 86400)
    return (dt.datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M"), days, n)


def build(root: Path, via: str) -> str:
    a = root / "01-记忆档案"
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    iso, days, nfiles = _last_update(root)
    _sec = _section_lines(a / "SOUL.md", "一、红线", 4)
    reds = _sec if _sec is not None else _first_lines(a / "SOUL.md", 4)
    who = _first_lines(a / "USER.md", 2)
    now = _qzone(a / "记忆工程" / "会话速读包.md", 5)
    call = _principal_call(root)

    L = []
    L.append("# 记忆库 digest ｜ 生成 %s ｜ **本次注入接线：%s**" % (stamp, via or "（未标注）"))
    L.append("")
    L.append("> 本件＝**注入面**（小、短、置顶）。细节勿依赖此处 —— 按库根 `AGENTS.md` → `MANIFEST.md` 的读序自取。")
    L.append("")
    L.append("## 一、红线（节自 `01-记忆档案/SOUL.md`）")
    L += ["- " + x.lstrip("- ").strip() for x in reds] or ["- （N0 新生儿态：尚无红线条目）"]
    L.append("")
    L.append("## 二、我是谁（节自 `01-记忆档案/USER.md`）")
    L += ["- " + x.lstrip("- ").strip() for x in who] or ["- （尚未写入）"]
    L.append("- **主人称呼：%s**" % call)          # ★ 2026-10-02 加 · 结构性防漏
    L.append("")
    L.append("## 三、当前事项（节自 `记忆工程/会话速读包.md` §①）")
    L += ["- " + x.lstrip("- ").strip() for x in now] or ["- （N0 新生儿态：尚无当前事项）"]
    L.append("")
    L.append("## 四、状态（自证 · 每轮可见）")
    L.append("- **库最后更新：%s**（%s）" % (
        iso, ("今天" if days == 0 else ("%d 天前" % days)) if days >= 0 else "无数据"))
    L.append("- 索引条目：%d 件（`01-记忆档案/**`）" % nfiles)
    L.append("- **本次由哪条接线注入：%s** —— 接线未写明 ⇒ 视为未接入。" % (via or "（未标注）"))
    L.append("- 停滞可见：若「库最后更新」长期不动 ⇒ 本库正在变旧，请提醒主人。")
    L.append("")
    L.append("> **接入与验收**：见 `docs/接入卡.md`（每宿主一页）与 `docs/接入演练.md`（两问演练）。")

    out = "\n".join(L)
    if len(L) > MAX_LINES or len(out) > MAX_CHARS:       # 硬闸：超限即截（防注入面膨胀）
        out = "\n".join(L[:MAX_LINES])[:MAX_CHARS] + "\n\n> （已按注入面上限截断）"
    return out.rstrip() + "\n"


def selftest() -> int:
    import tempfile
    cases = 0
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "01-记忆档案" / "记忆工程").mkdir(parents=True)
        for name in ("SOUL.md", "USER.md", "MEMORY.md"):
            (r / "01-记忆档案" / name).write_text("- 条目A\n- 条目B\n", encoding="utf-8")
        (r / "01-记忆档案" / "记忆工程" / "会话速读包.md").write_text(
            "# SP\n\n## ① 当前\n- 事项一\n- 事项二\n\n## ② 路径\n- 导航\n", encoding="utf-8")
        cases += 1
        txt = build(r, "L1:SessionStart")
        ok = ("事项一" in txt) and ("条目A" in txt) and ("L1:SessionStart" in txt) and ("库最后更新" in txt)
        print("[%s] 正常库 ⇒ 含红线/事项/接线/时戳" % ("PASS" if ok else "FAIL"))
        bad += 0 if ok else 1

        cases += 1
        empty = Path(td) / "empty"
        (empty / "01-记忆档案").mkdir(parents=True)
        t2 = build(empty, "")
        ok2 = ("N0" in t2) and ("未标注" in t2)
        print("[%s] 空库 ⇒ 不崩、标 N0 与未标注" % ("PASS" if ok2 else "FAIL"))
        bad += 0 if ok2 else 1

        cases += 1
        ok3 = len(build(r, "x").splitlines()) <= MAX_LINES + 1
        print("[%s] 行数上限 ≤%d" % ("PASS" if ok3 else "FAIL", MAX_LINES))
        bad += 0 if ok3 else 1

        # ★ 回归（2026-10-02 实测暴露）：带 frontmatter 的件 ⇒ 不得抓到 `key: value` 行
        cases += 1
        f2 = Path(td) / "fm"
        (f2 / "01-记忆档案").mkdir(parents=True)
        (f2 / "01-记忆档案" / "SOUL.md").write_text(
            "---\ntitle: \"SOUL\"\nsummary: \"x\"\nversion: \"0.1.0\"\n---\n\n"
            "# SOUL\n- 真红线甲\n- 真红线乙\n", encoding="utf-8")
        t3 = build(f2, "L1")
        ok4 = ("真红线甲" in t3) and ("title:" not in t3) and ("summary:" not in t3)
        print("[%s] 带 frontmatter ⇒ 取正文、不取 key:value" % ("PASS" if ok4 else "FAIL"))
        bad += 0 if ok4 else 1

        # ★ 回归（2026-10-02 · 承本机接入实测 · `0.1.15`）：任意层级标题不得进注入面
        cases += 1
        f3 = Path(td) / "hd"
        (f3 / "01-记忆档案").mkdir(parents=True)
        (f3 / "01-记忆档案" / "SOUL.md").write_text(
            "# SOUL\n- 真红线甲\n## 〇、节标题\n- 真红线乙\n### 子标题\n- 真红线丙\n",
            encoding="utf-8")
        t4 = build(f3, "L1")
        ok5 = ("真红线甲" in t4 and "真红线乙" in t4 and "真红线丙" in t4
               and "节标题" not in t4 and "子标题" not in t4)
        print("[%s] 任意层级标题 ⇒ 不进注入面" % ("PASS" if ok5 else "FAIL"))
        bad += 0 if ok5 else 1

        # ★ 回归（2026-10-02 · 承首见实测「问完不知道叫主人什么」）：称呼缺项须给安全默认
        cases += 1
        f4 = Path(td) / "callq"
        (f4 / "01-记忆档案").mkdir(parents=True)
        (f4 / "01-记忆档案" / "USER.md").write_text(
            "- **称呼**：待补 ｜ **代词**：待补\n", encoding="utf-8")
        t5 = build(f4, "L1")
        ok6 = ("主人称呼" in t5) and ("默认使用「你」" in t5)
        print("[%s] 称呼缺项 ⇒ 给安全默认（不空）" % ("PASS" if ok6 else "FAIL"))
        bad += 0 if ok6 else 1

        # ★ 回归（2026-10-02 · 承首见演练 A3）：称呼值须为**净词**（剥括注与引号）
        cases += 1
        f5 = Path(td) / "callq2"
        (f5 / "01-记忆档案").mkdir(parents=True)
        (f5 / "01-记忆档案" / "USER.md").write_text(
            '- **称呼**：**你**（主人选「直接说"你"就行」） ｜ **代词**：你\n', encoding="utf-8")
        t6 = build(f5, "L1")
        line = [x for x in t6.splitlines() if "主人称呼" in x]
        ok7 = (len(line) == 1) and (line[0].strip() == "- **主人称呼：你**")
        print("[%s] 称呼剥括注 ⇒ 注入面出净词" % ("PASS" if ok7 else "FAIL"))
        bad += 0 if ok7 else 1

        # ★ 回归（2026-10-02 · 承首见演练 A4）：红线应取「§一」段，而非文件头
        cases += 1
        f6 = Path(td) / "rl"
        (f6 / "01-记忆档案").mkdir(parents=True)
        (f6 / "01-记忆档案" / "SOUL.md").write_text(
            "# SOUL\n\n## 〇、新生儿态\n\n- 说明行一\n- 说明行二\n\n"
            "## 一、红线\n\n- 红线甲\n- 红线乙\n- 红线丙\n\n## 二、行为铁律\n\n`none`\n",
            encoding="utf-8")
        t7 = build(f6, "L1")
        ok8 = ("红线甲" in t7 and "红线乙" in t7 and "红线丙" in t7
               and "说明行一" not in t7)
        print("[%s] 红线取 §一 段（不取文件头）" % ("PASS" if ok8 else "FAIL"))
        bad += 0 if ok8 else 1

        # ★ 回归（2026-10-02 · 承首见演练 A4·N0 面）：§一 段为空（none）⇒ 出 N0 提示，**不得回落抓文件头**
        cases += 1
        f7 = Path(td) / "rl0"
        (f7 / "01-记忆档案").mkdir(parents=True)
        (f7 / "01-记忆档案" / "SOUL.md").write_text(
            "# SOUL\n\n## 〇、新生儿态\n\n- 说明行一\n\n## 一、红线\n\n`none`\n",
            encoding="utf-8")
        t8 = build(f7, "L1")
        ok9 = ("N0" in t8) and ("说明行一" not in t8)
        print("[%s] §一 空 ⇒ 出 N0 提示、不抓文件头" % ("PASS" if ok9 else "FAIL"))
        bad += 0 if ok9 else 1

    print("---- PASS %d / FAIL %d ----" % (cases - bad, bad))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--via", default="", help="接线标识，如 L1:SessionStart / L2:CLAUDE.md@import")
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.root:
        print("[ERR] 须给 --root <库根>")
        return 2
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root)
        return 2
    txt = build(root, a.via)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
        print("[OK] 已写 %s（%d 行 / %d 字符）" % (a.out, len(txt.splitlines()), len(txt)))
    else:
        sys.stdout.write(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())

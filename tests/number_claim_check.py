#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""J10 · 计数口径闸 —— 「凡报数必带口径／取证」。

【治什么】`J10`（判据层 `01-记忆档案/.learnings/ERRORS.md` §三）：
  凡报「N 条／N 处」⇒ **先声明口径**（token 数／去重实体数／分母窗口）并打印对照。
  2026-10-04 实证（落地率议题）：送审件随件复验卡 **6 个数中 4 个不可复现**
  —— 缺口径、缺取数时点、缺复跑命令。这是「判据在册、无退出码检查体」的典型
  ⇒ 本闸把 J10 做成**可机检**（承三方评审合并裁定 §五-5）。

【判据（客观可判）】逐行扫描：行内出现「数字 ＋ 量词」⇒ 该行须**同时**具备至少一项取证线索：
  a) 反引号包裹的命令或路径（`` `…` ``）
  b) 括号内出现口径词（口径／范围／单位／时点／去重／截至／分母／窗口）
  c) 行内显式标注 `[未核]`／`（待补）`／`待实测`
  ⇒ 三者皆无 ⇒ 记 1 处「裸报数」。

【不计（白名单）】标题行／表格结构与分隔行／HTML 注释／代码块内。

【★ 已知边界（诚实口径 · 不假装零误报）】**阈值／规格类声明**（如「本件自设上限 5,000 字符」）因缺取证线索，
  会被**判为裸报数** —— 这是**判据面偏宽**的已知项（加宽豁免会让「本轮共 8 处未处置（上限 10）」这类**真裸报数**逃逸，
  故**不加豁免**）。写法上把数字去掉（如「本件自设孔径上限」）即合规。｜由来：2026-10-04 本闸首跑**自己的速读包**时实测。
  **② 表格行（2026-10-04 改 · 承 DSH 回单「完工判据 2」）**：**不再整体豁免**，改为**按 `|` 切格逐格检**。
    由来：本闸上线同日，我自己的送审函里那处「白名单 48 件（**实 15**）」**正是写在表格里** ⇒ 整体豁免会让本闸
    **漏掉它自己的首个用例**（「闸逃逸自己的例子」）。折中＝逐格判（避免整行多数字互相掩护，也不整行豁免）。
    ⚠️ 代价仍明写：**表格格内的真裸报数现在会被检出**（这正是本次要的），但**同一格内含多个数字**时只记 1 处。
  **③ 自指／引述（2026-10-04 记）**：文档**谈自己**时的数字（如「本件 §一 共 **8 处**错」）与**引述他人原文**的数字，
    会被判为裸报数 —— 属**已知边界**，**故意不加豁免**（豁免会放走真裸报数）。按需在句内补取证，或明标 `[未核]`。

【载体定位】本闸 ＝ 判据层 `J10` 的**载体**（三格之「闸」：有退出码语义的检查体）。
  由 2026-10-04「落地率」议题三方评审合并裁定 **§五-5** 指定新做；登记见
  `12-运维管理/02_台账记录/规则承载点登记表.md` 段 `R-46`。

【退出码】0 全过 ｜ 1 有裸报数 ｜ 3 参数或 IO 错
【用法】`python tests/number_claim_check.py --file <件.md> [--json]` ｜ `--selftest`
"""
import argparse
import json
import re
import sys
from pathlib import Path

QUANT = r"(?:条|处|项|支|个|件|行|字符|字节|%|％|倍|次)"
NUMQ = re.compile(r"\d+(?:[.,]\d+)?\s*" + QUANT)
EVID = (
    re.compile(r"`[^`]+`"),
    re.compile(r"[（(][^）)]*(?:口径|范围|单位|时点|去重|截至|分母|窗口)[^）)]*[）)]"),
    re.compile(r"\[未核\]|（待补）|\(待补\)|待实测"),
    # ★ 2026-10-04 加（承 `J10` 与三方共识「数字须带**命令与时点**」）：**时点即取证** ——
    #   形如「（09:0x）」「（2026-10-04）」「（mtime 06:49）」等一律计为已取证。
    #   由来：本闸首轮自审时，v2 送审件里写满「（09:0x）」仍被判裸报数 ⇒ **判据未跟上规矩**（`E551` 族）。
    re.compile(r"[（(][^）)]*(?:\d{1,2}:[0-9x]{1,2}|\d{4}-\d{2}-\d{2}|mtime)[^）)]*[）)]"),
)
SKIP = re.compile(r"^\s*(#{1,6}\s|\||<!--)")   # ★ 表格行**整体**豁免（含数据行）—— 见 docstring「已知边界」


def scan(path: Path):
    """返回 [(行号, 行内容截断), ...]，每项＝一处「裸报数」。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.lstrip().startswith("|"):
            # ★ 2026-10-04 改（承 DSH 回单「完工判据 2」）：**表格行不再整体豁免，改为逐格检**。
            #   由来：本闸上线同日，我自己的送审函里那处「白名单 48 件（实 15）」**正是写在表格里**
            #   ⇒ 整体豁免会让本闸**漏掉它自己的首个用例**（「闸逃逸自己的例子」）。
            #   折中：按 `|` 切格**逐格**判 —— 避免整行多数字互相"掩护"，也不整行豁免。
            for _c in line.split("|"):
                if NUMQ.search(_c) and not any(p.search(_c) for p in EVID):
                    hits.append((i, _c.strip()[:120]))
            continue
        if SKIP.match(line):
            continue
        if not NUMQ.search(line):
            continue
        if any(p.search(line) for p in EVID):
            continue
        hits.append((i, line.strip()[:120]))
    return hits


def selftest() -> int:
    import tempfile
    cases = []
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        def w(name, txt):
            p = d / name
            p.write_text(txt, encoding="utf-8")
            return p

        f = w("a.md", "本轮共 8 处未处置。\n")
        cases.append(("【必红】裸报数（8 处 · 无口径）计 1", len(scan(f)) == 1))
        f = w("b.md", "本轮共 8 处未处置（口径＝命中行数 ｜ 范围＝12-运维管理 ｜ 时点＝10-04 06:2x）。\n")
        cases.append(("应绿·带口径三元组", len(scan(f)) == 0))
        f = w("c.md", "`grep -c foo f` ⇒ 6 条。\n")
        cases.append(("应绿·带取证命令（反引号）", len(scan(f)) == 0))
        f = w("d.md", "待补：12 项（[未核]）。\n")
        cases.append(("应绿·显式标 [未核]", len(scan(f)) == 0))
        f = w("e.md", "```\n共 3 处\n```\n本件共 3 处。\n")
        cases.append(("【必红】代码块内不计 · 块外裸报数计 1", len(scan(f)) == 1))
        f = w("f.md", "| a | b |\n|---|---|\n")
        cases.append(("应绿·表格结构行不计", len(scan(f)) == 0))
        f = w("g.md", "结论：20 条判据里 2 条挂闸（分母＝20 · 口径＝代码引用 · 时点＝10-04）。\n")
        cases.append(("应绿·结论句带分母与口径", len(scan(f)) == 0))
    ok = True
    for name, r in cases:
        print("  [%s] %s" % ("OK" if r else "FAIL", name))
        ok = ok and r
    print("== selftest %s（%d 态）==" % ("全绿" if ok else "有红", len(cases)))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="待检件（.md）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="六态自检（含两条**必红**例）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.file:
        print("[FAIL] 需 --file 或 --selftest")
        return 3
    p = Path(a.file)
    if not p.is_file():
        print("[FAIL] 件不存在：%s" % p)
        return 3
    hits = scan(p)
    if a.json:
        print(json.dumps({"file": str(p), "bare_claims": len(hits),
                          "items": [{"line": n, "text": t} for n, t in hits]},
                         ensure_ascii=False, indent=2))
    else:
        print("-- J10 计数口径闸 ｜ %s" % p)
        for ln, t in hits:
            print("   L%-5d %s" % (ln, t))
        print("-- 裸报数 **%d 处**（口径＝行级扫描 · 量词表 %s…）%s"
              % (len(hits), QUANT[:12], "（全过）" if not hits else " ⇒ 须补口径／取证，或标 [未核]"))
    return 0 if not hits else 1


# ★ 输出编码治本（承 gates_selftest.py 同款）：中文 Windows 控制台默认 GBK
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

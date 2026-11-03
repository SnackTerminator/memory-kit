#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力闸 —— 回答一个 33 个版本都没回答过的问题：**检索有没有变差？**

## 它是什么 / 不是什么（先划边界，防误读）

**是**：**检索能力回归闸** —— 给定一批「已知存在于本库」的问题，看 `memory ask`
（BM25 倒排）能不能在 top-5 里把**那条记忆**翻出来。指标 `Hit@5` 与 `MRR`（名次倒数）。

**不是**：① **不是记忆质量评测** —— 它测「找得到吗」，不测「记是对的/有用的吗」
② **不是语义理解评测** —— 零 LLM judge，纯串/路径比对（承 `07_评测壳` 的 `烟测_C0` 口径）
③ **不对外报排名** —— 承已否决 §一·6「拿外部 SOTA 分数当我方标尺」；
   本闸只用于**自身版本间比较**（同一台秤，称不同版本）。

## 两种模式

| 模式 | 用法 | 题从哪来 | 适用 |
|---|---|---|---|
| `--suite` | 内置 20 题（`SUITE`） | **针对本项目库**的人工题集 | 作者侧回归（本仓） |
| `--auto N` | 自动抽题 | 从库里扫标题行，取实词作 query，**期望命中该件** | 任意用户的库（通用） |

★ **`--auto` 的诚实边界**：query 取自条目本身的词 ⇒ 天然容易命中 ⇒ 它测的是
「**索引与检索的自洽性**」（文件收进来了吗、分词对吗、排序对吗），**不是**「懂不懂人话」。
拿它当"能力很强"的证据是错的；拿它当"索引没坏"的回归信号是对的。

## 用法

  python tests/bench_memory.py --root <库根>
  python tests/bench_memory.py --root <库根> --auto 20
  python tests/bench_memory.py --root <库根> --json
  python tests/bench_memory.py --root <库根> --write-baseline _run/bench_baseline.json
  python tests/bench_memory.py --root <库根> --compare _run/bench_baseline.json   # MRR 暗降即红
  python tests/bench_memory.py --selftest

退出码：0 达标 ｜ 1 退化/不达标 ｜ 3 参数/IO 错
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CJK = re.compile(r"[\u4e00-\u9fff]")
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]{2,}")

# ── 内置题集（针对本仓库根 · as-of 2026-10-25）──────────────────────────────
# 每题：(id, 组, q, expect)。组有两种，**必须分开报数**（否则一个混合数字既说不出
# 「检索准不准」也看不出「检索面够不够」）：
#   mem  ＝ 期望命中 `01-记忆档案/` 内的记忆件 —— 测**检索能力**
#   spec ＝ 期望命中 `spec/`／`docs/`／`AGENTS.md`／`MANIFEST.md` 等规程件 —— 测**检索覆盖面**
# ★ 2026-10-25 实测发现：`kitmeta.ARCHIVE_DIR = "01-记忆档案"` ⇒ **检索面只到记忆面**，
#   规程件**结构性检索不到**。这不是题库问题，是覆盖面缺口（记入建议件第 7 条候选）。
# 选材原则：① 库里真实存在 ② 问句不用条目原名（用同义表达）⇒ 有区分度
SUITE = [
    ("M01", "mem", "数字必须写出来源，不能凭印象", ["SOUL.md"]),
    ("M02", "mem", "节约不是省成本，是一次做好不返工", ["SOUL.md"]),
    ("M03", "mem", "聪明不等于什么都会，先查再答", ["SOUL.md", "IDENTITY"]),
    ("M04", "mem", "话里带分辨对象时先定对象再动手", ["SOUL.md"]),
    ("M05", "mem", "当前在做什么、还有什么没做完", ["会话速读包"]),
    ("M06", "mem", "上一阶段闭合了哪些事项", ["已完成台账", "速读包"]),
    ("M07", "mem", "主人的称呼与语言习惯", ["USER.md"]),
    ("S01", "spec", "删除要优先于回滚，三个状态", ["本库内删除可复核"]),
    ("S02", "spec", "网盘能不能当载体，有什么代价", ["MANIFEST"]),
    ("S03", "spec", "候选清单用什么分隔符喂给整理层", ["记忆形成与容量治理"]),
    ("S04", "spec", "状态、事件、记忆三层，谁能点头写入", ["记忆形成与容量治理"]),
    ("S05", "spec", "带走之前怎么自检有没有走失", ["carry_check"]),
    ("S06", "spec", "开机注入的那段摘要怎么生成", ["digest"]),
    ("S07", "spec", "私人关键词表怎么用", ["私词表"]),
    ("S08", "spec", "白名单是什么，多一个件会怎样", ["发行物清单"]),
    ("S09", "spec", "换机器怎么认出是同一台", ["CONTRACT"]),
    ("S10", "spec", "接进一个新宿主要做哪几步", ["接入卡"]),
    ("S11", "spec", "换了设备第一件事做什么", ["接上我"]),
    ("S12", "spec", "入口件说唯一动作是什么", ["AGENTS.md"]),
    ("S13", "spec", "开局必须按顺序读哪几件", ["MANIFEST"]),
]


def _ask(root: Path, q: str, top_k: int) -> list:
    """调真实 CLI 面（不 import，确保测的是用户实际会用的那条路）。"""
    cmd = [sys.executable, "-B", str(TOOLS / "memory.py"),
           "--root", str(root), "--json", "ask", q, "--top-k", str(top_k)]
    cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not (cp.stdout or "").strip():
        return []
    try:
        return json.loads(cp.stdout).get("hits", []) or []
    except json.JSONDecodeError:
        return []


def _hit_rank(hits, expect) -> int:
    """返回首个命中期望的 1-based 名次；未命中返回 0。"""
    for i, h in enumerate(hits, 1):
        p = h.get("path", "")
        if any(e in p for e in expect):
            return i
    return 0


def auto_suite(root: Path, n: int):
    """从库里自动抽题：标题行 → 实词 → query；期望命中**该文件**。"""
    items = []
    for dp, dns, fns in os.walk(root / "01-记忆档案"):
        dns[:] = [d for d in dns if not d.startswith("_") and d != "__pycache__"]
        for fn in sorted(fns):
            if not fn.endswith(".md"):
                continue
            p = Path(dp) / fn
            rel = str(p.relative_to(root)).replace("\\", "/")
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for ln in lines:
                if not ln.startswith("#"):
                    continue
                # 抽词：连续汉字切 2-gram（与 tokenize 的单字+二元组口径一致）＋ 英文词
                words = []
                for seg in re.findall(r"[\u4e00-\u9fff]{2,}", ln):
                    words += [seg[i:i + 2] for i in range(len(seg) - 1)] if len(seg) > 2 else [seg]
                words += WORD.findall(ln)
                words = [w for w in words if len(w) >= 2][:4]
                if words:
                    items.append((rel.split("/")[-1][:12], " ".join(words), [rel]))
                    break
            if len(items) >= n:
                return items
    return items


def run(root: Path, suite, top_k: int, quiet=False):
    """跑题集，返回 (rows, hit, mrr, 分组统计)。兼容 3 元组（auto）与 4 元组（带组名）。"""
    rows = []
    for item in suite:
        if len(item) == 4:
            sid, grp, q, expect = item
        else:
            sid, q, expect = item
            grp = "auto"
        hits = _ask(root, q, top_k)
        r = _hit_rank(hits, expect)
        rows.append({"id": sid, "grp": grp, "q": q, "expect": expect, "rank": r,
                     "top1": hits[0].get("path") if hits else None, "n_hits": len(hits)})
        if not quiet:
            mark = "✓" if r else "✗"
            print(f"  {mark} {sid}[{grp}] 名次 {r or '—'}  「{q[:30]}」→ {(rows[-1]['top1'] or '无命中')[:44]}")

    def _stat(rs):
        n = len(rs) or 1
        return (round(sum(1 for x in rs if x["rank"]) / n, 4),
                round(sum(1.0 / x["rank"] for x in rs if x["rank"]) / n, 4))

    groups = {}
    for g in sorted(set(x["grp"] for x in rows)):
        groups[g] = _stat([x for x in rows if x["grp"] == g])
    h, m = _stat(rows)
    return rows, h, m, groups


def selftest() -> int:
    """夹具：造 3 件 → 自动抽题 → 三条都应命中；再删一件 → 应出现未命中。"""
    import shutil
    import tempfile
    fails = 0
    td = Path(tempfile.mkdtemp(prefix="bench_"))
    try:
        base = td / "01-记忆档案"
        base.mkdir(parents=True)
        (base / "甲.md").write_text("# 载体选择与代价\n\n网盘可以作载体，但会上云。\n", encoding="utf-8")
        (base / "乙.md").write_text("# 删除可复核\n\n删除前先预告，恢复者当场重放。\n", encoding="utf-8")
        (base / "丙.md").write_text("# 机位识别\n\n换机器要取 machine_id。\n", encoding="utf-8")
        suite = auto_suite(td, 3)
        ok1 = len(suite) >= 3
        print(f"  态1 自动抽题 ≥3 条     → {'PASS' if ok1 else 'FAIL'}（实抽 {len(suite)}）")
        fails += 0 if ok1 else 1
        rows, h, m, _g = run(td, suite, 5, quiet=True)
        ok2 = h >= 0.6
        print(f"  态2 检索命中率 ≥0.6     → {'PASS' if ok2 else 'FAIL'}（Hit={h} MRR={m}）")
        fails += 0 if ok2 else 1
        # 态 3：写坏的索引不应崩（删掉索引目录后应能重建）
        idx = td / "08-检索索引"
        if idx.is_dir():
            shutil.rmtree(idx, ignore_errors=True)
        rows2, h2, _m2, _g2 = run(td, suite, 5, quiet=True)
        ok3 = h2 >= 0.6
        print(f"  态3 索引缺失可重建      → {'PASS' if ok3 else 'FAIL'}（Hit={h2}）")
        fails += 0 if ok3 else 1
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print(f"== 结果：{'全绿' if not fails else f'失败 {fails} 项'}（3 态）")
    return 0 if not fails else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--auto", type=int, default=0, help="自动抽 N 题（通用模式）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-baseline")
    ap.add_argument("--compare")
    ap.add_argument("--min-mrr", type=float, default=0.0, help="MRR 下限（默认只报数不判死）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    if not a.root:
        print("[FAIL] 需要 --root（或用 --selftest）")
        return 3
    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"[FAIL] 库目录不存在：{root}")
        return 3

    suite = auto_suite(root, a.auto) if a.auto else SUITE
    if not suite:
        print("[FAIL] 抽不到题（该库 01-记忆档案 下无可用标题）")
        return 3

    print(f"==== 能力闸（检索回归）｜ 库根 {root}")
    print(f"-- 点名观察对象：题 {len(suite)} 条 ｜ top-k {a.top_k} ｜ 判据＝零 LLM judge，路径串比对")
    rows, h, m, groups = run(root, suite, a.top_k, quiet=a.json)
    print(f"==== 合计 Hit@{a.top_k} **{h:.2%}** ｜ MRR **{m:.4f}** ｜ 题 {len(rows)} 条")
    for g, (gh, gm) in groups.items():
        n = sum(1 for x in rows if x["grp"] == g)
        label = {"mem": "记忆面（测检索能力）", "spec": "规程面（测检索覆盖面）",
                 "auto": "自动抽题"}.get(g, g)
        print(f"-- {g:4s} {label} 题 {n:2d} → Hit **{gh:.2%}** ｜ MRR **{gm:.4f}**")

    if a.json:
        print(json.dumps({"root": str(root), "n": len(rows), "top_k": a.top_k,
                          "hit_rate": h, "mrr": m,
                          "groups": {g: {"hit_rate": v[0], "mrr": v[1]} for g, v in groups.items()},
                          "rows": rows}, ensure_ascii=False))
    if a.write_baseline:
        p = Path(a.write_baseline)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"hit_rate": h, "mrr": m, "top_k": a.top_k, "n": len(rows)},
                                ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-- 已写基线：{p}")

    rc = 0
    if a.compare:
        try:
            b = json.loads(Path(a.compare).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[FAIL] 读不到基线：{e}")
            return 3
        print(f"-- 对比基线：Hit {b.get('hit_rate')} → {h} ｜ MRR {b.get('mrr')} → {m}")
        if m + 1e-9 < float(b.get("mrr", 0)):
            print("  [RED] MRR **暗降** ⇒ 判退化（允许持平，不允许变差）")
            rc = 1
        else:
            print("  [OK] 未退化")
    if a.min_mrr and m < a.min_mrr:
        print(f"  [RED] MRR {m} < 下限 {a.min_mrr}")
        rc = 1
    print("==== 结论：" + ("✅ 达标" if rc == 0 else "❌ 未达标（见上）"))
    return rc


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

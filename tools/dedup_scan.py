#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸④·a 合并闸（去重 · 同族候选）—— 设计件 §6.1。

判据（客观可判）：按 `family` 字段分组，**同族 ≥2 条 ⇒ 报为蒸馏候选**（附处置建议「合并／蒸馏」）。
**不自动合并** —— 蒸馏须人/AI 显式动作（且须留可回溯指针，见 `pointer_check.py`）。

**边界**：本脚本**只读＋判**，**一律不改库**。

用法：
  python tools/dedup_scan.py --root <库根> [--min N]
  python tools/dedup_scan.py --selftest        # 三态自检

退出码：0 无候选 ｜ 5 **有蒸馏候选**（待人工判定）｜ 3 参数/IO 错
"""
import argparse
import sys
sys.dont_write_bytecode = True  # ★ 保证「代码根只读」：禁写字节码（须在 import kitmeta 之前）—— 治 E631
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitmeta  # noqa: E402


def collect(root: Path, min_n: int = 2):
    """返回 (候选清单, 无族条目数, 观察串)。候选＝(族名, [相对路径…])。"""
    fams, nofam = {}, 0
    for _p, rel, meta, _body in kitmeta.iter_l2(root):
        fam = str(meta.get("family", "")).strip()
        if not fam:
            nofam += 1
            continue
        fams.setdefault(fam, []).append(rel)
    cands = sorted([(f, sorted(v)) for f, v in fams.items() if len(v) >= min_n])
    obs = (f"同族统计：族 {len(fams)} 个 ｜ 候选族 {len(cands)} 个（阈值 ≥{min_n}）"
           f" ｜ 无 family 字段 {nofam} 件（不参与去重）")
    return cands, nofam, obs


def selftest() -> int:
    print("== selftest（三态）==")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / "01-记忆档案"
        d.mkdir(parents=True)
        (d / "a1.md").write_text("---\nlayer: L2\nfamily: 成本\n---\nx\n", encoding="utf-8")
        (d / "a2.md").write_text("---\nlayer: L2\nfamily: 成本\n---\ny\n", encoding="utf-8")
        (d / "b1.md").write_text("---\nlayer: L2\nfamily: 排版\n---\nz\n", encoding="utf-8")
        (d / "c1.md").write_text("---\nlayer: L2\n---\n无族\n", encoding="utf-8")
        c1, nofam1, _ = collect(root, min_n=2)
        # 态2：提高阈值 ⇒ 无候选
        c2, _n2, _ = collect(root, min_n=3)

    cases = [
        ("态1 同族 ≥2 应报候选", len(c1) == 1 and c1[0][0] == "成本" and len(c1[0][1]) == 2),
        ("态2 同族 <N 免蒸（阈值 3）", c2 == []),
        ("态3 无 family 字段不计入候选", nofam1 == 1),
    ]
    ok = True
    for name, res in cases:
        print(f"  [{'OK' if res else 'FAIL'}] {name}")
        ok = ok and res
    print(f"== selftest {'全绿' if ok else '有红'}（{len(cases)} 态）==")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--min", type=int, default=2, help="同族条数阈值（默认 2）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        print(f"[FAIL] 库根不存在：{root}")
        return 3

    cands, _nofam, obs = collect(root, min_n=a.min)
    print(f"-- 点名观察对象：{obs}")
    for fam, rels in cands:
        print(f"[候选] 族「{fam}」{len(rels)} 条 ⇒ 建议**合并或蒸馏**（须留可回溯指针）：")
        for r in rels:
            print(f"        - {r}")
    if cands:
        print("== 闸④·a 有待判候选（**人工/AI 显式动作**；本闸不自动合并）==")
        return 5
    print("[OK] 闸④·a 合并闸通过（无蒸馏候选）")
    return 0


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

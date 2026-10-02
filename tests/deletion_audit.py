#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`purge audit` 的**验收薄壳**（三件之三 · 对外的核验入口）。

**为什么是薄壳**（v1.1 决策）：v1 曾有**两个重叠入口**（本件 vs `purge audit`）⇒ 合并为
**一套实现 ＋ 一层验收包装**：核验逻辑**唯一实现在 `tools/purge.py`**，本件只做
① 转调 ② **验收判定**（三类面统计 ＋ 边界四要素在场 ＋ 退出码归一）③ 交付/CI 可直接跑。

用法
  python tests/deletion_audit.py --root <库根> [--target <相对路径>]

退出码：0 通过 ｜ 1 **有残留或验收项缺** ｜ 3 参数/IO 错
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
PURGE = TOOLS / "purge.py"
BOUNDARY_KEYS = ("本库根", "逻辑删除", "不含库外与宿主侧", "自存证")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--target", default="")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root); return 3
    if not PURGE.is_file():
        print("[ERR] 取不到核验实现 `%s`" % PURGE); return 3

    cmd = [sys.executable, "-B", str(PURGE), "audit", "--root", str(root)]
    if a.target:
        cmd += ["--target", a.target]
    cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (cp.stdout or "") + (cp.stderr or "")
    print(out.rstrip())

    missing = [k for k in BOUNDARY_KEYS if k not in out]
    checks = []
    checks.append(("核验实现可执行（rc ∈ {0,1}）", cp.returncode in (0, 1), "rc=%d" % cp.returncode))
    checks.append(("**边界四要素在场**（D6）", not missing, "缺 %s" % missing))
    checks.append(("无静默（输出非空）", len(out.strip()) > 0, ""))

    bad = [n for n, ok, _ in checks if not ok]
    print("\n==== deletion_audit 验收")
    for n, ok, note in checks:
        print("   [%s] %s%s" % ("OK" if ok else "FAIL", n, ("  ← " + note) if (note and not ok) else ""))
    if bad or cp.returncode != 0:
        print("==== 结论：**未通过**（残留或验收项缺）")
        return 1
    print("==== 结论：通过（本库根内不可达 ＋ 边界在场）")
    return 0


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

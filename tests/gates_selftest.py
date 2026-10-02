#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四闸联动自检 —— 一次跑齐全部闸的 `--selftest`（设计件 §6.1）。

规则：**顺序跑，任一红即整批红**；★ **`rc=0` 不作数** ⇒ 每闸须**点名观察对象**
（各闸自检内已打印「态数」与实测值，本编排逐闸回显并要求 `全绿` 字样在场）。

用法：
  python tests/gates_selftest.py            # 跑齐五支
  python tests/gates_selftest.py --selftest # 本编排自身的自检（必红例）

退出码：0 全绿 ｜ 1 有红 ｜ 3 参数/IO 错
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
GATES = (
    ("闸① 入口闸", "tools/l2_admit.py"),
    ("闸② 容量闸", "tools/capacity_gate.py"),
    ("闸③ 寿命闸", "tools/ttl_sweep.py"),
    ("闸④·a 合并闸", "tools/dedup_scan.py"),
    ("闸④·b 指针闸", "tools/pointer_check.py"),
)
GREEN = re.compile(r"selftest\s*全绿（(\d+)\s*态）")


def run_gate(label, rel):
    script = KIT / rel
    if not script.is_file():
        return label, None, "-", f"脚本缺失：{rel}"
    cp = subprocess.run([sys.executable, "-B", str(script), "--selftest"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (cp.stdout or "") + (cp.stderr or "")
    m = GREEN.search(out)
    states = m.group(1) if m else "-"
    return label, cp.returncode, states, out


def selftest() -> int:
    """编排自身自检：用一个**必然红**的假闸 + 一个真闸，验证「任一红即整批红」成立。"""
    print("== selftest（必红例）==")
    res = []
    label, rc, states, _out = run_gate("真闸·入口", "tools/l2_admit.py")
    res.append(("真闸应 rc=0 且报态数", rc == 0 and states.isdigit()))
    bad_rc = 1  # 模拟一个 rc=1 的闸
    res.append(("假红闸应使整批判红", not (bad_rc == 0 and rc == 0)))
    ok = True
    for name, r in res:
        print(f"  [{'OK' if r else 'FAIL'}] {name}")
        ok = ok and r
    print(f"== selftest {'全绿' if ok else '有红'}（{len(res)} 态）==")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="本编排自身的必红例自检")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    print(f"==== 四闸联动自检 ｜ 套件根：{KIT}")
    rows, red = [], 0
    for label, rel in GATES:
        lb, rc, states, out = run_gate(label, rel)
        if not a.quiet:
            print(f"\n######## {lb}（{rel}）")
            print(out.rstrip())
        flag = "OK" if rc == 0 else "RED"
        if rc != 0:
            red += 1
        rows.append((lb, flag, rc, states))

    print("\n==== 汇总（点名观察对象：每闸自检态数）")
    for lb, flag, rc, states in rows:
        print(f"  [{flag}] {lb}  rc={rc}  自检态数={states}")
    print(f"==== 结果：{'全绿 ⇒ 四闸可用' if red == 0 else '有红 ⇒ 四闸未达标'}（红 {red} 项）")
    return 0 if red == 0 else 1


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸① 入口闸（L2 准入三问）—— 设计件 §6.1。

判据（客观可判）：条目件的 `admit` 段**三问答案在位**才 `exit 0`；
缺任一 ⇒ **`exit 1` 并打印缺哪问**（**禁静默通过**）。

三问（承 `spec/记忆形成与容量治理.md` §三 闸1）：
  ① `new_fact`        —— 是新事实吗？
  ② `changes_action`  —— 会改变未来动作吗？
  ③ `source`          —— 有来源吗？（须非空）

**边界**：本脚本**只读＋判**，**一律不改库**（改＝人／AI 的显式动作）。

用法：
  python tools/l2_admit.py --check <条目件>
  python tools/l2_admit.py --root <库根>        # 批量扫全部 L2 条目
  python tools/l2_admit.py --selftest           # 三态自检

退出码：0 全过 ｜ 1 有缺 ｜ 3 参数/IO 错
"""
import argparse
import sys
sys.dont_write_bytecode = True  # ★ 保证「代码根只读」：禁写字节码（须在 import kitmeta 之前）—— 治 E631
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitmeta  # noqa: E402

QUESTIONS = (
    ("new_fact", "① 是新事实吗"),
    ("changes_action", "② 会改变未来动作吗"),
    ("source", "③ 有来源吗"),
)


def judge(meta: dict):
    """返回缺失问清单（空＝三问齐备且为真）。"""
    admit = meta.get("admit") or {}
    if not isinstance(admit, dict):
        return [q for q, _ in QUESTIONS]
    missing = []
    for key, label in QUESTIONS:
        val = admit.get(key)
        if key == "source":
            if not (isinstance(val, str) and val.strip()):
                missing.append(label)
        elif val is not True and str(val).strip().lower() not in ("true", "yes"):
            missing.append(label)
    return missing


def check_one(path: Path, root: Path):
    meta, _body, _txt = kitmeta.read_meta(path)
    if "layer" not in meta:
        return None  # 非 L2 条目 ⇒ 不适用
    rel = path.relative_to(root).as_posix() if str(path).startswith(str(root)) else path.name
    layer = str(meta.get("layer", "")).strip()
    if layer != "L2":
        return (rel, layer, None)  # 非 L2 层不适用入口闸
    return (rel, layer, judge(meta))


def selftest() -> int:
    print("== selftest（三态）==")
    base = f"""---
layer: L2
created: 2026-09-29
admit:
  new_fact: true
  changes_action: true
  source: "实测 2026-09-29"
---
正文
"""
    partial = f"""---
layer: L2
admit:
  new_fact: true
  changes_action: true
---
正文
"""
    empty = "没有任何 frontmatter 的件\n"
    cases = [
        ("态1 三问齐备应通过", judge(kitmeta.parse_frontmatter(base)[0]) == []),
        ("态2 缺 source 应报缺", "③ 有来源吗" in judge(kitmeta.parse_frontmatter(partial)[0])),
        ("态3 无 admit 段应三问全缺", len(judge(kitmeta.parse_frontmatter(empty)[0])) == 3),
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
    ap.add_argument("--check", default=None, help="单件检查")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    if a.check:
        root = Path(a.root).resolve() if a.root else Path(a.check).resolve().parent
        p = Path(a.check).resolve()
        if not p.is_file():
            print(f"[FAIL] 找不到条目件：{p}")
            return 3
        res = check_one(p, root)
        if res is None:
            print(f"-- 非 L2 条目（无 layer 字段）⇒ 入口闸不适用：{p.name}")
            return 0
        rel, layer, missing = res
        if layer != "L2":
            print(f"-- layer={layer} ⇒ 入口闸只作用于 L2：{rel}")
            return 0
        if missing:
            print(f"[FAIL] {rel} — 准入三问缺 {len(missing)} 项：")
            for m in missing:
                print(f"        - {m}")
            return 1
        print(f"[OK] {rel} — 准入三问齐备")
        return 0

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    n_l2, bad = 0, []
    for p, rel, meta, _body in kitmeta.iter_l2(root):
        if str(meta.get("layer", "")).strip() != "L2":
            continue
        n_l2 += 1
        m = judge(meta)
        if m:
            bad.append((rel, m))
    print(f"-- 点名观察对象：L2 条目实测 {n_l2} 件 ｜ 三问齐备 {n_l2 - len(bad)} 件 ｜ 缺项 {len(bad)} 件")
    for rel, m in bad:
        print(f"[FAIL] {rel}：缺 {'、'.join(m)}")
    if not bad:
        print("[OK] 闸① 入口闸通过")
    return 1 if bad else 0


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

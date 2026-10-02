#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸④·b 指针闸（蒸馏后可回溯）—— 设计件 §6.1。

判据（客观可判）：凡标 `deprecated: true` 的条目，**必须带 `superseded_by` 指向新条**，
且该目标**存在**；**指针在位率须 100%**，缺 ⇒ **`exit 4`**。

**边界**：本脚本**只读＋判**，**一律不改库**。

用法：
  python tools/pointer_check.py --root <库根>
  python tools/pointer_check.py --selftest     # 三态自检

退出码：0 指针全在位 ｜ 4 有缺指针 ｜ 3 参数/IO 错
"""
import argparse
import sys
sys.dont_write_bytecode = True  # ★ 保证「代码根只读」：禁写字节码（须在 import kitmeta 之前）—— 治 E631
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitmeta  # noqa: E402


def collect(root: Path):
    """返回 (缺指针清单, 已废弃条目列表, 观察串)。"""
    index, deprecated = set(), []
    for _p, rel, meta, _body in kitmeta.iter_l2(root):
        index.add(rel)
        if meta.get("deprecated") is True or str(meta.get("deprecated", "")).lower() in ("true", "yes"):
            deprecated.append((rel, str(meta.get("superseded_by", "")).strip()))

    missing = []
    for rel, target in deprecated:
        if not target:
            missing.append((rel, "缺 `superseded_by` 字段"))
        else:
            norm_target = target.lstrip("./").replace("\\", "/")
            if norm_target not in index and not (root / norm_target).exists():
                missing.append((rel, f"指针目标不存在：{target}"))
    rate = 100.0 if not deprecated else round(100.0 * (len(deprecated) - len(missing)) / len(deprecated), 1)
    obs = f"已废弃条目 {len(deprecated)} ｜ 缺指针 {len(missing)} ｜ **指针在位率 {rate}%**（须 100%）"
    return missing, deprecated, obs


def selftest() -> int:
    print("== selftest（三态）==")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / "01-记忆档案"
        d.mkdir(parents=True)
        (d / "new.md").write_text("---\nlayer: L2\n---\n新条\n", encoding="utf-8")
        # 态1：有指针且目标存在
        (d / "old1.md").write_text(
            "---\nlayer: L2\ndeprecated: true\nsuperseded_by: 01-记忆档案/new.md\n---\n旧条\n",
            encoding="utf-8")
        m1, dep1, obs1 = collect(root)
        # 态2：缺指针字段
        (d / "old2.md").write_text("---\nlayer: L2\ndeprecated: true\n---\n旧条2\n", encoding="utf-8")
        m2, dep2, _ = collect(root)
        # 态3：指针目标不存在
        (d / "old3.md").write_text(
            "---\nlayer: L2\ndeprecated: true\nsuperseded_by: 01-记忆档案/不存在.md\n---\n旧条3\n",
            encoding="utf-8")
        m3, dep3, _ = collect(root)

    cases = [
        ("态1 有指针且目标存在 ⇒ 零缺", m1 == [] and len(dep1) == 1 and "100.0%" in obs1),
        ("态2 缺 superseded_by 应检出", len(m2) == 1 and "缺 `superseded_by`" in m2[0][1]),
        ("态3 指针目标不存在应检出", len(m3) == 2 and any("不存在" in x[1] for x in m3)),
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
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        print(f"[FAIL] 库根不存在：{root}")
        return 3

    missing, _dep, obs = collect(root)
    print(f"-- 点名观察对象：{obs}")
    for rel, why in missing:
        print(f"[FAIL] {rel}：{why}")
    if missing:
        print("== 闸④·b 指针闸未通过（蒸馏须可回溯 · 承 R-30 降级保一致性）==")
        return 4
    print("[OK] 闸④·b 指针闸通过（指针在位率 100%）")
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

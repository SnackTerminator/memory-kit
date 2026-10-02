#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸② 容量闸（硬顶）—— 设计件 §6.1。

判据（客观可判）：读各层上限（`kit.conf`，缺则内置默认）⇒ 比对**实测**条数／体积。
  **触顶 ⇒ `exit 3` ＋ 输出「须降冷或合并」**。
★ **脚本内无"自动扩上限"分支** —— 这是「**机器禁自动扩、用户须显式改配置**」的**代码级保证**。

**边界**：本脚本**只读＋判**，**一律不改库**。

用法：
  python tools/capacity_gate.py --root <库根>
  python tools/capacity_gate.py --selftest      # 三态自检

退出码：0 未触顶 ｜ 3 触顶 ｜ 4 上限缺失/配置错
"""
import argparse
import sys
sys.dont_write_bytecode = True  # ★ 保证「代码根只读」：禁写字节码（须在 import kitmeta 之前）—— 治 E631
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitmeta  # noqa: E402


def measure(root: Path):
    """返回 (条数, [(相对路径, 字符数)], conf, conf_src)。"""
    items = []
    for p, rel, _meta, body in kitmeta.iter_l2(root):
        items.append((rel, len(body)))
    conf, src = kitmeta.load_conf(root)
    return items, conf, src


def evaluate(items, conf):
    """返回 (触顶列表, 观察串)。触顶项＝(名称, 实测, 上限, 处置建议)。"""
    hits = []
    max_items = int(conf.get("L2_MAX_ITEMS", kitmeta.DEFAULTS["L2_MAX_ITEMS"]))
    max_chars = int(conf.get("L2_MAX_CHARS", kitmeta.DEFAULTS["L2_MAX_CHARS"]))

    n = len(items)
    if max_items > 0 and n > max_items:
        hits.append(("L2 条目总数", n, max_items, "须降冷或合并"))
    for rel, size in items:
        if max_chars > 0 and size > max_chars:
            hits.append((rel, size, max_chars, "须蒸馏或拆分"))
    obs = f"L2 条目 {n} / 上限 {max_items} ｜ 单件上限 {max_chars} 字符 ｜ 超限件 {len(hits)}"
    return hits, obs


def _mutates_limit(src: str) -> bool:
    """AST 静态断言：源码中是否存在对**上限常量**的自增／赋值（＝"自动扩"的代码形态）。"""
    import ast
    limits = {"L2_MAX_ITEMS", "L2_MAX_CHARS", "TTL_DEFAULT_DAYS"}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                and node.target.id in limits:
            return True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in limits:
                    return True
    return False


def selftest() -> int:
    print("== selftest（三态 ＋ 双保证）==")
    items_ok = [("a.md", 100), ("b.md", 200)]
    items_over = [("a.md", 100)] * 4
    conf_ok = {"L2_MAX_ITEMS": 10, "L2_MAX_CHARS": 1000}
    conf_low = {"L2_MAX_ITEMS": 2, "L2_MAX_CHARS": 1000}
    conf_missing = {"L2_MAX_CHARS": 1000}  # 缺 L2_MAX_ITEMS ⇒ 走默认

    h1, _ = evaluate(items_ok, conf_ok)
    frozen = dict(conf_low)
    h2, _ = evaluate(items_over, conf_low)
    h3, _ = evaluate(items_ok, conf_missing)

    src = Path(__file__).read_text(encoding="utf-8")
    no_grow_code = not _mutates_limit(src)          # 静态：无"改上限"语句
    conf_readonly = conf_low == frozen              # 行为：判定不改上限

    cases = [
        ("态1 未触顶应无命中", h1 == []),
        ("态2 触顶应命中并给处置建议", len(h2) == 1 and h2[0][3] == "须降冷或合并"),
        ("态3 上限缺失应回落默认（不报错）", h3 == []),
        ("保证1 判定不改上限（行为验证）", conf_readonly),
        ("保证2 源码无「改上限」语句（AST 断言 · 机器禁自动扩）", no_grow_code),
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

    items, conf, conf_src = measure(root)
    hits, obs = evaluate(items, conf)
    print(f"-- 上限来源：{conf_src}")
    print(f"-- 点名观察对象：{obs}")
    if hits:
        print("[FAIL] 闸② 触顶 ⇒ **须降冷或合并**（机器不自动扩上限；如需调高请**显式改 kit.conf**，须留痕）：")
        for name, actual, limit, advice in hits:
            print(f"        {name}：实测 {actual} ／ 上限 {limit} ⇒ {advice}")
        return 3
    print("[OK] 闸② 容量闸通过（未触顶）")
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

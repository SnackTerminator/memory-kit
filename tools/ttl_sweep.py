#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸③ 寿命闸（TTL ＋ 降冷）—— 设计件 §6.1。

判据（客观可判）：出**过期清单**（含**建议动作**）。
★ **脚本内无删除分支** —— 这是「**L2 永不自动删，只可显式废弃**」的**代码级保证**。

分层处置（只给建议，不执行）：
  L0／L1 过期 ⇒ 建议「**提炼或降冷**」｜L2 过期 ⇒ 建议「**显式废弃或续期**（永不自动删）」
  **L2 条目混入 L1 扫描面** ⇒ 报警（层级归属错）

**边界**：本脚本**只读＋判**，**一律不改库**；`--dry-run` 为**默认且唯一**模式。

用法：
  python tools/ttl_sweep.py --root <库根> [--today YYYY-MM-DD]
  python tools/ttl_sweep.py --selftest        # 三态自检

退出码：0 无待处理 ｜ 5 **有清单待处理**（非失败，是"有活干"）｜ 3 参数/IO 错
"""
import argparse
import datetime
import sys
sys.dont_write_bytecode = True  # ★ 保证「代码根只读」：禁写字节码（须在 import kitmeta 之前）—— 治 E631
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitmeta  # noqa: E402

L1_HINT = ("01-记忆档案/记忆工程/会话速读包.md",)


def collect(root: Path, today=None):
    """返回 (过期清单, L2 混入告警, 观察串)。清单项＝(相对路径, 层, 状态说明, 建议动作)。"""
    conf, _src = kitmeta.load_conf(root)
    default_days = int(conf.get("TTL_DEFAULT_DAYS", kitmeta.DEFAULTS["TTL_DEFAULT_DAYS"]))
    todos, mixed = [], []

    for p, rel, meta, _body in kitmeta.iter_l2(root):
        layer = str(meta.get("layer", "")).strip()
        state, note = kitmeta.ttl_state(meta, today=today, default_days=default_days)
        if state == "expired":
            advice = "显式废弃或续期（**永不自动删**）" if layer == "L2" else "提炼或降冷"
            todos.append((rel, layer, note, advice))
        if layer != "L2" and layer in ("L0", "L1"):
            mixed.append((rel, layer, "非 L2 条目落在记忆档案扫描面"))

    obs = f"L2 条目扫描完成 ｜ 过期 {len(todos)} ｜ 层级错位 {len(mixed)} ｜ 默认 TTL {default_days} 天"
    return todos, mixed, obs


def _has_delete_call(src: str) -> bool:
    """AST 静态断言：源码中是否存在删除类**调用**（不靠字面量匹配，避免自伤）。"""
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True  # 解析失败 ⇒ 保守判"有"，宁可误报
    targets = (("os", "remove"), ("os", "unlink"), ("os", "rmdir"), ("shutil", "rmtree"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value
            if isinstance(base, ast.Name) and (base.id, node.func.attr) in targets:
                return True
    return False


def selftest() -> int:
    print("== selftest（三态 ＋ 双保证）==")
    import tempfile
    src_no_delete = not _has_delete_call(Path(__file__).read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / "01-记忆档案"
        d.mkdir(parents=True)
        # 态1：无过期
        (d / "ok.md").write_text("---\nlayer: L2\nttl: permanent\n---\n正文\n", encoding="utf-8")
        t1, m1, _ = collect(root, today=datetime.date(2026, 9, 29))
        # 态2：有过期（ttl 已过）
        (d / "old.md").write_text("---\nlayer: L2\nttl: 2026-01-01\n---\n正文\n", encoding="utf-8")
        t2, _m2, _ = collect(root, today=datetime.date(2026, 9, 29))
        # 态3：L1 层混入（非 L2 但带 layer）
        (d / "stray.md").write_text("---\nlayer: L1\nttl: permanent\n---\n正文\n", encoding="utf-8")
        _t3, m3, _ = collect(root, today=datetime.date(2026, 9, 29))
        # 行为态：跑闸前后磁盘**逐件不变**（只读验证）
        snap = lambda: sorted((p.relative_to(root).as_posix(), p.stat().st_size)
                              for p in root.rglob("*") if p.is_file())
        before = snap()
        collect(root, today=datetime.date(2026, 9, 29))
        unchanged = snap() == before

    cases = [
        ("态1 无过期应清零", t1 == [] and m1 == []),
        ("态2 过期应入清单并给建议", len(t2) == 1 and "永不自动删" in t2[0][3]),
        ("态3 L1 层混入应报警", len(m3) == 1),
        ("保证1 跑闸不改库（只读 · 行为验证）", unchanged),
        ("保证2 无删除类调用（AST 断言）", src_no_delete),
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
    ap.add_argument("--today", default=None, help="基准日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        print(f"[FAIL] 库根不存在：{root}")
        return 3
    today = datetime.date.fromisoformat(a.today) if a.today else None

    todos, mixed, obs = collect(root, today=today)
    print("-- 模式：dry-run（**只出清单，不执行任何变更**）")
    print(f"-- 点名观察对象：{obs}")
    for rel, layer, note, advice in todos:
        print(f"[清单] {rel}（{layer}）：{note} ⇒ **{advice}**")
    for rel, layer, note in mixed:
        print(f"[报警] {rel}（{layer}）：{note}")
    if todos or mixed:
        print("== 闸③ 有待处理项（**人工/AI 显式动作**；本闸永不自动删）==")
        return 5
    print("[OK] 闸③ 寿命闸通过（无待处理）")
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

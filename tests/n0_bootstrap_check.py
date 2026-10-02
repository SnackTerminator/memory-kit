#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N0 新生儿态自检 —— 干净路径冷启动后，骨架能否"合法出生"（G3 ③）。

判据（承 DSH 15:4x 否定性裁决 Q6「把 G6 单机可判子项前移进 S3」）：
  在【干净路径】冷启动 ⇒ ① 必读清单全满足（或按 N0 生成占位并报出）
                        ② 结构件齐 ③ 零手工补件 ④ 骨架自带 N0 三行为承载

用法：
  python tests/n0_bootstrap_check.py --root <包根>
  python tests/n0_bootstrap_check.py --selftest

退出码：0 通过 ｜ 1 未通过 ｜ 3 参数/IO 错误
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED = (
    "01-记忆档案/SOUL.md",
    "01-记忆档案/USER.md",
    "01-记忆档案/IDENTITY.md",
    "01-记忆档案/MEMORY.md",
    "01-记忆档案/记忆工程/会话速读包.md",
)
STRUCTURAL = (
    "AGENTS.md",
    "MANIFEST.md",
    "01-记忆档案/carrier.yaml",
    "01-记忆档案/.learnings/ERRORS.md",
    "01-记忆档案/.learnings/LEARNINGS.md",
    "01-记忆档案/.learnings/SEED.md",
)
N0_BEHAVIOUR = ("不崩", "不装懂", "主动索要")


def run_install(kit_root: Path, target: Path):
    script = kit_root / "install" / "init_instance.py"
    if not script.is_file():
        return None, f"找不到初始化器：{script}"
    cp = subprocess.run(
        [sys.executable, "-B", str(script), "--target", str(target), "--kit-root", str(kit_root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return cp, None


def check_instance(inst: Path):
    problems, notes = [], []

    missing, empty = [], []
    for rel in REQUIRED:
        f = inst / rel
        if not f.is_file():
            missing.append(rel)
        elif f.stat().st_size == 0:
            empty.append(rel)
    problems += [f"必读件缺失：{m}" for m in missing]
    problems += [f"必读件为空：{m}" for m in empty]

    for rel in STRUCTURAL:
        f = inst / rel
        if not (f.is_file() and f.stat().st_size > 0):
            problems.append(f"结构件缺失或为空：{rel}")

    # N0 三行为须有承载件（MANIFEST 的 N0 段）
    man = inst / "MANIFEST.md"
    if man.is_file():
        txt = man.read_text(encoding="utf-8", errors="replace")
        for kw in N0_BEHAVIOUR:
            if kw not in txt:
                problems.append(f"MANIFEST 未承载 N0 行为：{kw}")
    else:
        problems.append("MANIFEST.md 缺失 ⇒ 无 N0 承载面")

    # 占位件（= 骨架自带不全的信号）出现即记，不算致命但须报
    for rel in REQUIRED:
        f = inst / rel
        if f.is_file() and "占位件" in f.read_text(encoding="utf-8", errors="replace"):
            notes.append(f"骨架未自带、由 install 生成占位：{rel}")

    n_files = sum(1 for p in inst.rglob("*") if p.is_file())
    n_bytes = sum(p.stat().st_size for p in inst.rglob("*") if p.is_file())
    return problems, notes, n_files, n_bytes


def selftest() -> int:
    print("== selftest（三态）==")
    results = []
    kit = KIT_ROOT

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # 态 1：正常套件 ⇒ 全绿
        t1 = base / "ok"
        cp, err = run_install(kit, t1)
        if err or cp.returncode != 0:
            results.append(("态1 正常安装", False))
        else:
            problems, notes, nf, nb = check_instance(t1)
            results.append(("态1 正常安装应全绿", not problems and not notes))

        # 态 2：装后人为删一件 ⇒ 应被检出
        t2 = base / "broken"
        cp, err = run_install(kit, t2)
        if cp and cp.returncode == 0:
            (t2 / "01-记忆档案" / "SOUL.md").unlink()
            problems, _notes, _nf, _nb = check_instance(t2)
            results.append(("态2 缺必读件应被检出", any("SOUL.md" in p for p in problems)))
        else:
            results.append(("态2 缺必读件应被检出", False))

        # 态 3：套件根不存在 ⇒ 安装器应报错返回，而非静默成功
        cp, err = run_install(base / "no-such-kit", base / "t3")
        reported = (err is not None) or (cp is not None and cp.returncode != 0)
        results.append(("态3 无效套件根应报错", reported))

    ok = True
    for name, res in results:
        print(f"  [{'OK' if res else 'FAIL'}] {name}")
        ok = ok and res
    print(f"== selftest {'全绿' if ok else '有红'}（{len(results)} 态）==")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="套件根（默认：本脚本上一级）")
    ap.add_argument("--keep", action="store_true", help="保留临时实例目录（供人工复核）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    kit_root = Path(a.root).resolve() if a.root else KIT_ROOT
    if not kit_root.is_dir():
        print(f"[FAIL] 套件根不存在：{kit_root}")
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="n0_check_"))
    inst = tmp / "instance"
    try:
        cp, err = run_install(kit_root, inst)
        if err:
            print(f"[FAIL] {err}")
            return 3
        if cp.returncode != 0:
            print(f"[FAIL] 初始化器返回 {cp.returncode}")
            print(cp.stdout or "", cp.stderr or "")
            return 1

        problems, notes, n_files, n_bytes = check_instance(inst)
        print(f"-- 冷启动落点：{inst}")
        print(f"-- 点名观察对象：件数 {n_files} ｜ 总字节 {n_bytes} ｜ "
              f"缺件 {len([p for p in problems if '缺失' in p])} ｜ "
              f"机器生成占位 {len(notes)}")
        for p in problems:
            print(f"   [FAIL] {p}")
        for n in notes:
            print(f"   [WARN] {n}（N0 允许，但说明骨架未自带 ⇒ 请补齐骨架）")

        ok = not problems and not notes
        print(f"== N0 新生儿态自检：{'通过' if ok else '未通过'} ==")
        return 0 if ok else 1
    finally:
        if a.keep:
            print(f"-- 已保留临时实例：{inst}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

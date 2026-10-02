#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包器 —— 按白名单产出发行包（**打包前强制跑发行前闸**）。

设计要点：
- **白名单是真源**：读 `发行物清单.md` 的「一、白名单」段，**只打这些件**（多一件都不打）；
- **打包前必过闸**：先跑 `tests/pre_release.py`，**任一红 ⇒ 拒绝打包**（防"带病出厂"）；
- **发行名映射**：包内顶层目录名 = `memory-kit`（构建目录名与发行名解耦）。

⚠️ **本脚本是发行者工具**：`--private-ref`／`--keywords` 属**发行者侧**参数（用户不需要打包）。

用法：
  python install/pack.py --out <输出.zip> --private-ref <私有件目录> --keywords <词表件>
  python install/pack.py --dry-run            # 只看会打哪些件

退出码：0 成功 ｜ 1 闸未过/白名单不符 ｜ 3 参数/IO 错
"""
import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
MANIFEST = KIT / "发行物清单.md"
RELEASE_NAME = "memory-kit"


def parse_whitelist():
    """解析 发行物清单.md 的「一、白名单」围栏块。"""
    if not MANIFEST.is_file():
        return []
    lines = MANIFEST.read_text(encoding="utf-8", errors="replace").splitlines()
    out, started, state = [], False, 0
    for ln in lines:
        s = ln.strip()
        if not started:
            if s.startswith("## 一、白名单"):
                started = True
            continue
        if s.startswith("```"):
            if state == 0:
                state = 1
                continue
            break
        if state == 1 and s:
            out.append(s)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="输出 zip 路径（默认 <套件目录>/../memory-kit.zip）")
    ap.add_argument("--private-ref", default=None, help="私有件目录（发行者侧 · 供判据②）")
    ap.add_argument("--keywords", default=None, help="私人关键词表（发行者侧 · 供判据②）")
    ap.add_argument("--allow-incomplete", action="store_true", help="调试用：跳过判据②")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    wl = parse_whitelist()
    if not wl:
        print("[FAIL] 白名单解析为空 —— 检查 `发行物清单.md` 的「一、白名单」段")
        return 1

    # ★ 打包前强制过闸
    cmd = [sys.executable, "-B", str(KIT / "tests" / "pre_release.py"), "--root", str(KIT)]
    if a.keywords:
        cmd += ["--keywords", a.keywords]
    if a.private_ref:
        cmd += ["--private-ref", a.private_ref]
    if a.allow_incomplete:
        cmd += ["--allow-incomplete"]
    if not a.dry_run:
        print("==== 打包前闸（任一红 ⇒ 拒绝打包）")
        cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((cp.stdout or "").rstrip()[-800:])
        if cp.returncode != 0:
            print("[FAIL] 发行前闸未过 ⇒ **拒绝打包**（这是设计行为，不是故障）")
            print("  → 处方：判据① 红灯**多为「构建垃圾进包」**（`__pycache__/` · `*.bak_*`）⇒ **先清再打包**；")
            print("     清法示例：`find . -name __pycache__ -type d -prune -exec rm -rf {} +`（Windows 可手动删）")
            print("     ⚠️ **不要**靠排除规则绕过判据 —— 判据是唯一真源（见 `spec/零私人内容判据.md` §八）。")
            return 1

    have, missing = [], []
    for rel in wl:
        (have if (KIT / rel).is_file() else missing).append(rel)

    print(f"-- 白名单 {len(wl)} 件 ｜ 实到 {len(have)} 件 ｜ 缺 {len(missing)} 件")
    for m in missing:
        print(f"   [WARN] 白名单声明但缺失：{m}")

    if a.dry_run:
        print(f"[dry] 将打包 {len(have)} 件 → 顶层目录 `{RELEASE_NAME}/`")
        return 0

    # ★ 默认输出**落在套件目录之外**（临时目录）：产物若落进构建根，会变成"白名单外文件"而污染判据①。
    out = Path(a.out) if a.out else (Path(tempfile.gettempdir()) / "memory-kit.zip")
    # ★ 输出目录不存在 ⇒ 自动创建（2026-09-29 实测抓出：原先直接 FileNotFoundError 裸栈，与本脚本
    #   声明的"IO 错 ⇒ 退出码 3"不符；裸栈会让使用者以为是脚本坏了）。
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[FAIL] 输出目录无法创建：{out.parent}（{e}）")
        return 3
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in have:
            z.write(KIT / rel, f"{RELEASE_NAME}/{rel}")
    size = out.stat().st_size
    print(f"-- 已产出：{out} ｜ {len(have)} 件 ｜ {size} B ｜ 顶层 `{RELEASE_NAME}/`")
    print("-- 提示：包内**不含** `instance/`（I 层落点）与 `_run/`（运行态）—— 它们不在白名单里")
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

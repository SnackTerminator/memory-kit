#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化器 —— 在你的目录里生成一个空记忆库（N0 新生儿态）。

做什么：把包根的入口件（AGENTS.md / MANIFEST.md / 接上我.md）与 kernel-skeleton/ 整体复制到目标目录，
        并装**注入面工具** tools/digest.py。
        （2026-10-02 · 0.1.15 补：原版不装它 ⇒ **库不自足** —— 宿主侧接线调不到 digest
         就只能退化为一句指针；本机接入实测暴露。）
不做什么：不联网、不装依赖、不改你的环境、不生成任何"内容" —— 出生时它是空的，这是合法的。

用法：
  python install/init_instance.py --target <库目录> [--dry-run] [--force]

退出码：0 成功 ｜ 3 目标已存在且非空（需 --force）｜ 4 IO 错误
"""
import argparse
import shutil
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
# 入口件（复制进库根）：
#   AGENTS.md／MANIFEST.md —— 惯例入口与读序规范（宿主启动时读）
#   接上我.md             —— 【0.1.19 加】递进门 L0：主人主动拖进对话框的临场件
#                             （原缺 ⇒ 库在盘上、Agent 不知道它存在 ⇒ 「可读」≠「会被读」）
ENTRY_FILES = ("AGENTS.md", "MANIFEST.md", "接上我.md")
SKELETON = "kernel-skeleton"

# N0 必读件（与 MANIFEST「① 本轮必读」同口径）；缺件须生成占位并报出，禁静默失败
REQUIRED = (
    "01-记忆档案/SOUL.md",
    "01-记忆档案/USER.md",
    "01-记忆档案/IDENTITY.md",
    "01-记忆档案/MEMORY.md",
    "01-记忆档案/记忆工程/会话速读包.md",
)

# 库自足所需工具（与 `发行物清单` 白名单同口径；**只装零依赖件**）
# 2026-10-02 加（`0.1.15`）：原版只拷骨架 ⇒ 库根缺 `tools/digest.py`，
#   宿主侧接线（`SessionStart` 等）调不到它 ⇒ 注入面**退化为一句指针**。
TOOLS = (
    "tools/digest.py",
)

PLACEHOLDER = """# {rel}

> **占位件** —— 本件应由骨架出厂。当前为空缺，按 N0 三行为处理：
> **不崩**（不报错退出）／**不装懂**（不编内容）／**主动索要**（请主人补充）。

## 待补

- [ ] 主人补充本件内容
"""


def ensure_required(target: Path, dry_run: bool, provided=None):
    """必读件缺失 ⇒ 生成占位件。返回 (生成清单, 已在位清单)。

    provided ＝ 本次安装**将提供**的相对路径集合。
    （dry-run 下 target 尚为空 ⇒ 须以此判断"骨架自带"，否则会**误报**"已生成占位"。）
    """
    provided = set(provided or ())
    created, existed = [], []
    for rel in REQUIRED:
        if rel in provided:
            existed.append(rel)
            continue
        dst = target / rel
        if dst.exists() and dst.stat().st_size > 0:
            existed.append(rel)
            continue
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(PLACEHOLDER.format(rel=rel), encoding="utf-8")
        created.append(rel)
    return created, existed


def collect(kit_root: Path):
    """产出 [(源文件, 目标相对路径)]。"""
    items = []
    for name in ENTRY_FILES:
        src = kit_root / name
        if src.is_file():
            items.append((src, name))
    skel = kit_root / SKELETON
    if skel.is_dir():
        for p in sorted(skel.rglob("*")):
            if p.is_file():
                items.append((p, p.relative_to(skel).as_posix()))
    for rel in TOOLS:                                   # 库自足工具（0.1.15 加）
        src = kit_root / rel
        if src.is_file():
            items.append((src, rel))
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="记忆库落点目录")
    ap.add_argument("--kit-root", default=str(KIT_ROOT), help="套件根（默认：本脚本上一级）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="目标非空时仍写入（会覆盖同名件）")
    a = ap.parse_args(argv)

    kit_root = Path(a.kit_root).resolve()
    target = Path(a.target).resolve()

    items = collect(kit_root)
    if not items:
        print(f"[FAIL] 套件根未找到可出厂件：{kit_root}")
        return 4

    if target.exists() and any(target.iterdir()) and not a.force:
        print(f"[FAIL] 目标目录已存在且非空：{target}")
        print("       如确要写入，请加 --force（同名件将被覆盖）")
        return 3

    written = 0
    total_bytes = 0
    for src, rel in items:
        dst = target / rel
        size = src.stat().st_size
        if a.dry_run:
            print(f"  [dry] {rel}  ({size} B)")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        written += 1
        total_bytes += size

    verb = "将写入" if a.dry_run else "已写入"
    print(f"-- {verb} {written} 件 / {total_bytes} B -> {target}")

    # N0 承载：必读件缺失 ⇒ 生成占位并【当场报出】（禁静默失败）
    created, existed = ensure_required(target, a.dry_run, provided=[rel for _s, rel in items])
    print(f"-- N0 必读件：在位 {len(existed)} / {len(REQUIRED)}")
    if created:
        print("   [报出] 以下必读件原本缺失，已生成占位（请主人补充）：")
        for rel in created:
            print(f"        - {rel}")

    print("-- 注入面（库已自足）：python tools/digest.py --root <库目录> --via \"L2:自定义指令位\"")
    print("-- 下一步：让你的宿主读库根 AGENTS.md（读序见 MANIFEST.md）")
    print("-- 自检：python install/verify.py --root <库目录>")
    print("-- 出生时记忆为空是正常的（N0 新生儿态：不崩 / 不装懂 / 主动索要）")
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

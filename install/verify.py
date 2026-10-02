#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""移植者侧「一键自检」—— 装完跑一次，回答一个问题：**我这套现在能不能用？**

面向**用户**（不是发行者）：不需要任何私有参数，不判断"有没有私人内容"，
只判断「**结构齐不齐 ＋ 组件活不活 ＋ CLI 通不通**」。

用法：
  python install/verify.py --root <你的库目录>
  python install/verify.py --root <你的库目录> --json

退出码：0 **能用** ｜ 1 **不能用**（附缺什么）｜ 3 参数/IO 错
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
REQUIRED = (
    "01-记忆档案/SOUL.md",
    "01-记忆档案/USER.md",
    "01-记忆档案/IDENTITY.md",
    "01-记忆档案/MEMORY.md",
    "01-记忆档案/记忆工程/会话速读包.md",
)


def run(args):
    cp = subprocess.run([sys.executable, "-B"] + args, capture_output=True,
                        text=True, encoding="utf-8", errors="replace")
    return cp.returncode, ((cp.stdout or "") + (cp.stderr or ""))


# ── ⑥ 学习件字段自检（WARN 级）──────────────────────────────────────────────
# 为什么是 WARN 而不是 FAIL：这两件是**用户自己写**的；字段缺了不影响"能不能用"，
# 但会让"记录了却不生效"（护栏不写 ⇒ 教训防不住复发；来源不写 ⇒ 分不清谁说的）。
ENTRY_MARK = "## 二、实际条目区"
LEARN_FIELDS = {
    "ERRORS.md": ("**护栏**", "**来源**"),
    "LEARNINGS.md": ("**来源**", "**被引用过**"),
}


def _entries(text: str):
    """只取「实际条目区」之下的条目块（格式示例段不算数据）。"""
    if ENTRY_MARK in text:
        text = text.split(ENTRY_MARK, 1)[1]
    blocks, cur = [], None
    for ln in text.splitlines():
        if ln.startswith("### "):
            if cur is not None:
                blocks.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
    if cur is not None:
        blocks.append(cur)
    return ["\n".join(b) for b in blocks]


def check_learnings(root: Path):
    """返回 WARN 明细清单（空 = 无 WARN）。"""
    warns = []
    lp = root / "01-记忆档案" / ".learnings"
    for fn, fields in LEARN_FIELDS.items():
        f = lp / fn
        if not f.is_file():
            continue                      # 缺件由别处管；这里只查字段
        for blk in _entries(f.read_text(encoding="utf-8", errors="replace")):
            head = blk.splitlines()[0].strip()
            missing = [fd for fd in fields if fd not in blk]
            if missing:
                warns.append(f"{fn} `{head}` 缺字段：{'、'.join(missing)}")

    # 必读区隔离（投毒防线最要紧的一条）：经验库若被列进"开局必读"，
    # 则其中的「外部注入」条目会随每次会话注入 ⇒ 放大器。
    man = root / "MANIFEST.md"
    if man.is_file():
        txt = man.read_text(encoding="utf-8", errors="replace")
        seg = txt
        for marker in ("## ① 本轮必读", "## ①"):
            if marker in txt:
                seg = txt.split(marker, 1)[1]
                break
        seg = seg.split("## ②", 1)[0]
        if ".learnings/" in seg:
            warns.append("MANIFEST「① 本轮必读」段含 `.learnings/` ⇒ 经验库被列入开局必读"
                         "（其中「外部注入」条目会随每次会话注入 ⇒ 违投毒防线 #3）")
    return warns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="你的库目录（install 时生成的）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"[FAIL] 库目录不存在：{root}")
        return 3

    checks = []

    # ① 结构：入口件 ＋ 必读件
    entry = (root / "AGENTS.md").is_file() and (root / "MANIFEST.md").is_file()
    missing = [r for r in REQUIRED if not (root / r).is_file()]
    checks.append(("① 入口件与必读件", entry and not missing,
                   f"AGENTS/MANIFEST {'齐' if entry else '缺'}；必读缺失 {len(missing)} 件"
                   + (f"：{'、'.join(missing)}" if missing else "")))

    # ② N0 新生儿态自检
    rc, out = run([str(KIT / "tests" / "n0_bootstrap_check.py"), "--root", str(KIT)])
    checks.append(("② 新生儿态自检", rc == 0, out.strip().splitlines()[-1] if out.strip() else ""))

    # ③ 四闸自检
    rc, out = run([str(KIT / "tests" / "gates_selftest.py"), "--quiet"])
    checks.append(("③ 四闸自检", rc == 0, out.strip().splitlines()[-1] if out.strip() else ""))

    # ④ CLI 可用（get/search/list 三条路径都在）
    rc, out = run([str(KIT / "tools" / "memory.py"), "selftest"])
    checks.append(("④ CLI 自检", rc == 0, out.strip().splitlines()[-1] if out.strip() else ""))

    # ⑤ CLI 真读你的库（list 能跑通即算通）
    rc, out = run([str(KIT / "tools" / "memory.py"), "--root", str(root), "list"])
    checks.append(("⑤ CLI 能读本库", rc == 0, out.strip().splitlines()[0] if out.strip() else ""))

    # ⑥ 学习件字段自检（WARN 级：不阻断"能用"，但必须出声）
    warns = check_learnings(root)

    ok = all(c[1] for c in checks)
    if a.json:
        print(json.dumps({"root": str(root), "usable": ok, "warns": warns,
                          "checks": [{"name": n, "pass": p, "note": d} for n, p, d in checks]},
                         ensure_ascii=False))
    else:
        print(f"==== 移植者侧自检 ｜ 库目录：{root}")
        for name, passed, detail in checks:
            print(f"  [{'OK' if passed else 'FAIL'}] {name}  —— {detail}")
        print(f"  [{'OK' if not warns else 'WARN'}] ⑥ 学习件字段自检  —— "
              + ("字段齐" if not warns else f"{len(warns)} 项待补"))
        for w in warns:
            print(f"        · {w}")
        if warns:
            print("        （WARN 不阻断使用；处置口径见 spec/记忆形成与容量治理.md §九）")
        print(f"==== 结论：{'✅ 能用' if ok else '❌ 不能用（先按上面的 FAIL 项处置，见 docs/TROUBLESHOOTING.md）'}"
              + (f"（另有 {len(warns)} 条 WARN，见上）" if warns else ""))
    return 0 if ok else 1


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

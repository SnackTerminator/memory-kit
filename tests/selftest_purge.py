#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`purge` 夹具 —— 覆盖 **D1–D8** ＋ 防呆 ＋ **跨工具一致性向量**（`curate` ↔ `purge` 公式同源）。

D8 针式探针（本件核心）：**造针 → 可检索（正向）→ purge → 全读取路径不可达 → 且回执在**。

⚠️ `memory.py` 的 `--root` 是**顶层选项**（`memory [--root R] <cmd>`），**不是子命令选项** ⇒ 统一走 `mem()`
（本文件首轮即踩过：写成 `search KW --root R` ⇒ 子命令 parser 不认 ⇒ `rc=2`）。

用法：python -B selftest_purge.py ｜ 退出码：0 全绿 ｜ 1 有 FAIL
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
PURGE = TOOLS / "purge.py"
MEMORY = TOOLS / "memory.py"
PY = sys.executable
R = []
NEEDLE = "NEEDLE-D7XQ-20261001"
TGT = "01-记忆档案/条目A.md"


def run(*args):
    cp = subprocess.run([PY, "-B"] + [str(x) for x in args], capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def mem(root, *args):
    """`memory.py` 壳：**`--root` 必须放在子命令之前**。"""
    return run(MEMORY, "--root", root, *args)


def ck(name, ok, note=""):
    R.append((name, bool(ok), note))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def mkroot(base):
    root = Path(base) / "lib"
    for d in ("01-记忆档案", "08-检索索引", "_archive/01-记忆档案", "_meta/curation/hist"):
        (root / d).mkdir(parents=True, exist_ok=True)
    body = "---\nlayer: L2\nttl: 30d\n---\n\n%s 这是正文甲\n" % NEEDLE
    (root / TGT).write_text(body, encoding="utf-8")
    (root / "01-记忆档案/条目B.md").write_text("---\nlayer: L2\n---\n\n正文乙（对照）\n", encoding="utf-8")
    (root / "01-记忆档案/条目C.md").write_text("---\nlayer: L2\n---\n\n正文丙（对照）\n", encoding="utf-8")
    (root / "08-检索索引/_index.tsv").write_text(
        "path\tlayer\thead\n%s\tL2\t%s 这是正文甲\n01-记忆档案/条目B.md\tL2\t正文乙\n" % (TGT, NEEDLE),
        encoding="utf-8")
    shutil.copyfile(root / TGT, root / "_archive" / TGT)                                            # archive-copy
    shutil.copyfile(root / TGT, root / "_meta/curation/hist/20261001T000000_cool_ab12cd.snapshot")  # hist-snapshot
    shutil.copyfile(root / TGT, root / "01-记忆档案/条目A.md.bak_20260101_JIOOO")                    # other-copy
    return root


with tempfile.TemporaryDirectory() as tmp:
    root = mkroot(tmp)

    # ── D7 零依赖零网（AST 机检）──
    sys.path.insert(0, str(TOOLS))
    import purge as P
    ck("D7 零依赖零网（AST 自查无非标准库 import）", P.audit_probe() == [], str(P.audit_probe()))

    # ── 跨工具一致性向量（根治「复用不重造」含糊 · v1.1）──
    import curate as C
    vec = ["2026-01-01T00:00:00", "purge", "primary", TGT, "deadbeef", "1", "op", "rel"]
    ck("跨工具一致性向量（purge._row_hash ≡ curate._row_hash）",
       P._row_hash(vec) == C._row_hash(vec), "%s vs %s" % (P._row_hash(vec), C._row_hash(vec)))

    # ── D8-a 针式探针·正向：删前**可检索** ──
    rc_s, out_s = mem(root, "search", NEEDLE)
    ck("D8 正向：删前 `memory search` 命中该针（rc=0）", rc_s == 0 and NEEDLE in out_s, "rc=%d ｜ %s" % (rc_s, out_s[-120:]))

    # ── 防呆：缺 --yes ⇒ 拒；指纹错 ⇒ 拒；preview 零写 ──
    b_before = sha(root / "01-记忆档案/条目B.md")
    ck("防呆 缺 --yes ⇒ 拒", run(PURGE, "purge", "--root", root, "--target", TGT, "--operator", "u1")[0] == 1)
    ck("防呆 无 --receipt-fingerprint ⇒ 拒",
       run(PURGE, "purge", "--root", root, "--target", TGT, "--operator", "u1", "--yes")[0] == 1)
    ck("防呆 指纹错 ⇒ 拒",
       run(PURGE, "purge", "--root", root, "--target", TGT, "--operator", "u1", "--yes",
           "--receipt-fingerprint", "deadbeef")[0] == 1)
    rc_pv, out_pv = run(PURGE, "purge", "--root", root, "--target", TGT, "--operator", "u1", "--preview")
    ck("防呆 预览 rc=0 且零写（primary 仍在）", rc_pv == 0 and (root / TGT).is_file(), "rc=%d" % rc_pv)
    ck("防呆 预览外带最小外锚（sha256[:12]）", sha(root / TGT)[:12] in out_pv)

    # ── 真执行 ──
    rc, out = run(PURGE, "purge", "--root", root, "--target", TGT, "--operator", "u1",
                  "--yes", "--receipt-fingerprint", "NEW")      # 首次删除：回执不存在 ⇒ 期望字面 NEW
    ck("purge 执行 rc=0", rc == 0, out[-200:])

    # ── D1 真删 ──
    ck("D1 真删：目标不存在", not (root / TGT).exists())

    # ── D2 命中副本全清（内容同一性 · 三处）──
    ck("D2 命中副本已清：archive-copy（`_archive/`）", not (root / "_archive" / TGT).exists())
    hist = list((root / "_meta/curation/hist").glob("*.snapshot"))
    ck("D2 命中副本已清：hist-snapshot（全文前像）", len(hist) == 0, str(hist))
    ck("D2 命中副本已清：other-copy（`.bak_*`）",
       not (root / "01-记忆档案/条目A.md.bak_20260101_JIOOO").exists())

    # ── D5 不误伤 ──
    ck("D5 不误伤：对照件 `条目B.md` 内容不变", sha(root / "01-记忆档案/条目B.md") == b_before)
    ck("D5 不误伤：对照件 `条目C.md` 仍在", (root / "01-记忆档案/条目C.md").is_file())

    # ── D2' 路径面 ＋ D3 重建不可复生 ──
    rc_a, out_a = run(PURGE, "audit", "--root", root, "--target", TGT)
    ck("D2' 索引面残留被 audit 检出（rc=1 且列 `_index.tsv`）", rc_a == 1 and "_index.tsv" in out_a, "rc=%d" % rc_a)
    rc_r, out_r = mem(root, "reindex")
    rc_a2, out_a2 = run(PURGE, "audit", "--root", root, "--target", TGT)
    ck("D3 重建索引后**不可复生**（reindex 后 audit rc=0）",
       rc_r == 0 and rc_a2 == 0, "reindex rc=%d ｜ audit rc=%d ｜ %s" % (rc_r, rc_a2, out_a2[-200:]))

    # ── D8-b 针式探针·反向：删后全读取路径不可达 ──
    rc_s2, out_s2 = mem(root, "search", NEEDLE)
    ck("D8 反向：删后 `memory search` 不再命中（rc=1）", rc_s2 == 1, "rc=%d ｜ %s" % (rc_s2, out_s2[-140:]))
    rc_g, out_g = mem(root, "get", TGT)
    ck("D8 反向：删后 `memory get` 取不到（rc=4）", rc_g == 4, "rc=%d ｜ %s" % (rc_g, out_g[-140:]))

    # ── D4 回执可核 ＋ 正向证明回执在 ──
    rc_v, out_v = run(PURGE, "verify", "--root", root)
    ck("D4 回执链完整（verify rc=0）", rc_v == 0, out_v[-150:])
    rp = root / "_meta/deletion/receipt.tsv"
    txt = rp.read_text(encoding="utf-8")
    ck("D4 回执**有行**且 role 分组（primary ＋ 三类副本）",
       all(k in txt for k in ("primary", "archive-copy", "hist-snapshot", "other-copy")))
    ck("D4 证据面**禁存正文**（回执不含针）", NEEDLE not in txt)
    ck("D5 回执 15 列且记 lib_digest pre/post",
       txt.splitlines()[1].count("\t") == 14 and "lib_digest_pre" in txt)
    rp.write_text(txt.replace("primary", "primaryX", 1), encoding="utf-8")
    ck("D4 反例：篡改回执 ⇒ verify 红（rc=1）", run(PURGE, "verify", "--root", root)[0] == 1)

    # ── D6 边界自白（四要素）──
    rc_au, out_au = run(PURGE, "audit", "--root", root)
    ck("D6 边界四要素在场（本库根／逻辑删除／不含库外与宿主侧／自存证）",
       all(k in out_au for k in ("本库根", "逻辑删除", "不含库外与宿主侧", "自存证")), out_au[-160:])

    # ── 归档态目标亦可 purge（v1.1）──
    root2 = mkroot(Path(tmp) / "t2")
    (root2 / "_archive/01-记忆档案").mkdir(parents=True, exist_ok=True)
    (root2 / TGT).replace(root2 / "_archive" / TGT)              # 只留归档态
    rc2, out2 = run(PURGE, "purge", "--root", root2, "--target", TGT, "--operator", "u2",
                    "--yes", "--receipt-fingerprint", "NEW")
    ck("归档态目标可 purge（rc=0 且归档件已清）",
       rc2 == 0 and not (root2 / "_archive" / TGT).exists(), "rc=%d ｜ %s" % (rc2, out2[-160:]))

    # ── 验收薄壳（`tests/deletion_audit.py`）──
    AUDIT = HERE / "deletion_audit.py"
    rc_sh, out_sh = run(AUDIT, "--root", root)
    ck("验收薄壳 `deletion_audit.py` 可用（rc=0 · 边界在场）", rc_sh == 0 and "边界" in out_sh,
       "rc=%d ｜ %s" % (rc_sh, out_sh[-160:]))

    # ── 运行后无 __pycache__ ──
    ck("无 __pycache__（dont_write_bytecode）", not list(Path(tmp).rglob("__pycache__")))

bad = [n for n, ok, _ in R if not ok]
print("== selftest_purge ==")
for n, ok, note in R:
    print("   [%s] %s%s" % ("OK" if ok else "FAIL", n, ("  ← " + note) if (note and not ok) else ""))
print("=> %d/%d" % (len(R) - len(bad), len(R)))
sys.exit(0 if not bad else 1)

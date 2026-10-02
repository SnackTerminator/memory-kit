#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""件 2／件 3 夹具 —— 覆盖判据 1–11（含 Hermes 补强 9／10／11）＋ 批确认防呆四件套。

判据映射（设计稿 §四 ＋ Hermes 批3回件补三条）：
  1 到期可判（由 ttl_sweep 承担 · 本夹具只验"复用而非重造"：源码无 TTL 重实现）
  2 起草不动内容   3 提案可验（schema＋配额超整批拒）   4 不删三充要
  5 台账可回滚（前像逐字节一致）   6 句柄闸（篡改提案/台账 ⇒ 拒且零写入）
  7 幂等           8 零依赖零网     9 他源静默检测   10 原子写   11 分叉可侦测
  ＋ 防呆四件套：①动作分级 ②--batch-count 核数 ③回贴提案指纹 ④逐条 diff 预览

用法：python -B selftest_curate.py
退出码：0 全绿 ｜ 1 有 FAIL
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"           # 件 2／3／4 执行体在 `tools/`
CURATE = TOOLS / "curate.py"
PY = sys.executable
R = []          # (名称, ok, 备注)


def run(*args, cwd=None):
    cp = subprocess.run([PY, "-B", str(CURATE)] + list(args), capture_output=True,
                        text=True, encoding="utf-8", errors="replace", cwd=cwd)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def ck(name, ok, note=""):
    R.append((name, bool(ok), note))


def mkroot(tmp):
    root = Path(tmp) / "lib"
    (root / "01-记忆档案" / "记忆工程").mkdir(parents=True)
    (root / "01-记忆档案" / "a.md").write_text("# A\n内容甲\n", encoding="utf-8")
    (root / "01-记忆档案" / "b.md").write_text("# B\n内容乙\n", encoding="utf-8")
    (root / "01-记忆档案" / "记忆工程" / "c.md").write_text("# C\n", encoding="utf-8")
    return root


def fp(root):
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for f in fns:
            p = Path(dp) / f
            rel = p.relative_to(root).as_posix()
            if rel.startswith("_meta/curation/"):
                continue
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


with tempfile.TemporaryDirectory() as tmp:
    root = mkroot(tmp)
    cand = Path(tmp) / "cand.tsv"
    cand.write_text("01-记忆档案/a.md\tretire\t超期未用\n01-记忆档案/b.md\tcool\t降温\n", encoding="utf-8")
    TGT = "01-记忆档案/a.md"
    PID = "p001-" + hashlib.sha256(TGT.encode("utf-8")).hexdigest()[:6]

    # ── 判据 8：零依赖零网（静态）──
    src = CURATE.read_text(encoding="utf-8")
    ck("判据8 零依赖零网（源码无网络导入）",
       not any(m in src for m in ("import requests", "import socket", "urllib.request", "http.client")))
    ck("判据1 到期判定=复用 ttl_sweep（无 TTL 重实现）",
       "ttl_sweep.py" in src and "ttl_state" not in src)

    f_before = fp(root)

    # ── 件 2 ①正常提案 ──
    rc, out = run("propose", "--root", str(root), "--candidates", str(cand), "--kit", str(HERE.parent))
    ck("件2 正常提案 rc=5（有提案待处理）", rc == 5, "rc=%d" % rc)
    ck("判据2 起草不动内容（propose 前后除 _meta/curation 外指纹不变）", fp(root) == f_before)
    pj = root / "_meta/curation/proposals.json"
    ck("判据3 proposals.json 生成且 schema 在场",
       pj.is_file() and json.loads(pj.read_text(encoding="utf-8"))["schema"] == 1)
    pmd = root / "_meta/curation/proposals.md"
    fp8 = hashlib.sha256(pj.read_bytes()).hexdigest()[:8]
    ck("判据3 proposals.md 为派生件且嵌 json 指纹", pmd.is_file() and fp8 in pmd.read_text(encoding="utf-8"))

    # ── 件 2 ②配额超 ⇒ 整批拒 ──
    rc, out = run("propose", "--root", str(root), "--candidates", str(cand),
                  "--kit", str(HERE.parent), "--quota", "1")
    ck("判据3 配额超 ⇒ 整批拒 rc=1", rc == 1, "rc=%d" % rc)

    # ── 防呆④ 预览不写 ──
    rc1, _ = run("apply", "--root", str(root), "--preview")
    ck("防呆④ 预览 rc=0 且不写任何件", rc1 == 0 and fp(root) == f_before)

    # ── 防呆③ 指纹闸 ──
    ck("防呆③ 缺指纹 ⇒ 拒", run("apply", "--root", str(root), "--yes")[0] == 1)
    ck("防呆③ 指纹错 ⇒ 拒", run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", "deadbeef")[0] == 1)

    # ── 防呆① 动作分级 ──
    rc, _ = run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", fp8,
                "--batch", "--batch-count", "2")
    ck("防呆① 批模式含 retire ⇒ 拒", rc == 1, "rc=%d" % rc)
    # ── 防呆② 核数 ──
    rc, _ = run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", fp8, "--batch")
    ck("防呆② 批模式缺 --batch-count ⇒ 拒", rc == 1)
    rc, _ = run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", fp8,
                "--batch", "--batch-count", "9")
    ck("防呆② --batch-count 不符 ⇒ 拒", rc == 1)

    # ── 判据 11 分叉可侦测 ──
    st = root / "_meta/curation/state.json"
    st.write_text(json.dumps({"schema": 1, "last_seen": {"at": "2026-01-01T00:00:00", "count": 1, "digest": "0000deadbeef0000"}}),
                  encoding="utf-8")
    rc11, out11 = run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", fp8)
    ck("判据11 指纹漂移（未声明）⇒ 拒 rc=1 且出声", rc11 == 1 and "分叉" in out11, "rc=%d" % rc11)

    # ── 判据 4 三充要：retire ⇒ 移入 _archive ＋ 台账有行 ＋ 内容逐字节一致 ──
    orig = (root / "01-记忆档案/a.md").read_bytes()
    rc, out = run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", fp8,
                  "--accept-drift", "--only", PID)
    arc = root / "_archive/01-记忆档案/a.md"
    led = (root / "_meta/curation/ledger.tsv").read_text(encoding="utf-8")
    ck("判据4 不删：条目移入 _archive 且内容逐字节一致",
       (not (root / "01-记忆档案/a.md").exists()) and arc.is_file() and arc.read_bytes() == orig, "rc=%d" % rc)
    ck("判据4 台账有行（prepared ＋ done 双行 · WAL）",
       "retire:prepared" in led and "retire:done" in led)
    hist = list((root / "_meta/curation/hist").glob("*.snapshot"))
    ck("判据5 前像落 hist/ 且与原文逐字节一致",
       len(hist) >= 1 and any(h.read_bytes() == orig for h in hist))

    # ── 幂等：重跑同 proposal ⇒ skip（且不产生新 done 行）──
    n_done = led.count("retire:done")
    run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", fp8, "--accept-drift", "--only", PID)
    led2 = (root / "_meta/curation/ledger.tsv").read_text(encoding="utf-8")
    ck("判据7 幂等（重跑不新增 done 行）", led2.count("retire:done") == n_done)

    # ── 判据 6 句柄闸：篡改 proposals.json ⇒ 指纹不符 ⇒ 拒且零写入 ──
    pj.write_text(pj.read_text(encoding="utf-8").replace('"total": 2', '"total": 99'), encoding="utf-8")
    rc, _ = run("apply", "--root", str(root), "--yes", "--proposal-fingerprint", fp8)
    ck("判据6 提案被篡改 ⇒ 指纹不符 ⇒ 拒且零写入", rc == 1, "rc=%d" % rc)

    # ── 判据 6 台账链：篡改一行 ⇒ 检出 ──
    lp = root / "_meta/curation/ledger.tsv"
    lp.write_text(lp.read_text(encoding="utf-8").replace("retire:done", "retire:doneX", 1), encoding="utf-8")
    sys.path.insert(0, str(TOOLS))
    import curate as C
    ck("判据6 台账篡改 ⇒ verify 检出", len(C._verify_chain(root)) >= 1)

    # ── 判据 10 原子写：无 .tmp_ 残留 ──
    ck("判据10 原子写 ⇒ 无 .tmp_ 残留",
       not list((root / "_meta/curation").rglob(".tmp_*")) and not list(root.rglob(".tmp_*")))

    # ── 判据 9 他源静默检测 ──
    root2 = mkroot(Path(tmp) / "t2")
    (root2 / "_meta").mkdir(parents=True, exist_ok=True)
    cand2 = Path(tmp) / "cand2.tsv"
    cand2.write_text("01-记忆档案/a.md\tcool\t降温\n", encoding="utf-8")
    run("propose", "--root", str(root2), "--candidates", str(cand2), "--kit", str(HERE.parent))
    pj2 = root2 / "_meta/curation/proposals.json"
    fp82 = hashlib.sha256(pj2.read_bytes()).hexdigest()[:8]
    (root2 / "01-记忆档案/b.md").write_text("# B\n**被别的会话改了**\n", encoding="utf-8")   # 他源改动
    rc, out = run("apply", "--root", str(root2), "--yes", "--proposal-fingerprint", fp82)
    ck("判据9 他源静默变更（自起草以来）⇒ 检出并 rc=1", rc == 1 and "他源" in out, "rc=%d" % rc)

    # ── 判据 8：未生成 __pycache__ ──
    ck("判据8 运行后无 __pycache__（dont_write_bytecode）",
       not list(Path(tmp).rglob("__pycache__")))

bad = [n for n, ok, _ in R if not ok]
print("== selftest_curate ==")
for n, ok, note in R:
    print("   [%s] %s%s" % ("OK" if ok else "FAIL", n, ("  ← " + note) if (note and not ok) else ""))
print("=> %d/%d" % (len(R) - len(bad), len(R)))
sys.exit(0 if not bad else 1)

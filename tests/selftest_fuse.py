#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""熔断三类 ＋ `pending_proposals` 字段 · 夹具（批 3 收口 · 设计稿 v1.1 §三／§八）。

覆盖：
  熔断·空转 —— 连续空提案达 `IDLE_LIMIT` ⇒ 出声（触发点＝每周期 propose 后由人看输出）
  熔断·误判 —— 抽核率超阈 ⇒ 触；**阈值未定 ⇒ 只记录不熔断**（承 §十-3，不猜阈值）
  熔断·借脑 —— 静态自查：非标准库 import ⇒ 触发（触发点＝设计评审时）
  `pending_proposals` —— `propose` 落字段并置顶；`apply` 后递减（设计稿 §三 接口化）

用法：python -B selftest_fuse.py ｜ 退出码 0 全绿 ｜ 1 有 FAIL
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tools" / "curate.py"
KIT = HERE.parent    # 套件根（`tools/ttl_sweep.py` 由其派生）
PY = sys.executable
R = []


def run(*args):
    cp = subprocess.run([PY, "-B", str(TOOL)] + list(args), capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def ck(name, ok, note=""):
    R.append((name, bool(ok), note))


def mkroot(base, name):
    root = Path(base) / name
    (root / "01-记忆档案").mkdir(parents=True)
    (root / "01-记忆档案/a.md").write_text("# A\n内容甲\n", encoding="utf-8")
    (root / "01-记忆档案/b.md").write_text("# B\n内容乙\n", encoding="utf-8")
    return root


def state(root):
    return json.loads((root / "_meta/curation/state.json").read_text(encoding="utf-8"))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cand = tmp / "c1.tsv"
    cand.write_text("01-记忆档案/a.md\tretire\t超期\n01-记忆档案/b.md\tcool\t降温\n", encoding="utf-8")
    empty = tmp / "empty.tsv"
    empty.write_text("# 空清单\n", encoding="utf-8")

    # ── 库 A：`pending_proposals` 字段 ＋ 空转熔断 ──
    rootA = mkroot(tmp, "A")
    rc, out = run("propose", "--root", str(rootA), "--candidates", str(cand), "--kit", str(KIT))
    st = state(rootA)
    ck("pending_proposals 字段已落（＝2）", st.get("pending_proposals") == 2, json.dumps(st, ensure_ascii=False)[:200])
    ck("pending_proposals 在**前两位键**（设计稿 §三「顶部字段」）",
       "pending_proposals" in list(st.keys())[:2], str(list(st.keys())))
    ck("熔断·空转：有提案 ⇒ idle_streak 归零", st.get("idle_streak") == 0, str(st.get("idle_streak")))

    pj = rootA / "_meta/curation/proposals.json"
    fp8 = hashlib.sha256(pj.read_bytes()).hexdigest()[:8]
    pid_cool = "p002-" + hashlib.sha256("01-记忆档案/b.md".encode("utf-8")).hexdigest()[:6]
    rc, out = run("apply", "--root", str(rootA), "--yes", "--proposal-fingerprint", fp8, "--only", pid_cool)
    ck("apply 后 pending_proposals 递减（＝1）", state(rootA).get("pending_proposals") == 1,
       "rc=%d ｜ %s" % (rc, out[-160:]))

    for _ in range(3):
        run("propose", "--root", str(rootA), "--candidates", str(empty), "--kit", str(KIT))
    ck("熔断·空转：连续 3 周期空提案 ⇒ idle_streak=3", int(state(rootA).get("idle_streak") or 0) == 3,
       str(state(rootA).get("idle_streak")))
    rc, out = run("fuse", "--root", str(rootA))
    ck("熔断·空转 触发（rc=1 ＋ FUSE:idle）", rc == 1 and "FUSE:idle" in out, "rc=%d ｜ %s" % (rc, out[-200:]))

    # ── 库 B：误判熔断（阈值未定 ⇒ 不熔断；给阈且超 ⇒ 触发）──
    rootB = mkroot(tmp, "B")
    run("propose", "--root", str(rootB), "--candidates", str(cand), "--kit", str(KIT))
    rc, out = run("fuse", "--root", str(rootB), "--checked", "10", "--wrong", "9")
    ck("熔断·误判 阈值未定 ⇒ 明写「未定」且**不触发**（rc=0）", rc == 0 and "未定" in out,
       "rc=%d ｜ %s" % (rc, out[-200:]))
    rc, out = run("fuse", "--root", str(rootB), "--checked", "10", "--wrong", "9", "--max-wrong-rate", "0.2")
    ck("熔断·误判 超阈 ⇒ 触发（rc=1 ＋ FUSE:misjudge）", rc == 1 and "FUSE:misjudge" in out,
       "rc=%d ｜ %s" % (rc, out[-200:]))

    # ── 借脑熔断（静态自查）──
    sys.path.insert(0, str(HERE.parent / "tools"))
    import curate as C
    ok, hits = C._borrow_brain_check(Path(C.__file__).read_text(encoding="utf-8"))
    ck("熔断·借脑 本执行体零外部依赖 ⇒ 未触发", ok, str(hits))
    ok2, hits2 = C._borrow_brain_check("import requests\nx = 1\n")
    ck("熔断·借脑 注入非标准库 ⇒ 触发并给出证据", (not ok2) and hits2, str(hits2))
    ok3, hits3 = C._borrow_brain_check("import os\nimport json\n")
    ck("熔断·借脑 纯标准库 ⇒ 不误报", ok3, str(hits3))

    # ── 合并后：件 4 子命令与件 2／3 同执行体可用 ──
    rc, out = run("ledger", "verify", "--root", str(rootA))
    ck("合并后 `ledger verify` 同执行体可用", rc == 0 and "链条完整" in out, "rc=%d ｜ %s" % (rc, out[-160:]))

bad = [n for n, ok, _ in R if not ok]
print("== selftest_fuse ==")
for n, ok, note in R:
    print("   [%s] %s%s" % ("OK" if ok else "FAIL", n, ("  ← " + note) if (note and not ok) else ""))
print("=> %d/%d" % (len(R) - len(bad), len(R)))
sys.exit(0 if not bad else 1)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""J13 · 破坏性操作「改前快照 ＋ 旧文可溯」闸。

【治什么】`J13`（判据层 `01-记忆档案/.learnings/ERRORS.md` §三）：
  破坏性操作**先备份再动**；批量后**必做计数闭合校验**；「原文保留供追溯」这类话**必须真的 grep 得到**。
  2026-10-04 实证（账一）：回滚点建在**覆盖之后** ⇒ 恢复不了；落了「原文保留供追溯」而后续 **grep 不到原句**
  ⇒ 违规本体＝**记录不实**（承三方评审合并裁定 §四）。

【判据（客观可判）】
  ① `--snapshot <f>`：把 f 的**当前逐行**追加到 `<snap-dir>/<YYYYMMDD>.jsonl`（`{t,path,line_no,text}`，只追加）。
  ② `--verify <f> --snippet <s>`：断言 s 能在**当日快照**里命中 ≥1 ⇒ rc 0；命中不到 ⇒ rc 1。
     （⇒ 「我保留了原文」这句话从此**可被机检**：验不到即不许写。）

【载体定位】本闸 ＝ 判据层 `J13` 的**载体**（三格之「闸」：有退出码语义的检查体）。
  由 2026-10-04「落地率」议题三方评审合并裁定 **§五-5** 指定新做；登记见
  `12-运维管理/02_台账记录/规则承载点登记表.md` 段 `R-46`。

【退出码】0 通过 ｜ 1 断言失败 ｜ 3 参数或 IO 错
【用法】
  python tests/pre_change_snapshot.py --snapshot <目标件> --snap-dir <快照目录>
  python tests/pre_change_snapshot.py --verify <目标件> --snippet "<旧文片段>" --snap-dir <快照目录>
  python tests/pre_change_snapshot.py --selftest
【★ 边界（诚实口径）】本闸**不自动拦写动作** —— 「写前必过」最彻底的形态是 `PreToolUse` 钩子，
  那属**宿主接线**，不在套件内。本闸提供的是**可复算的检查体 ＋ 必红例**；挂点＝改 L1 件前／收尾清单。
"""
import argparse
import datetime
import json
import sys
from pathlib import Path


def _snap_file(snap_dir: Path, day=None) -> Path:
    day = day or datetime.datetime.now().strftime("%Y%m%d")
    return snap_dir / ("%s.jsonl" % day)


def snapshot(target: Path, snap_dir: Path) -> int:
    if not target.is_file():
        print("[FAIL] 目标件不存在：%s" % target)
        return 3
    snap_dir.mkdir(parents=True, exist_ok=True)
    sf = _snap_file(snap_dir)
    rows = target.read_text(encoding="utf-8", errors="replace").splitlines()
    t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sf.open("a", encoding="utf-8", newline="\n") as fh:
        for n, line in enumerate(rows, 1):
            fh.write(json.dumps({"t": t, "path": str(target), "line_no": n, "text": line},
                                ensure_ascii=False) + "\n")
    print("-- snapshot 已追加：%d 行 ⇒ %s" % (len(rows), sf))
    return 0


def verify(target: Path, snippet: str, snap_dir: Path) -> int:
    sf = _snap_file(snap_dir)
    if not sf.is_file():
        print("[FAIL] 当日快照不存在：%s ⇒ **未快照即改动**（J13 违例）" % sf)
        return 1
    hit = 0
    for line in sf.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if snippet in rec.get("text", ""):
            hit += 1
    print("-- verify ｜ 件＝%s ｜ 片段＝%r ｜ 命中 %d 行" % (target.name, snippet[:40], hit))
    if hit:
        print("    ⇒ 旧文**可溯**（快照在案）")
        return 0
    print("    ⇒ **命中 0** ⇒ 禁写「原文保留供追溯」（J13：记录不实）")
    return 1


def selftest() -> int:
    import tempfile
    cases = []
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        tgt = d / "sample.md"
        tgt.write_text("第一行\n待删的那一句\n第三行\n", encoding="utf-8")
        snap = d / "snaps"
        # 【必红】未快照即 verify
        cases.append(("【必红】未快照即 verify ⇒ rc=1", verify(tgt, "待删的那一句", snap) == 1))
        # 快照后 verify 命中 ⇒ 0
        snapshot(tgt, snap)
        cases.append(("应绿·快照后 verify 命中 ⇒ rc=0", verify(tgt, "待删的那一句", snap) == 0))
        # 【必红】verify 不存在的片段
        cases.append(("【必红】片段不在快照 ⇒ rc=1", verify(tgt, "从未存在的一句话", snap) == 1))
        # 【必红】目标件缺失 ⇒ 3
        cases.append(("【必红】目标件缺失 ⇒ rc=3", snapshot(d / "nope.md", snap) == 3))
        # 只追加（快照两遍，行数应翻倍而非覆盖）
        n1 = len(_snap_file(snap).read_text(encoding="utf-8").splitlines())
        snapshot(tgt, snap)
        n2 = len(_snap_file(snap).read_text(encoding="utf-8").splitlines())
        cases.append(("应绿·只追加（两遍 = 2×）", n2 == 2 * n1))
    ok = True
    for name, r in cases:
        print("  [%s] %s" % ("OK" if r else "FAIL", name))
        ok = ok and r
    print("== selftest %s（%d 态）==" % ("全绿" if ok else "有红", len(cases)))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None, help="把该件逐行快照")
    ap.add_argument("--verify", default=None, help="校验件")
    ap.add_argument("--snippet", default=None, help="待校验的旧文片段")
    ap.add_argument("--snap-dir", default=None, help="快照目录（必填，或由 env WB_SNAPSHOT_DIR 提供）")
    ap.add_argument("--selftest", action="store_true", help="五态自检（含三条**必红**例）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    import os
    snap_dir = Path(a.snap_dir or os.environ.get("WB_SNAPSHOT_DIR") or "")
    if not str(snap_dir) or str(snap_dir) == ".":
        print("[FAIL] 需 --snap-dir（或 env WB_SNAPSHOT_DIR）")
        return 3
    if a.snapshot:
        return snapshot(Path(a.snapshot), snap_dir)
    if a.verify:
        if not a.snippet:
            print("[FAIL] --verify 须同时给 --snippet")
            return 3
        return verify(Path(a.verify), a.snippet, snap_dir)
    print("[FAIL] 需 --snapshot / --verify / --selftest 之一")
    return 3


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

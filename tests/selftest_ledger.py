#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""件 4 台账 · 夹具（覆盖设计稿 §四 判据 2/4/5/6/7/8 的可测部分）—— 件 4 已并入 `tools/curate.py`。

**批 3 收口（2026-10-01）**：件 4 已**并入** `curate.py`（子命令 `ledger append|show|verify`），
原 `curate_ledger.py` 退役 ⇒ 本夹具改指 `curate.py`，**判据 10 条不变**（合并判据＝本夹具 10/10 ＋ `selftest_curate.py` 23/23 同时全绿）。

判据1（同输入同输出）属「到期判定」——已由 `03_发行物/tools/ttl_sweep.py` 承担，不在本夹具范围。
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tools" / "curate.py"   # ← 合并后：件 2/3/4 同执行体（出厂位＝`tools/`）
LEDGER_CMD = "ledger"
PY = sys.executable


def run(args):
    r = subprocess.run([PY, "-B", str(TOOL), LEDGER_CMD] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def main():
    ok = fail = 0

    def check(name, cond, extra=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"[PASS] {name}")
        else:
            fail += 1
            print(f"[FAIL] {name}  {extra}")

    tmp = Path(tempfile.mkdtemp(prefix="kitledger_"))
    try:
        arc = tmp / "01-记忆档案"
        arc.mkdir(parents=True)
        item = arc / "条目A.md"
        item.write_text("---\nlayer: L2\ncreated: 2026-01-01\nttl: 30d\n---\n\n正文内容\n", encoding="utf-8")
        before = md5(item)

        rc, out = run(["append", "--root", str(tmp), "--action", "cool",
                       "--target", "01-记忆档案/条目A.md", "--frm", "active", "--to", "cooled",
                       "--operator", "姜姜", "--proposal-id", "P-1", "--snapshot", str(item)])
        check("append 成功", rc == 0, out[:250])
        # 判据 2：起草/追加不动记忆正文
        check("判据2 不动记忆正文（md5 不变）", md5(item) == before, f"before={before} after={md5(item)}")

        led = tmp / "_meta" / "curation" / "ledger.tsv"
        check("台账已建立", led.is_file())
        if led.is_file():
            n = len([l for l in led.read_text(encoding="utf-8").splitlines() if l.strip()])
            check("行数=2（表头+1 数据行）", n == 2, f"实际 {n}")

        snaps = list((tmp / "_meta" / "curation" / "hist").glob("*.snapshot"))
        check("判据5 前像已落 hist/ 且内容一致", len(snaps) == 1 and md5(snaps[0]) == before, f"{snaps}")

        b1 = md5(led)
        rc, out = run(["verify", "--root", str(tmp)])
        check("链条校验通过", rc == 0 and "链条完整" in out, out[-250:])
        check("verify 无副作用（只增/幂等侧面）", md5(led) == b1)

        rc, _ = run(["append", "--root", str(tmp), "--action", "retire",
                     "--target", "01-记忆档案/条目A.md", "--frm", "cooled", "--to", "archived",
                     "--operator", "姜姜", "--proposal-id", "P-2"])
        rc2, out2 = run(["verify", "--root", str(tmp)])
        check("两行链条完整", rc2 == 0, out2[-250:])

        # 判据 6 精神：任何改写都要能被检出
        lines = led.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace("\tcool\t", "\tdelete\t")
        led.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc3, out3 = run(["verify", "--root", str(tmp)])
        check("判据6 篡改台账被检出（rc=1 + FAIL）", rc3 == 1 and "FAIL" in out3, out3[-250:])

        # 判据 8：零依赖零网
        src = TOOL.read_text(encoding="utf-8")
        banned = [w for w in ("import socket", "import urllib", "import http", "import requests", "urlopen") if w in src]
        check("判据8 无网络导入", not banned, str(banned))

        print(f"\n==== 夹具结果：PASS {ok} ／ FAIL {fail} ====")
        return 0 if fail == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

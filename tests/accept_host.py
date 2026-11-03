#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宿主侧焊点验收 —— 把「宿主能不能调套件命令」变成**三条可复跑命令 ＋ 一段可粘话术**

## 为什么单独一支（`O-143` · 承 `adapters/CONTRACT.md` §八）

五焊点里 A（注入）已在母体焊牢；**B（写触发）在无钩子宿主上永远是「自觉项」，不假装是机制**；
真正能测的是 **C 检索／D 确认／E 删除触达** —— 而它们的判据都长一个样：
**「宿主的会话里，能不能把这条命令跑出来，并看见它该有的输出」**。

过去这件事卡在**没人知道该跑什么**（`NOTES.md` 里写着「宿主侧未测」，但没给可复跑件）。
本支把「套件侧那一半」自动化，并把「宿主侧那一半」压成**一段可粘的话术**（`--emit-host-prompt`）。

## 诚实边界（写在最前面）

- 本支跑通 ⇒ 只证明「**套件侧前提已备**」＋「**命令在套件环境可用**」
- **不等于「宿主侧已焊」** —— 宿主侧必须**在那个宿主的会话里**跑一遍同样三条（用 `--emit-host-prompt` 取话术）
- ⇒ `NOTES.md` 的状态列在宿主侧真跑之前，**只能标 ⏳**（承「未实测禁标已焊」）

## 用法

  python tests/accept_host.py --root <库根>
  python tests/accept_host.py --root <库根> --json
  python tests/accept_host.py --emit-host-prompt --root <库根>
  python tests/accept_host.py --selftest

退出码：0 套件侧三项全通 ｜ 1 有不通 ｜ 3 参数/IO 错
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
PY = sys.executable


def _run(args, cwd=None):
    cp = subprocess.run([PY, "-B"] + args, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", cwd=cwd)
    return cp.returncode, ((cp.stdout or "") + (cp.stderr or ""))


def _tree_md5(root: Path) -> str:
    h = hashlib.md5()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in str(p):
            h.update(str(p.relative_to(root)).encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


# ── C 检索 ──────────────────────────────────────────────────────────────────
def check_c(root: Path, kw="记忆"):
    rc, out = _run([str(KIT / "tools" / "memory.py"), "--root", str(root), "search", kw])
    m = re.search(r"命中\s*(\d+)\s*处", out)
    n = int(m.group(1)) if m else 0
    return {"ok": rc == 0 and n > 0, "hits": n, "kw": kw,
            "detail": f"`memory search {kw}` → 扫描/命中：{(out.strip().splitlines() or [''])[0][:80]}"}


# ── D 确认 ──────────────────────────────────────────────────────────────────
def check_d(root: Path):
    rc, out = _run([str(KIT / "tools" / "curate.py"), "state", "--root", str(root)])
    m = re.search(r"pending_proposals[：:]\s*(\d+)", out)
    pend = int(m.group(1)) if m else -1
    # 速读包首行「待确认：N 条」须与它一致
    fp = root / "01-记忆档案" / "记忆工程" / "会话速读包.md"
    shown = None
    if fp.is_file():
        for ln in fp.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
            mm = re.search(r"待确认[^\d]{0,6}(\d+)\s*条", ln)
            if mm:
                shown = int(mm.group(1))
                break
    return {"ok": rc == 0 and pend >= 0 and (shown is None or shown == pend),
            "pending": pend, "shown_in_digest": shown,
            "detail": f"`curate state` pending_proposals={pend} ｜ 速读包首行显示={shown}"
                      + ("" if shown is None else ("（一致）" if shown == pend else "（**不一致**）"))}


# ── E 删除触达（在**临时副本**上跑，绝不碰真库）──────────────────────────────
def check_e(root: Path):
    tmp = Path(tempfile.mkdtemp(prefix="purge_"))
    try:
        copy = tmp / "lib"
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns("__pycache__", "_run"))
        tgt = copy / "01-记忆档案" / "验收夹具-待删.md"
        tgt.write_text("# 验收夹具\n\n本件只为验证删除链路，跑完即弃。\n", encoding="utf-8")
        rel = "01-记忆档案/验收夹具-待删.md"

        rc1, o1 = _run([str(KIT / "tools" / "purge.py"), "purge", "--root", str(copy),
                        "--target", rel, "--preview"])
        # ★ 2026-10-25 实测：`--yes` 必须回贴执行凭证 `--receipt-fingerprint`，
        #   首次无回执时传字面量 `NEW`（否则工具按设计拒执行 —— 这是它的防误删闸）。
        rc2, o2 = _run([str(KIT / "tools" / "purge.py"), "purge", "--root", str(copy),
                        "--target", rel, "--yes", "--operator", "accept-host",
                        "--receipt-fingerprint", "NEW"])
        gone = not tgt.exists()
        rc3, o3 = _run([str(KIT / "tools" / "purge.py"), "audit", "--root", str(copy),
                        "--target", rel])
        # ★ 2026-10-25 实测校正：**「回执」长在 `purge --yes` 的输出里**（`[OK] 已删 N 件…｜回执 N 行｜链完整`），
        #   **不在 audit**；audit 的正判据是「本库根内**不可达**」＋四类计数全 0。
        #   首版把回执判据挂在 audit 上 ⇒ 假负（跑通了却报 False）。
        receipt = ("回执" in o2) and ("链完整" in o2)
        # audit 的终判句就是「本库根内**不可达**」；四类计数是它内部细节，不重复解析（少一个易错点）
        unreachable = "不可达" in o3
        ok = (rc1 == 0) and (rc2 == 0) and gone and (rc3 == 0) and receipt and unreachable
        return {"ok": ok, "preview_rc": rc1, "yes_rc": rc2, "audit_rc": rc3,
                "file_gone": gone, "purge_has_receipt": receipt, "audit_unreachable": unreachable,
                "detail": f"preview rc={rc1} → --yes rc={rc2}（回执 {receipt}）→ 件消失={gone}"
                          f" → audit rc={rc3}（不可达 {unreachable}）"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HOST_PROMPT = """\
请在你的环境里依次执行下面三条命令，**原样贴回输出**（不要总结、不要改写）：

1) 检索（焊点 C）
   python "{tools}/memory.py" --root "{root}" search 记忆
   期望：出现「命中 N 处」，N > 0

2) 确认队列（焊点 D）
   python "{tools}/curate.py" state --root "{root}"
   期望：出现「pending_proposals：N」，且与速读包首行「待确认：N 条」一致

3) 删除触达（焊点 E · **请在你自己库的副本上做，别删真库**）
   python "{tools}/purge.py" purge --root "<副本根>" --target "<一条测试条目相对路径>" --preview
   python "{tools}/purge.py" purge --root "<副本根>" --target "<同上>" --yes --operator "<你的名字>"
   python "{tools}/purge.py" audit --root "<副本根>" --target "<同上>"
   期望：preview 给出将要删什么 → --yes 后文件消失 → audit 出示**回执**

三条都贴回输出后，我据此把 `adapters/<你>/NOTES.md` 的焊点状态由 ⏳ 改 ✅。
"""


def selftest() -> int:
    """夹具库：造最小结构，三项都应能跑通（E 项在自己的副本上）。"""
    fails = 0
    td = Path(tempfile.mkdtemp(prefix="acc_"))
    try:
        lib = td / "lib"
        (lib / "01-记忆档案" / "记忆工程").mkdir(parents=True)
        (lib / "01-记忆档案" / "SOUL.md").write_text("# 灵魂\n\n记忆必须有来源。\n", encoding="utf-8")
        (lib / "01-记忆档案" / "记忆工程" / "会话速读包.md").write_text(
            "# 速读包\n\n> **待确认**：0 条\n", encoding="utf-8")
        c = check_c(lib)
        print(f"  态1 C 检索            → {'PASS' if c['ok'] else 'FAIL'}（hits={c['hits']}）")
        fails += 0 if c["ok"] else 1
        d = check_d(lib)
        print(f"  态2 D 确认（口径一致）  → {'PASS' if d['ok'] else 'FAIL'}（pending={d['pending']} shown={d['shown_in_digest']}）")
        fails += 0 if d["ok"] else 1
        before = _tree_md5(lib)
        e = check_e(lib)
        after = _tree_md5(lib)
        print(f"  态3 E 删除触达（副本上） → {'PASS' if e['ok'] else 'FAIL'}（{e['detail']}）")
        fails += 0 if e["ok"] else 1
        ok4 = before == after
        print(f"  态4 真库零改动（E 不碰真库）→ {'PASS' if ok4 else 'FAIL'}")
        fails += 0 if ok4 else 1
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print(f"== 结果：{'全绿' if not fails else f'失败 {fails} 项'}（4 态）")
    return 0 if not fails else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--emit-host-prompt", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    if not a.root:
        print("[FAIL] 需要 --root（或用 --selftest）")
        return 3
    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"[FAIL] 库根不存在：{root}")
        return 3

    if a.emit_host_prompt:
        print(HOST_PROMPT.format(tools=(KIT / "tools").as_posix(), root=root.as_posix()))
        return 0

    print(f"==== 宿主侧焊点验收（**套件侧**那一半）｜ 库根 {root}")
    print("-- 判据：C 检索有命中／D 确认口径一致／E 删除链出回执；E 全程在临时副本上跑")
    c, d, e = check_c(root), check_d(root), check_e(root)
    for tag, r in (("C 检索", c), ("D 确认", d), ("E 删除触达", e)):
        print(f"  [{'OK' if r['ok'] else 'FAIL'}] {tag}  —— {r['detail']}")
    ok = c["ok"] and d["ok"] and e["ok"]
    if a.json:
        print(json.dumps({"root": str(root), "C": c, "D": d, "E": e, "kit_side_ok": ok},
                         ensure_ascii=False))
    print(f"==== 套件侧：{'✅ 三项全通' if ok else '❌ 有不通项'}")
    print("==== 宿主侧：⏳ **未测**（真跑要在那个宿主的会话里执行；取话术 ⇒ `--emit-host-prompt`）")
    return 0 if ok else 1


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

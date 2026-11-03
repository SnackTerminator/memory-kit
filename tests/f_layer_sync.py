#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F 层分叉检测 —— 「在用的那份」与「要发的那份」是不是同一份？

**它治什么**（`L1206`）：`v0.1.26` 为「库根自足」把 F 层**部署进库**，此后同一个内容
有了**两份物理副本**（出厂真源 `03_发行物/` ＋ 库内镜像），而**没有任何闸比对过它们**。
9 天后实测：同名 58 件中 **21 件内容不同**、库根另缺 3 件 —— 没有一条命令报过。
⇒ **「部署一次」只保证那一天一致；之后必须有会变红的信号。**

用法：
  python tests/f_layer_sync.py --src <出厂根> --mirror <库根>
  python tests/f_layer_sync.py --src ... --mirror ... --json
  python tests/f_layer_sync.py --selftest

退出码：0 **一致** ｜ 1 **有分叉** ｜ 3 参数/IO 错

**判据设计（四条，均有外部依据 · 2026-10-25 检索吸收）**
 1. **相对路径配对**（不用文件名配对）—— 文件名唯一时才可用后者；
 2. **两段式**：**先比件集合**（谁缺谁多），再比内容 —— 件集不齐时谈内容无意义；
 3. **三类分流**：`DIFF` 内容不同 ／ `ONLY-SRC` 镜像缺 ／ `ONLY-MIRROR` 镜像多；
 4. **排除面显式**（`MIRROR_SKIP`／`SRC_SKIP`），禁隐式跳过 —— 跳过什么必须写在码里看得见。

**它不做什么**：不判「哪边对」。两侧 `mtime/size` 只作参考打印；**方向由人裁**。
（自动回流＝写动作，超出本件职责，也超出"只读检测"的安全边界。）
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# ── 排除面（显式 · 禁隐式跳过）──────────────────────────────────────────────
# 镜像侧（库根）独有、**不属于 F 层**的东西：I 层实例、运行态、派生物。
MIRROR_SKIP = (
    "01-记忆档案/",        # I 层：每用户专属，永不进发行物（MANIFEST §⑤-1）
    "_run/",               # 运行态（S2 分治后的家）
    "08-检索索引/",        # 可重建派生物
    "CHECKSUMS.tsv",       # 库实例基线（carry_check 用），属 I 层派生物
    "_hist/",
    "_归档/",
    # ★ 2026-11-03 补（`O-152`）：这两类属**实例侧 L1／L3**，镜像本来就会有、真源永远没有。
    #   缺它们时实测报 4 件 ONLY-MIRROR（`02-工作日志/流水/…`、`_meta/curation/*`）⇒ 噪声。
    #   判据：真源里不存在同名目录（`ls 03_发行物/02-工作日志` 应为 No such file）。
    "02-工作日志/",        # L1：当日流水（session_flow 写）
    "_meta/",              # L3：curation 提案与状态（可重建）
)
# 真源（出厂根）里**设计上不装进库根**的件（装了会在库内造第二个 01-记忆档案 ⇒ 踩 MANIFEST ⓪）
SRC_SKIP = (
    "kernel-skeleton/",
    "examples/",
)
SKIP_SUFFIX = (".bak", ".corrupted", ".tmp", ".orig", ".rej")
SKIP_NAME_CONTAINS = (".bak_", ".corrupted_", "__pycache__")


def _skip(rel: str, prefixes) -> bool:
    r = rel.replace("\\", "/")
    if any(r.startswith(p) for p in prefixes):
        return True
    if any(r.endswith(s) for s in SKIP_SUFFIX):
        return True
    return any(k in r for k in SKIP_NAME_CONTAINS)


ALLOW_FILE = "f_layer_sync.allow"


def load_allow(src: Path):
    """读「有意差异」白名单（同目录 f_layer_sync.allow）。

    为什么需要它：库根与出厂**有些件本来就该不同**（如 README：库根讲「这套库怎么用」、
    出厂讲「这套件怎么装」）。没有白名单 ⇒ 每条有意差异都报红 ⇒ **信号很快归零**
    （`MANIFEST §⑤-2` 每跑必红的同一个教训）。
    但白名单**不能是黑箱**：命中项仍单列 `ALLOW` 段打印出来，看得见才不会变成"静默跳过"。
    """
    f = Path(__file__).resolve().parent / ALLOW_FILE   # 与本脚本同目录（tests/），不随 --src 变
    out = {}
    if not f.is_file():
        print(f"-- 提示：未见白名单 {f}（全部差异按分叉计）")
        return out
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.split("#", 1)[0].strip()
        if not s:
            continue
        out[s] = (ln.split("#", 1)[1].strip() if "#" in ln else "")
    return out


def _walk(base: Path, prefixes):
    """返回 {相对路径: 绝对路径}；相对路径配对（外部实践：relative-path pairing 最稳）。"""
    out = {}
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            p = Path(dp) / fn
            rel = str(p.relative_to(base)).replace("\\", "/")
            if _skip(rel, prefixes):
                continue
            out[rel] = p
    return out


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def compare(src: Path, mirror: Path, allow=None) -> dict:
    allow = allow or {}
    s = _walk(src, SRC_SKIP)
    m = _walk(mirror, MIRROR_SKIP)

    # 第一段：件集合（先齐，再谈内容）
    only_src = sorted(set(s) - set(m))
    only_mirror = sorted(set(m) - set(s))
    common = sorted(set(s) & set(m))

    # 第二段：内容
    diff, allow_hit = [], []
    for rel in common:
        try:
            if _md5(s[rel]) != _md5(m[rel]):
                if rel in allow:
                    allow_hit.append({"path": rel, "why": allow[rel]})
                    continue
                diff.append({
                    "path": rel,
                    "src_size": s[rel].stat().st_size,
                    "mirror_size": m[rel].stat().st_size,
                    "src_mtime": int(s[rel].stat().st_mtime),
                    "mirror_mtime": int(m[rel].stat().st_mtime),
                })
        except OSError as e:
            diff.append({"path": rel, "error": str(e)})

    return {
        "src": str(src), "mirror": str(mirror),
        "src_files": len(s), "mirror_files": len(m),
        "common": len(common),
        "only_src": only_src, "only_mirror": only_mirror, "diff": diff,
        "allow_hit": allow_hit,
        "ok": not (only_src or only_mirror or diff),
    }


def report(r: dict) -> None:
    print(f"==== F 层分叉检测 ｜ 真源 {r['src']}")
    print(f"                    镜像 {r['mirror']}")
    print(f"-- 点名观察对象：真源 {r['src_files']} 件 ｜镜像 {r['mirror_files']} 件 ｜同名 {r['common']} 件")
    if r.get("allow_hit"):
        print(f"-- 有意差异白名单命中 {len(r['allow_hit'])} 件（**不计分叉**，但列出来看得见）：")
        for d in r["allow_hit"]:
            print(f"        · {d['path']}  ← {d['why'] or '（白名单未写理由 · 建议补）'}")
    if r["ok"]:
        print("  [OK] 一致 —— 同名件内容全同、无缺无多" +
              ("（另有白名单放行件，见上）" if r.get("allow_hit") else ""))
        return
    if r["diff"]:
        print(f"  [DIFF] 内容不同 {len(r['diff'])} 件（**按字节比，含行尾差异**）：")
        for d in r["diff"][:12]:
            if "error" in d:
                print(f"        · {d['path']}  ← 读取失败：{d['error']}")
            else:
                newer = "镜像较新" if d["mirror_mtime"] > d["src_mtime"] else (
                    "真源较新" if d["src_mtime"] > d["mirror_mtime"] else "同时刻")
                print(f"        · {d['path']}  {d['src_size']}B→{d['mirror_size']}B  {newer}")
        if len(r["diff"]) > 12:
            print(f"        … 另 {len(r['diff']) - 12} 件（--json 取全）")
    if r["only_src"]:
        print(f"  [ONLY-SRC] 镜像缺 {len(r['only_src'])} 件（真源有、镜像无）：")
        for p in r["only_src"][:12]:
            print(f"        · {p}")
        if len(r["only_src"]) > 12:
            print(f"        … 另 {len(r['only_src']) - 12} 件")
    if r["only_mirror"]:
        print(f"  [ONLY-MIRROR] 镜像多 {len(r['only_mirror'])} 件（镜像有、真源无）：")
        for p in r["only_mirror"][:12]:
            print(f"        · {p}")
        if len(r["only_mirror"]) > 12:
            print(f"        … 另 {len(r['only_mirror']) - 12} 件")
    print("==== 结论：❌ 有分叉（**方向由人裁**；本件只报事实，不自动回流）")


def selftest() -> int:
    """三态：一致 ⇒ 绿；内容改一件 ⇒ DIFF；删一件 ⇒ ONLY-SRC。"""
    import shutil
    import tempfile
    fails = 0
    tmp = Path(tempfile.mkdtemp(prefix="fls_"))
    try:
        s = tmp / "src"
        m = tmp / "mirror"
        for d in (s, m):
            (d / "spec").mkdir(parents=True)
            (d / "VERSION").write_text("0.1.34\n", encoding="utf-8")
            (d / "spec" / "a.md").write_text("甲\n", encoding="utf-8")
        # 态 1：一致
        r = compare(s, m)
        ok1 = r["ok"]
        print(f"  态1 一致            → {'PASS' if ok1 else 'FAIL'}")
        fails += 0 if ok1 else 1
        # 态 2：内容改一件 ⇒ DIFF
        (m / "spec" / "a.md").write_text("乙\n", encoding="utf-8")
        r = compare(s, m)
        ok2 = (not r["ok"]) and len(r["diff"]) == 1 and r["diff"][0]["path"] == "spec/a.md"
        print(f"  态2 改一件          → {'PASS' if ok2 else 'FAIL'}（DIFF={len(r['diff'])}）")
        fails += 0 if ok2 else 1
        # 态 3：镜像缺一件 ⇒ ONLY-SRC
        (m / "VERSION").unlink()
        r = compare(s, m)
        ok3 = (not r["ok"]) and r["only_src"] == ["VERSION"]
        print(f"  态3 缺一件          → {'PASS' if ok3 else 'FAIL'}（ONLY-SRC={r['only_src']}）")
        fails += 0 if ok3 else 1
        # 态 4：镜像侧 I 层不参与比对（MIRROR_SKIP 生效）
        (m / "01-记忆档案").mkdir()
        (m / "01-记忆档案" / "SOUL.md").write_text("我的灵魂\n", encoding="utf-8")
        r = compare(s, m)
        ok4 = not any(p.startswith("01-记忆档案/") for p in r["only_mirror"])
        print(f"  态4 I 层不算分叉     → {'PASS' if ok4 else 'FAIL'}")
        fails += 0 if ok4 else 1
        # 态 5：真源侧骨架不参与比对（SRC_SKIP 生效）
        (s / "kernel-skeleton").mkdir()
        (s / "kernel-skeleton" / "x.md").write_text("骨架\n", encoding="utf-8")
        r = compare(s, m)
        ok5 = not any(p.startswith("kernel-skeleton/") for p in r["only_src"])
        print(f"  态5 骨架不算缺件     → {'PASS' if ok5 else 'FAIL'}")
        fails += 0 if ok5 else 1
        # 态 7：白名单命中 ⇒ 不算分叉
        (m / "spec" / "a.md").write_text("丙\n", encoding="utf-8")
        r0 = compare(s, m)
        r1 = compare(s, m, {"spec/a.md": "自检：故意不同"})
        ok7 = (len(r0["diff"]) == 1) and (len(r1["diff"]) == 0) and len(r1["allow_hit"]) == 1
        print(f"  态7 白名单放行       → {'PASS' if ok7 else 'FAIL'}")
        fails += 0 if ok7 else 1
        (m / "spec" / "a.md").write_text("甲\n", encoding="utf-8")

        # 态 6：.bak 不入比对
        (m / "spec" / "a.md.bak_20261025_0000_HOST").write_text("旧\n", encoding="utf-8")
        r = compare(s, m)
        ok6 = not any(".bak_" in p for p in r["only_mirror"])
        print(f"  态6 备份件不算多件   → {'PASS' if ok6 else 'FAIL'}")
        fails += 0 if ok6 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"== 结果：{'全绿' if not fails else f'失败 {fails} 项'}（7 态）")
    return 0 if not fails else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="真源根（出厂内容，如 03_发行物/）")
    ap.add_argument("--mirror", help="镜像根（库根）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    if not (a.src and a.mirror):
        print("[FAIL] 需要 --src 与 --mirror（或用 --selftest）")
        return 3
    src, mirror = Path(a.src).resolve(), Path(a.mirror).resolve()
    for p, nm in ((src, "--src"), (mirror, "--mirror")):
        if not p.is_dir():
            print(f"[FAIL] {nm} 不是目录：{p}")
            return 3
    r = compare(src, mirror, load_allow(src))
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        report(r)
    return 0 if r["ok"] else 1


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

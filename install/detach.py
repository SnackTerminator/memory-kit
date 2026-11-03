#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""撤出检查 —— 「这套东西在我机器上留了什么，怎么撤干净？」

## 为什么要有它（`O-144`）

套件的卖点是「**插上就用**」，但**只有承诺能拔干净，人才敢插**。
实测缺口（2026-10-25）：`install/` 只有 `init_instance`／`pack`／`verify` 三支；
全树 `detach|卸载|撤出|uninstall` **零命中**；`spec/对外承诺.md` 三条承诺
**没有一条管「从宿主撤出」** —— 删的是**库内条目**，不是**宿主侧痕迹**。

## 它做什么（以及**坚决不做什么**）

**做**：按 `adapters/<host>/manifest.json` 声明的接入形态（`adapterShape`），
列出「**本机会留下什么**」四类痕迹，并给每类**可复跑的验证命令**。

**不做**（三条硬边界，写死在这里）：
1. **不删除任何东西** —— 连 `--apply` 也只**打印**该删什么，不落手
   （承既有口径「删除只以提案形式出现」，`spec/本库内删除可复核.md`）
2. **不写任何文件** —— 本件全程只读；要改由人按提案自己动
3. **不硬编码宿主路径** —— 跨机件禁写死盘符与用户名（承 `E630`）；
   宿主侧一律给**带占位符的命令**，由使用者在自己的机器上跑

## 用法

  python install/detach.py --root <库根>
  python install/detach.py --root <库根> --json
  python install/detach.py --selftest

退出码：0 正常出清单 ｜ 3 参数/IO 错
"""
import argparse
import json
import os
import sys
from pathlib import Path

# ── 四类痕迹（与 docs/撤出.md 的表格一一对应，改这里必须同步改那件）─────────
CATEGORIES = [
    ("A", "库目录本身", "套件的全部内容都在这一个目录里 —— **删目录＝撤干净**（无安装到系统）"),
    ("B", "库内运行态与派生物", "`instance/`／`_run/`／`08-检索索引/`／`CHECKSUMS.tsv` —— 可重建，删了不丢记忆"),
    ("C", "宿主侧接线（仅 wired-inject 形态）", "注入钩子／每轮注入行／环境变量 —— **这一层在库外**，删库不会自动清"),
    ("D", "宿主侧配置文件里的引用", "宿主配置里若写过本库路径（如 settings），属**残留引用**，需人工核"),
]


def _size(p: Path) -> int:
    return p.stat().st_size if p.is_file() else 0


def scan(root: Path) -> dict:
    """只读扫描：返回 {'hosts': [...], 'dirs': {...}, 'files': {...}, 'counts': {...}}"""
    hosts = []
    adir = root / "adapters"
    if adir.is_dir():
        for m in sorted(adir.glob("*/manifest.json")):
            try:
                j = json.loads(m.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            hosts.append({
                "host": m.parent.name,
                "shape": j.get("adapterShape", "(未声明)"),
                "wiring": list((j.get("wiring") or {}).keys()) if isinstance(j.get("wiring"), dict) else [],
                "entry": j.get("entry", ""),
            })

    dirs = {}
    for d in ("instance", "_run", "08-检索索引", "01-记忆档案"):
        p = root / d
        dirs[d] = {"exists": p.is_dir(),
                   "files": sum(1 for _ in p.rglob("*") if _.is_file()) if p.is_dir() else 0}
    # ★ 只把「可重建/可弃」的件列入 B 类。
    #   `carrier.yaml`（实例身份）与 `VERSION` **不在此列** —— 前者是"这个库是谁"的凭据、
    #   后者是版本锚点，都不属运行态（2026-10-25 首版曾误列入，实跑时发现会误导）。
    files = {}
    for f in ("CHECKSUMS.tsv",):
        p = root / f
        files[f] = {"exists": p.is_file(), "bytes": _size(p)}

    total = sum(1 for p in root.rglob("*") if p.is_file())
    md = sum(1 for p in root.rglob("*.md") if p.is_file())
    return {"root": str(root), "hosts": hosts, "dirs": dirs, "files": files,
            "counts": {"files": total, "md": md}}


def report(r: dict) -> None:
    print(f"==== 撤出检查（只读）｜ 库根 {r['root']}")
    print(f"-- 点名观察对象：{r['counts']['files']} 件（其中 .md {r['counts']['md']} 件）")
    wired = [h for h in r["hosts"] if h["shape"] == "wired-inject"]
    bare = [h for h in r["hosts"] if h["shape"] != "wired-inject"]
    print(f"-- 接入形态：wired-inject {len(wired)} 个{'（' + '、'.join(h['host'] for h in wired) + '）' if wired else ''}"
          f" ｜bare-read {len(bare)} 个{'（' + '、'.join(h['host'] for h in bare) + '）' if bare else ''}")

    for code, name, why in CATEGORIES:
        print(f"\n[{code}] {name}")
        print(f"    为什么：{why}")
        if code == "A":
            print(f"    现状：{r['counts']['files']} 件")
            print("    撤：整个目录移走或删除（**先确认记忆已另存**）；验证＝目录不存在即干净")
            print("    边界：本套件**无系统级安装**（不写注册表／不装服务／不加 PATH）")
            print("    不属撤出范围：`01-记忆档案/`（记忆本体）｜`carrier.yaml`（实例身份）｜`VERSION`（版本锚点）")
        elif code == "B":
            for d, v in r["dirs"].items():
                if d == "01-记忆档案":
                    continue
                print(f"    · {d}/  {'在位，' + str(v['files']) + ' 件' if v['exists'] else '不在'}"
                      + ("　⇒ 可整目录删（派生物／运行态）" if v["exists"] else ""))
            for f, v in r["files"].items():
                print(f"    · {f}  {'在位 ' + str(v['bytes']) + ' B' if v['exists'] else '不在'}"
                      + ("　⇒ 删了会丢基线，重建＝重跑 carry_check --write-baseline" if f == "CHECKSUMS.tsv" and v["exists"] else ""))
            print("    ⚠ `01-记忆档案/` **不属撤出范围** —— 那是你的记忆本体，撤出时不删")
        elif code == "C":
            if not wired:
                print("    本库当前**无 wired-inject 形态的宿主** ⇒ 本类不适用（裸库直读＝宿主侧零痕迹）")
            for h in wired:
                print(f"    · {h['host']}：接线项 {('、'.join(h['wiring']) or '(未声明)')}")
                print("      撤：到该宿主配置里**删掉指向本库的钩子条目** ⇒ 验证＝宿主新会话不再出现注入行")
                print("      验证命令（占位符自己填）：<宿主配置目录> 下搜本库路径，命中 0 即撤净")
        elif code == "D":
            print("    撤：在宿主配置目录里搜本库路径（命令示例见 docs/撤出.md §D）")
            print("    验证＝命中 0 ⇒ 无残留引用")
    print("\n==== 本工具**未删除任何文件**（连 --apply 也只打印）")
    print("==== 逐类撤销步骤与验证命令 → docs/撤出.md")


def selftest() -> int:
    import shutil
    import tempfile
    fails = 0
    td = Path(tempfile.mkdtemp(prefix="detach_"))
    try:
        (td / "01-记忆档案").mkdir(parents=True)
        (td / "01-记忆档案" / "SOUL.md").write_text("# 灵魂\n", encoding="utf-8")
        (td / "adapters" / "h1").mkdir(parents=True)
        (td / "adapters" / "h1" / "manifest.json").write_text(
            json.dumps({"adapterShape": "wired-inject", "wiring": {"read": "x", "writebackGate": "y"},
                        "entry": "AGENTS.md"}), encoding="utf-8")
        (td / "adapters" / "h2").mkdir(parents=True)
        (td / "adapters" / "h2" / "manifest.json").write_text(
            json.dumps({"adapterShape": "bare-read"}), encoding="utf-8")
        (td / "_run").mkdir()
        (td / "_run" / "log.txt").write_text("x", encoding="utf-8")
        r = scan(td)
        ok1 = len(r["hosts"]) == 2
        print(f"  态1 读到 2 个宿主声明     → {'PASS' if ok1 else 'FAIL'}（实到 {len(r['hosts'])}）")
        fails += 0 if ok1 else 1
        ok2 = r["dirs"]["_run"]["exists"] and r["dirs"]["_run"]["files"] == 1
        print(f"  态2 探测到 _run 1 件      → {'PASS' if ok2 else 'FAIL'}")
        fails += 0 if ok2 else 1
        ok3 = r["dirs"]["instance"]["exists"] is False
        print(f"  态3 不存在的目录不误报     → {'PASS' if ok3 else 'FAIL'}")
        fails += 0 if ok3 else 1
        ok4 = any(h["shape"] == "wired-inject" for h in r["hosts"])
        print(f"  态4 认出 wired-inject     → {'PASS' if ok4 else 'FAIL'}")
        fails += 0 if ok4 else 1
        # 态5：全流程不得改动任何文件（md5 前后一致）
        import hashlib
        before = hashlib.md5(b"".join(sorted(p.read_bytes() for p in td.rglob("*") if p.is_file()))).hexdigest()
        scan(td)
        after = hashlib.md5(b"".join(sorted(p.read_bytes() for p in td.rglob("*") if p.is_file()))).hexdigest()
        ok5 = before == after
        print(f"  态5 只读（全树指纹不变）   → {'PASS' if ok5 else 'FAIL'}")
        fails += 0 if ok5 else 1
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print(f"== 结果：{'全绿' if not fails else f'失败 {fails} 项'}（5 态）")
    return 0 if not fails else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="保留参数但**只打印不执行**（本工具永不删除，见件头三条硬边界）")
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
    r = scan(root)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        report(r)
        if a.apply:
            print("\n[--apply] 已收到，但**本工具不执行删除** —— 上面每类条目即提案，请人工核对后自行操作。")
    return 0


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态一致性闸（F 类 · 零依赖 · 只读）—— 治「状态源失真」人眼守不住的那五类面。

为什么需要它（承项目审查 P0-3 ／ Hermes 第 1 问②「全清单唯一防复发杠杆项」）：
  批 0「归真批」修的三处矛盾**长期无人发现**；Hermes 复跑 10 组命令即抓出
  「22 处实为 26」「1 处实为 2」两处计数不符 ⇒ **人眼回扫不可作验收基准**。
  ⇒ 对策略：把这些断言收成**一条命令**，每次打包前必跑。

判据（六类机器面 · 任一红即 FAIL）：
  ① 版本四面一致：`VERSION` 首行 == `CHANGELOG` 首条 == `README` 版本行 == `发行物清单` §四 套件版本
  ② 发行包指纹：`06_发行包/` 恰一个 `*.zip`；其 size ／ md5 与「声明处」逐字一致
     （声明处长在**项目根 README**，出厂包内不可见 ⇒ 取不到即 SKIP＋WARN，不判红）
  ③ 禁物：套件树下不得有 `*.downloading` ／ `__pycache__` ／ `*.pyc` ／ `*.bak*`
  ④ 白名单路径实体存在：`发行物清单.md` §一 每行在套件树下存在（清单件自指除外）
  ⑤ 叙述类声称须带指向件：受限强断言词（`唯一可行`／`唯一全绿`／`业界首个`／`首创`）
     须在**同行或上一行**出现指向件标记（`§` ／ `.md` ／ `.json` ／ `L##` ／ 目录名）
     ⇒ 无指向即红。**基线豁免**见 `KNOWN_EXCEPTIONS`（各带**到期项**，不是永久豁免）。
  ⑥ 文档面版本串一致（2026-10-02 加 · `O-114` ①）：件内 `memory-kit-<x.y.z>` 须 == 当前版本；
     **排除** `CHANGELOG.md`／`发行物清单.md`（历史 append 台账）／`tests/`（夹具）。
     治「同源漂移」第 3 次（示例包名三轮 bump 两轮漏改）。

用法：
  python tests/state_consistency.py                      # 全跑（套件根＝本脚本上一级）
  python tests/state_consistency.py --root <套件根> --repo-root <项目根>
  python tests/state_consistency.py --selftest           # 本闸自检（必红例 ＋ 正确态）

退出码：0 全绿 ｜ 1 有红 ｜ 3 参数/IO 错
"""
import argparse
import hashlib
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

VER_RE = re.compile(r"\d+\.\d+\.\d+")
CLAIM_WORDS = ("唯一可行", "唯一全绿", "业界首个", "首创")
POINT_RE = re.compile(r"§|\.md|\.json|\.py|L\d+|spec/|docs/|tools/|adapters/|install/|kernel-skeleton/|发行物清单|MANIFEST")
JUNK_DIRS = ("__pycache__",)

# ★ 基线豁免（**不是永久豁免**）：每条须带「到期」。到期项统一并入「下次 bump 合批清单」。
# ★ 2026-10-01 `v0.1.3` bump 时**已清空**：原两条（`adapters/hermes/manifest.json` 的「唯一全绿宿主」／
#   `MANIFEST.md` 的「对账法（唯一可行）」）**已于 `v0.1.2` 改述完毕** ⇒ 豁免**失效**，实证＝判据⑤
#   在两处目标行上已不再命中（保留空豁免即「机制走一半」：会让将来的强断言误借旧豁免通过）。
KNOWN_EXCEPTIONS = ()


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------- ① 版本四面 ----------
def v_version(kit: Path):
    line = (_read(kit / "VERSION").splitlines() or [""])[0].strip()
    m = VER_RE.search(line)
    return m.group(0) if m else None


def v_changelog(kit: Path):
    for ln in _read(kit / "CHANGELOG.md").splitlines():
        if ln.startswith("## ["):
            m = VER_RE.search(ln)
            return m.group(0) if m else None
    return None


def v_readme(kit: Path):
    m = re.search(r"\*\*版本\*\*\s*：\s*\*\*(\d+\.\d+\.\d+)\*\*", _read(kit / "README.md"))
    return m.group(1) if m else None


def v_manifest(kit: Path):
    m = re.search(r"套件版本\s*＝\s*`(\d+\.\d+\.\d+)`", _read(kit / "发行物清单.md"))
    return m.group(1) if m else None


def v_json_version(p: Path):
    """取 JSON 件内的 "version" 字段（**2026-10-01 补 · 治「版本面 8 处中 4 处不在闸内」**）。
    由来：外部评审实测 —— `v0.1.4` 包内两处 `adapters/*/manifest.json` **停在 `0.1.3`** 而
    本闸判①仍绿（原判据①只看 VERSION／CHANGELOG／README／发行物清单 四面）⇒ 纳管。"""
    m = re.search(r'"version"\s*:\s*"(\d+\.\d+\.\d+)"', _read(p))
    return m.group(1) if m else None


def check_versions(kit: Path):
    got = {"VERSION": v_version(kit), "CHANGELOG": v_changelog(kit),
           "README": v_readme(kit), "发行物清单": v_manifest(kit)}
    # 2026-10-01 补：JSON 版本面（manifest×2 ＋ cli-spec）—— **件在则纳入、不在则跳过**
    # （夹具与渐进构建期不必备此三件；出厂包内必有 ⇒ 由判据④ 白名单路径把关）
    for label, rel in (
        ("adapters/dsh/manifest.json", ("adapters", "dsh", "manifest.json")),
        ("adapters/hermes/manifest.json", ("adapters", "hermes", "manifest.json")),
        ("tools/cli-spec.json", ("tools", "cli-spec.json")),
    ):
        _v = v_json_version(kit.joinpath(*rel))
        if _v:
            got[label] = _v
    miss = [k for k, v in got.items() if not v]
    vals = {v for v in got.values() if v}
    if miss:
        return False, "取不到版本号：%s" % "／".join(miss), got
    if len(vals) > 1:
        return False, "四面不一致：%s" % got, got
    return True, "四面一致 = %s" % vals.pop(), got


# ---------- ② 发行包指纹 ----------
def md5_of(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_package(kit: Path, repo: Path):
    pkg = repo / "06_发行包"
    if not pkg.is_dir():
        return None, "取不到 %s ⇒ SKIP（出厂包内无此项）" % pkg
    zips = sorted(p for p in pkg.glob("*.zip") if p.is_file())
    if len(zips) != 1:
        return False, "06_发行包/ 应恰一个 *.zip，实到 %d：%s" % (len(zips), [z.name for z in zips])
    z = zips[0]
    size, h = z.stat().st_size, md5_of(z)
    decl = repo / "README.md"
    txt = _read(decl)
    if not txt:
        return None, "取不到声明处 %s ⇒ SKIP" % decl
    s_tok, m_tok = "{:,} B".format(size), "%s…" % h[:8]
    if s_tok in txt and m_tok in txt:
        return True, "%s ｜ %s ｜ %s ⇒ 与声明处一致" % (z.name, s_tok, h)
    return False, "%s ｜ %s ｜ %s ⇒ 与声明处 %s **对不上**（缺 %s）" % (
        z.name, s_tok, h, decl, " / ".join(x for x in (s_tok, m_tok) if x not in txt))


# ---------- ③ 禁物 ----------
def check_junk(kit: Path):
    hits = []
    for dp, dns, fns in os.walk(kit):
        for d in list(dns):
            if d in JUNK_DIRS:
                hits.append(os.path.relpath(os.path.join(dp, d), kit) + "/")
        for f in fns:
            if f.endswith((".pyc", ".pyo", ".downloading")) or ".bak" in f:
                hits.append(os.path.relpath(os.path.join(dp, f), kit))
    return (not hits), ("禁物 %d 处：%s" % (len(hits), hits[:8]) if hits else "无禁物")


# ---------- ④ 白名单路径 ----------
def parse_whitelist(kit: Path):
    out, started, state = [], False, 0
    for ln in _read(kit / "发行物清单.md").splitlines():
        s = ln.strip()
        if not started:
            if s.startswith("## 一、白名单"):
                started = True
            continue
        if s.startswith("```"):
            if state == 0:
                state = 1
                continue
            break
        if state == 1 and s:
            out.append(s)
    return out


def check_whitelist_paths(kit: Path):
    wl = parse_whitelist(kit)
    if not wl:
        return False, "白名单解析为空（检查 `发行物清单.md` §一 围栏块）"
    missing = [r for r in wl if not (kit / r).is_file()]
    if missing:
        return False, "白名单声明但缺失 %d 件：%s" % (len(missing), missing[:8])
    return True, "白名单 %d 件全部在位" % len(wl)


# ---------- ⑤ 声称须带指向件 ----------
def check_claims(kit: Path):
    known = {(r, n) for r, n, _ in KNOWN_EXCEPTIONS}
    bad, exc = [], []
    for dp, dns, fns in os.walk(kit):
        dns[:] = [d for d in dns if d not in JUNK_DIRS]
        for f in fns:
            if not f.endswith((".md", ".json")):
                continue
            p = Path(dp) / f
            rel = p.relative_to(kit).as_posix()
            lines = _read(p).splitlines()
            for i, ln in enumerate(lines, 1):
                if not any(w in ln for w in CLAIM_WORDS):
                    continue
                ctx = ln + (lines[i - 2] if i >= 2 else "")
                if POINT_RE.search(ctx):
                    continue
                (exc if (rel, i) in known else bad).append("%s:%d" % (rel, i))
    msg = "无指向强断言 %d 处" % len(bad)
    if bad:
        msg += "：%s" % bad[:6]
    if exc:
        msg += " ｜ 基线豁免 %d 处（**到期：下次 bump 合批**）：%s" % (len(exc), exc)
    return (not bad), msg


# ---------- ⑥ 文档面版本串一致（2026-10-02 加 · 治「同源漂移」第 3 次 ⇒ `O-114` ①） ----------
# 为什么需要它：`docs/QUICKSTART.md` 的**示例包名**在 `v0.1.6 → 0.1.7 → 0.1.12` 三轮里**两轮漏改**，
#   直到第 6 轮外部验收才被抓出（"同源漂移"第 3 次）⇒ **人眼回扫不可作验收基准**（承 P0-3）。
# 判据：**文档面**出现的 `memory-kit-<x.y.z>` 必须 == 当前版本。
# 扫描面**排除历史台账与夹具**（它们按定义就含历史版本号）：
#   `CHANGELOG.md` ｜ `发行物清单.md`（§四 是逐版 append 台账） ｜ `tests/`（夹具）。
VERSTR_RE = re.compile(r"memory-kit-(\d+\.\d+\.\d+)")
VER_EXEMPT_FILES = ("CHANGELOG.md", "发行物清单.md")


def check_doc_version_strings(kit: Path):
    cur = v_version(kit)
    if not cur:
        return False, "取不到当前版本（`VERSION` 缺失或格式不符）"
    bad, scanned = [], 0
    for dp, dns, fns in os.walk(kit):
        dns[:] = [d for d in dns if d not in JUNK_DIRS and d != "tests"]
        for f in fns:
            if not f.endswith((".md", ".json")) or f in VER_EXEMPT_FILES:
                continue
            p = Path(dp) / f
            scanned += 1
            for i, ln in enumerate(_read(p).splitlines(), 1):
                for m in VERSTR_RE.finditer(ln):
                    if m.group(1) != cur:
                        bad.append("%s:%d 命中 `%s`（当前 %s）"
                                   % (p.relative_to(kit).as_posix(), i, m.group(0), cur))
    if bad:
        return False, "文档面版本串**停旧** %d 处：%s" % (len(bad), bad[:6])
    return True, "文档面 %d 件无停旧版本串（当前 %s）" % (scanned, cur)


# ---------- 汇总 ----------
def run_all(kit: Path, repo: Path, quiet: bool = False):
    rows, red = [], 0
    for name, fn in (("①版本四面", lambda: check_versions(kit)),
                     ("②发行包指纹", lambda: check_package(kit, repo)),
                     ("③禁物", lambda: check_junk(kit)),
                     ("④白名单路径", lambda: check_whitelist_paths(kit)),
                     ("⑤声称指向件", lambda: check_claims(kit)),
                     ("⑥版本串一致", lambda: check_doc_version_strings(kit))):
        res = fn()
        ok, detail = res[0], res[1]
        tag = "GREEN" if ok is True else ("SKIP " if ok is None else "RED  ")
        if ok is False:
            red += 1
        rows.append((name, tag, detail))
    print("==== 状态一致性闸（F 类）｜ 套件根：%s" % kit)
    for name, tag, detail in rows:
        print("  [%s] %-10s %s" % (tag, name, detail))
    print("==== 汇总：RED %d ｜ %s" % (red, "全绿（6 类）" if red == 0 else "未过 —— 按上行处方修"))
    return 0 if red == 0 else 1


def selftest() -> int:
    """必红例 ＋ 正确态：植入错版本号 ⇒ RED；正确态 ⇒ GREEN。"""
    checks = []
    with tempfile.TemporaryDirectory() as d:
        kit = Path(d) / "kit"
        repo = Path(d) / "repo"
        (kit / "adapters/hermes").mkdir(parents=True)
        repo.mkdir(parents=True)
        (kit / "VERSION").write_text("memory-kit 0.1.1\n", encoding="utf-8")
        (kit / "CHANGELOG.md").write_text("## [0.1.1] — 2026-09-30\n", encoding="utf-8")
        (kit / "README.md").write_text("> **版本**：**0.1.1**\n", encoding="utf-8")
        WL = ("## 一、白名单（x）\n\n```\nVERSION\nREADME.md\nCHANGELOG.md\n发行物清单.md\n```\n\n"
              "套件版本 ＝ `0.1.1`\n")
        (kit / "发行物清单.md").write_text(WL, encoding="utf-8")

        # 正确态：无 06_发行包 ⇒ 判据②SKIP，其余全绿
        checks.append(("正确态应全绿（②按 SKIP）", run_all(kit, repo, quiet=True) == 0))

        (kit / "VERSION").write_text("memory-kit 9.9.9\n", encoding="utf-8")
        checks.append(("植入错版本号 ⇒ 必 RED", run_all(kit, repo, quiet=True) == 1))
        (kit / "VERSION").write_text("memory-kit 0.1.1\n", encoding="utf-8")

        (kit / "__pycache__").mkdir()
        checks.append(("植入 __pycache__ ⇒ 必 RED", run_all(kit, repo, quiet=True) == 1))
        (kit / "__pycache__").rmdir()

        (kit / "发行物清单.md").write_text(WL.replace("发行物清单.md\n", "发行物清单.md\n缺件.md\n"), encoding="utf-8")
        checks.append(("白名单缺件 ⇒ 必 RED", run_all(kit, repo, quiet=True) == 1))
        (kit / "发行物清单.md").write_text(WL, encoding="utf-8")

        (kit / "README.md").write_text("> **版本**：**0.1.1**\n\n这是唯一可行的做法。\n", encoding="utf-8")
        checks.append(("无指向强断言 ⇒ 必 RED", run_all(kit, repo, quiet=True) == 1))
        (kit / "README.md").write_text("> **版本**：**0.1.1**\n", encoding="utf-8")

        # ⑥ 文档面版本串一致（**须在动 zip 之前跑**：后续用例会改包内容 ⇒ 判据② 变红）
        (kit / "docs").mkdir()
        (kit / "docs" / "X.md").write_text("照抄 `memory-kit-0.1.0.zip` 即可\n", encoding="utf-8")
        checks.append(("文档面版本串停旧 ⇒ 必 RED", run_all(kit, repo, quiet=True) == 1))
        (kit / "docs" / "X.md").write_text("照抄 `memory-kit.zip` 即可\n", encoding="utf-8")
        checks.append(("示例式去版本化 ⇒ 复原 GREEN", run_all(kit, repo, quiet=True) == 0))
        (kit / "CHANGELOG.md").write_text("## [0.1.1] — x\n\n历史提 `memory-kit-0.1.0.zip`\n", encoding="utf-8")
        checks.append(("历史台账豁免 ⇒ 仍 GREEN", run_all(kit, repo, quiet=True) == 0))

        # ② 发行包指纹：声明对得上 ⇒ GREEN；改包内容 ⇒ RED
        pkg = repo / "06_发行包"
        pkg.mkdir()
        z = pkg / "memory-kit-0.1.1.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("memory-kit/VERSION", "memory-kit 0.1.1\n")
        size, h = z.stat().st_size, md5_of(z)
        (repo / "README.md").write_text("| **^1** | 包 %s · %s · md5 `%s…` |\n" % (z.name, "{:,} B".format(size), h[:8]), encoding="utf-8")
        checks.append(("包指纹声明一致 ⇒ GREEN", run_all(kit, repo, quiet=True) == 0))
        with zipfile.ZipFile(z, "a") as zf:
            zf.writestr("memory-kit/EXTRA.md", "x")
        checks.append(("改包内容 ⇒ 指纹 RED", run_all(kit, repo, quiet=True) == 1))

    bad = [n for n, ok in checks if not ok]
    print("== state_consistency --selftest ==")
    for n, ok in checks:
        print("   [%s] %s" % ("OK" if ok else "FAIL", n))
    print("=> %d/%d" % (len(checks) - len(bad), len(checks)))
    return 0 if not bad else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="套件根（默认：本脚本上一级）")
    ap.add_argument("--repo-root", default=None, help="项目根（供判据②取 06_发行包 与声明处）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    kit = Path(a.root).resolve() if a.root else Path(__file__).resolve().parent.parent
    if not kit.is_dir():
        print("[FAIL] 套件根不存在：%s" % kit)
        return 3
    repo = Path(a.repo_root).resolve() if a.repo_root else kit.parent
    return run_all(kit, repo, quiet=a.quiet)


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

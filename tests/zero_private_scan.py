#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零私人内容判据扫描器 —— 发行前的"出厂物不含私人内容"判据（G3 ①②）。

判据（承 DSH 15:4x 否定性裁决 Q3「白名单为主、黑名单为辅」）：
  ① 白名单：实际出厂文件集合 ⊆ 白名单（多一个文件即 FAIL；少一个只 WARN）
  ② 黑名单：私人关键词命中 = 0；与私有参照件的 n-gram 交叉 = 0
     —— 无参照输入时【明示未执行】，禁假装通过。

本脚本【自身零私人内容】：私人信息一律由命令行传入，永不落包。

用法：
  python zero_private_scan.py --root <包根>                      # 全跑（有参照则跑②）
  python zero_private_scan.py --root <包根> --whitelist          # 只跑①
  python zero_private_scan.py --root <包根> --content \
      --keywords <词表件> --private-ref <私有件目录>
  python zero_private_scan.py --selftest                         # 三态自检

退出码：0 全通过 ｜ 1 白名单 FAIL ｜ 2 内容 FAIL ｜ 3 参数/IO 错误
"""
import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

TEXT_EXT = {"", ".md", ".txt", ".py", ".json", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".csv"}
SKIP_DIRS = {".git", "__pycache__", ".idea", ".vscode", ".mypy_cache", ".pytest_cache"}
MANIFEST_NAME = "发行物清单.md"
NGRAM_N = 16
NGRAM_MIN_HITS = 2


# ---------------------------------------------------------------- 基础设施

def iter_files(root: Path, skip: bool = True):
    """产出 (绝对路径, POSIX 相对路径)。

    skip=True 用于【内容扫描】（跳过构建垃圾目录）；
    skip=False 用于【白名单扫描】—— 宁可误报，不可漏报（`__pycache__` 内文件同样该被白名单判据抓到）。
    """
    for dp, dns, fns in os.walk(root):
        if skip:
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            p = Path(dp) / fn
            yield p, p.relative_to(root).as_posix()


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_fenced_list(path: Path, heading_prefix: str):
    """解析 md 件：<heading_prefix> 之后的第一个 ``` 围栏块，逐行取非空行为列表。"""
    out, started, state = [], False, 0
    for ln in read_text(path).splitlines():
        s = ln.strip()
        if not started:
            if s.startswith(heading_prefix):
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


def norm(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./")


# ---------------------------------------------------------------- 判据 ① 白名单

def check_whitelist(root: Path):
    manifest = root / MANIFEST_NAME
    if not manifest.exists():
        return None, None, f"找不到白名单真源：{manifest}"
    wl = [norm(x) for x in parse_fenced_list(manifest, "## 一、白名单")]
    if not wl:
        return None, None, f"白名单段解析为空：{manifest}"
    wl_set = set(wl)
    actual = {norm(rel) for _p, rel in iter_files(root, skip=False)}
    extra = sorted(actual - wl_set)
    missing = sorted(wl_set - actual)
    return extra, missing, None


# ---------------------------------------------------------------- 判据 ② 内容

def load_keywords(kwfile: Path):
    return [norm(x) for x in parse_fenced_list(kwfile, "## 一、词表")] if kwfile else []


def normalize(s: str) -> str:
    """只留汉字／字母／数字 —— 剥掉标点、空白、表格线、代码符号。

    必要性（实测教训 2026-09-29）：不做归一化时，markdown 表格线、代码骨架
    （import argparse 段）、frontmatter 字段名会与参照件大面积"同源"，
    导致判据②对**结构化文本**完全失效（首跑 17/17 件全命中，全是假阳性）。
    """
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def ngrams(text: str, n: int = NGRAM_N):
    t = normalize(text)
    return {t[i:i + n] for i in range(len(t) - n + 1)} if len(t) >= n else set()


# ★ 判据② 改度量（2026-09-29 · 机制变更已获明示）：三件一起上 ——
#   ① **全篇取样**（旧版只取"含关键词的 ±40 窗口"，实测漏掉"逐字注入的私人原文（不含关键词）"）
#   ② **基线扣除**（框架共用语不再靠"限定取样面"消，而由"**出现在包内 ≥FRAME_COMMON_MIN_FILES 件**"机械扣除）
#   ③ **阳性对照纳入自检**（selftest 新增态5）
REF_LINE_MIN = 60            # 参照侧"长行"阈值（字符）
REF_LINE_CAP = 6000          # 参照侧长行取样上限（控内存；超出则截断并**报出**）
FRAME_COMMON_MIN_FILES = 2   # 一个 n-gram 在**包内或参照侧**出现 ≥ 该件数 ⇒ 判为框架共用语，扣除
RUN_MIN = 48                 # ★ "逐字搬用"判据：最长**连续命中**字符数须 ≥ 该值（= 3×16-gram）
#   为什么要有 RUN_MIN（2026-09-29 实测）：只按"命中 gram 数"判 ⇒ 零星共享词组（MIT 许可条款、
#   规范术语、文件名枚举）会被当命中（干净包残留 12 件）。**真泄漏的形态是"一段被逐字搬用"**，
#   阳性对照探针 B（176 字符逐字）连续命中 ≈160 字符；而上述噪声连续命中均 <48 字符。
#   ⇒ 判据改为「跨件扣除后仍 ≥NGRAM_MIN_HITS 个 **且** 最长连续命中 ≥RUN_MIN 字符」。


def longest_run(text: str, ref_grams, n: int = NGRAM_N) -> int:
    """返回 text 归一化后**最长连续命中**的字符数（0 = 无命中）。"""
    t = normalize(text)
    if len(t) < n or not ref_grams:
        return 0
    best = cur = 0
    for i in range(len(t) - n + 1):
        if t[i:i + n] in ref_grams:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return 0 if best == 0 else best + n - 1


def collect_ref_grams(refdir: Path, keywords, win: int = 40):
    """采样私有参照，产出 n-gram 参照集（**两条腿**）+ 参照侧跨件复现集。

    ★ 2026-09-29 判据② 改度量（承外部复核 + 阳性对照实测）：
      ① **关键词窗口**（保留）—— 抓「私人事实被改写后带出的周边措辞」；
      ② **参照侧长行全篇**（新增）—— 抓「**逐字搬用**」（阳性对照探针 B 即此形态：
         把某私人件里一行 ≥60 字符的原文逐字注入包内，该行**本身不含任何关键词**，
         旧版因"无关键词锚点"取不到窗口 ⇒ **三闸全漏**）。
      ③ **参照侧跨件复现集**（新增）—— 框架级术语/通用条款（如 MIT 许可正文）在参照侧
         会**跨多件出现**，而在包内可能只落在单件 ⇒ 只扣"包内侧"会漏（实测残留 12 件）。

    返回：(ref_grams, ref_common, n_kw_windows, n_ref_lines, truncated)
    """
    grams, ref_files, n_win, n_line, truncated = set(), {}, 0, 0, False
    if not refdir or not refdir.exists():
        return grams, set(), n_win, n_line, truncated
    kws = [k.lower() for k in keywords if k]
    for p, _rel in iter_files(refdir):
        if p.suffix.lower() not in TEXT_EXT:
            continue
        txt = read_text(p)
        low = txt.lower()
        fg = set()
        for kw in kws:
            start = 0
            while True:
                i = low.find(kw, start)
                if i < 0:
                    break
                fg |= ngrams(txt[max(0, i - win): i + len(kw) + win])
                n_win += 1
                start = i + len(kw)
        for ln in txt.splitlines():
            s = ln.strip()
            if len(s) < REF_LINE_MIN:
                continue
            if any(k in s.lower() for k in kws):
                continue          # 含关键词的行已由关键词闸覆盖，不重复计入
            if n_line >= REF_LINE_CAP:
                truncated = True
                break
            fg |= ngrams(s)
            n_line += 1
        if fg:
            grams |= fg
            for x in fg:
                ref_files[x] = ref_files.get(x, 0) + 1
    ref_common = {x for x, c in ref_files.items() if c >= FRAME_COMMON_MIN_FILES}
    return grams, ref_common, n_win, n_line, truncated


def check_content(root: Path, keywords, refdir: Path):
    """内容面扫描：① 关键词（硬）② n-gram 交叉（**已扣除框架共用语**）。

    ★ 2026-09-29 改度量：命中口径 = `(件 ∩ 参照) − 框架共用语`，
      其中"框架共用语" ＝ **出现在包内 ≥FRAME_COMMON_MIN_FILES 件的 n-gram**（基线扣除的
      自包含近似：骨架由参照件脱胎 ⇒ 框架级路径/术语必然两侧相同，且必然**跨件复现**）。
    返回 6 元组（末项为采样统计 dict）。
    """
    ref_grams, ref_common, n_win, n_line, truncated = collect_ref_grams(refdir, keywords)

    kw_hits, ng_hits, scanned, too_short = [], [], 0, 0
    file_grams, gram_files, file_txt = {}, {}, {}   # 第一遍：收集 + 计"跨件复现次数"
    for p, rel in iter_files(root):
        if p.suffix.lower() not in TEXT_EXT:
            continue
        txt = read_text(p)
        scanned += 1
        low = txt.lower()
        for kw in keywords:
            if kw and kw.lower() in low:
                kw_hits.append((norm(rel), kw))
        if not ref_grams:
            continue
        # ★ 归一化后不足 NGRAM_N 字的文本**产生不了 n-gram** ⇒ 本通道的"静默盲区"，必须**报出**（禁静默）。
        if len(normalize(txt)) < NGRAM_N:
            too_short += 1
            continue
        g = ngrams(txt) & ref_grams
        if g:
            rel_n = norm(rel)
            file_grams[rel_n] = g
            file_txt[rel_n] = txt
            for x in g:
                gram_files[x] = gram_files.get(x, 0) + 1

    dropped = 0                              # 第二遍：扣除框架共用语（**双侧**）后判命中
    for rel, g in file_grams.items():
        eff = {x for x in g
               if gram_files.get(x, 0) < FRAME_COMMON_MIN_FILES and x not in ref_common}
        dropped += len(g) - len(eff)
        run = longest_run(file_txt[rel], eff)
        if len(eff) >= NGRAM_MIN_HITS and run >= RUN_MIN:
            ng_hits.append((rel, len(eff), sorted(eff)[:2], run))
    stats = {"ref_win": n_win, "ref_lines": n_line, "ref_truncated": truncated,
             "ref_common": len(ref_common), "frame_common_dropped": dropped,
             "files_with_overlap": len(file_grams), "run_min": RUN_MIN}
    return kw_hits, ng_hits, scanned, len(file_grams), too_short, stats


# ---------------------------------------------------------------- 自检

def _make_pkg(base: Path, files):
    for rel in files:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")


def selftest() -> int:
    print("== selftest（五态 · 含阳性对照）==")
    wl_head = "## 一、白名单"
    cases = []

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # 态 1：合法包（实际 == 白名单）=> rc 0
        d1 = base / "ok"
        files1 = ["a.md", "b/c.py", MANIFEST_NAME]
        _make_pkg(d1, [f for f in files1 if f != MANIFEST_NAME])
        (d1 / MANIFEST_NAME).write_text(
            f"\n{wl_head}\n\n```\na.md\nb/c.py\n{MANIFEST_NAME}\n```\n", encoding="utf-8")
        extra, missing, err = check_whitelist(d1)
        cases.append(("态1 合法包应无多余件", err is None and extra == [] and missing == []))

        # 态 2：多一个文件 => extra 非空（FAIL 信号）
        d2 = base / "extra"
        _make_pkg(d2, ["a.md", "b/c.py", "偷偷新增.txt"])
        shutil.copy(d1 / MANIFEST_NAME, d2 / MANIFEST_NAME)
        extra, _missing, err = check_whitelist(d2)
        cases.append(("态2 多一个文件应被检出", err is None and extra == ["偷偷新增.txt"]))

        # 态 3：少一个文件 => missing 非空（WARN，不算 FAIL）
        d3 = base / "missing"
        _make_pkg(d3, ["a.md"])
        shutil.copy(d1 / MANIFEST_NAME, d3 / MANIFEST_NAME)
        extra, missing, err = check_whitelist(d3)
        cases.append(("态3 少文件应为 missing 而非 extra", err is None and extra == [] and missing == ["b/c.py"]))

        # 态 4：内容命中（关键词） => 应报出
        d4 = base / "kw"
        _make_pkg(d4, ["a.md"])
        (d4 / "a.md").write_text("这句话里有 禁区词甲 三个字\n", encoding="utf-8")
        kf = base / "kw.txt"
        kf.write_text(f"\n## 一、词表\n\n```\n禁区词甲\n```\n", encoding="utf-8")
        kw_hits, _ng, scanned, _n, _ts, _st = check_content(d4, load_keywords(kf), None)
        cases.append(("态4 关键词命中应被检出", len(kw_hits) == 1 and scanned >= 1))

        # 态 5：★ 阳性对照 —— **逐字同源、且不含关键词** ⇒ 改度量后**必须被检出**
        #        （旧版此态必红：无关键词锚点 ⇒ 取不到窗口 ⇒ 静默漏报）
        d5, rf5 = base / "verbatim", base / "ref5"
        d5.mkdir(parents=True, exist_ok=True)
        rf5.mkdir(parents=True, exist_ok=True)
        secret = ("私件里的一行独有措辞用于阳性对照：窗外雨声一直下到凌晨三点，" * 2)
        (rf5 / "priv.md").write_text(f"# 私件\n\n{secret}\n", encoding="utf-8")
        _make_pkg(d5, ["a.md"])
        # 注入：逐字搬用该行（**该行不含任何关键词**），并加一个无关前缀（模拟"藏在正文里"）
        (d5 / "a.md").write_text(f"例：{secret}\n", encoding="utf-8")
        _kw2, ng5, _sc, _n2, _ts2, _st2 = check_content(d5, [], rf5)
        cases.append(("态5【阳性对照】逐字同源（不含关键词）应被检出", len(ng5) >= 1))

    ok = True
    for name, res in cases:
        print(f"  [{'OK' if res else 'FAIL'}] {name}")
        ok = ok and res
    print(f"== selftest {'全绿' if ok else '有红'}（{len(cases)} 态）==")
    return 0 if ok else 1


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--root", default=None, help="发行包根目录（默认：本脚本上一级）")
    ap.add_argument("--whitelist", action="store_true", help="只跑判据①")
    ap.add_argument("--content", action="store_true", help="只跑判据②")
    ap.add_argument("--keywords", default=None, help="关键词表件（私人件，永不落包）")
    ap.add_argument("--private-ref", default=None, help="私有参照目录（n-gram 交叉用）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--ngram-warn", action="store_true",
                    help="把 n-gram 交叉降为 WARN（**默认已恢复为 FAIL**：改度量后框架共用语被机械扣除，"
                         "见 spec §七；本开关仅供排查时降噪）")
    ap.add_argument("--strict-ngram", action="store_true",
                    help="[已废弃·保留兼容] 同 --ngram-warn 的反面（默认即 FAIL，故本开关现为无操作）")
    ap.add_argument("--selftest", action="store_true", help="五态自检（含阳性对照）")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"[FAIL] 包根不存在：{root}")
        return 3

    run_wl = a.whitelist or not (a.whitelist or a.content)
    run_ct = a.content or not (a.whitelist or a.content)
    rc = 0
    report = {"root": str(root)}

    print(f"包根：{root}")

    if run_wl:
        extra, missing, err = check_whitelist(root)
        if err:
            print(f"[FAIL] {err}")
            return 3
        n_actual = sum(1 for _ in iter_files(root))
        print(f"-- 判据① 白名单：实际 {n_actual} 件 ｜ 白名单 {n_actual - len(extra) + len(missing)} 件 "
              f"｜ 多余 {len(extra)} ｜ 缺失 {len(missing)}")
        report["whitelist"] = {"extra": extra, "missing": missing, "actual": n_actual}
        if extra:
            print("[FAIL] 出现白名单外文件（多一个即 fail）：")
            for e in extra:
                print(f"        + {e}")
            rc = 1
        else:
            print("[OK] 判据① 通过（无白名单外文件）")
        for m in missing:
            print(f"[WARN] 白名单声明但实际缺失（允许渐进构建）：{m}")

    ct_skipped = False
    if run_ct:
        kwfile = Path(a.keywords) if a.keywords else None
        refdir = Path(a.private_ref) if a.private_ref else None
        if not kwfile and not refdir:
            print("[SKIP] 判据② 未提供 --keywords/--private-ref ⇒ 【本节未执行】（不等于通过）")
            report["content"] = {"executed": False}
            ct_skipped = True
        else:
            kws = load_keywords(kwfile) if kwfile else []
            kw_hits, ng_hits, scanned, n_overlap, too_short, st = check_content(root, kws, refdir)
            print(f"-- 判据② 内容：扫描 {scanned} 件 ｜ 关键词 {len(kws)} 条 ｜ 命中 {len(kw_hits)} ｜ "
                  f"参照采样（关键词窗口 {st['ref_win']} ／ 长行 {st['ref_lines']}）｜ "
                  f"n-gram 交叉命中件 {len(ng_hits)} ｜ **已扣除框架共用语 {st['frame_common_dropped']} 个**")
            if st.get("ref_truncated"):
                print(f"   [报出] 参照侧长行取样达上限 {REF_LINE_CAP} 行（**已截断**）⇒ 召回面收窄，"
                      f"如需全覆盖请提高 REF_LINE_CAP")
            if too_short:
                print(f"   [报出] 过短文本（归一化后 < {NGRAM_N} 字，**不参与 n-gram 通道**）：{too_short} 件"
                      f" —— 这些件在本通道里是静默盲区，只能靠关键词闸覆盖")
            report["content"] = {"executed": True, "scanned": scanned,
                                 "kw_hits": kw_hits, "ng_hits": ng_hits,
                                 "ng_sample": st}
            if kw_hits:
                print("[FAIL] 关键词命中：")
                for rel, kw in kw_hits[:20]:
                    print(f"        {rel}  <- {kw}")
                rc = 2
            if ng_hits:
                # ★ 2026-09-29 改度量后**默认恢复 FAIL**：框架共用语已被"跨件复现"机械扣除，
                #   残留命中＝"只在这一件出现、且与私有参照重合" ⇒ 有鉴别力（阳性对照已证）。
                tag = "[WARN]" if a.ngram_warn else "[FAIL]"
                print(f"{tag} 与私有参照 n-gram 交叉（**已扣除框架共用语** · 按密度排序）：")
                for rel, cnt, sample, run in sorted(ng_hits, key=lambda x: -x[1])[:20]:
                    print(f"        {rel}  ({cnt} 个 {NGRAM_N}-gram ｜ 最长连续 {run} 字符)  例：{sample}")
                if not a.ngram_warn:
                    rc = 2
            if not kw_hits and not ng_hits:
                print("[OK] 判据② 通过")

    if a.json:
        import json
        print(json.dumps(report, ensure_ascii=False))
    if ct_skipped:
        # ★ 口径落差治本（2026-09-29 外部复核抓出）：本节未执行时**禁再打"通过"** ——
        #   rc 仍为 0（判定职责在发行前闸：它把"跳过"另判为『审查不完整』）。
        print("== 结果：判据① 通过；判据② **未执行** ⇒ 不构成完整通过"
              "（rc=0；由发行前闸判『审查不完整』）==")
    else:
        print(f"== 结果：{'通过' if rc == 0 else '未通过'}（rc={rc}）==")
    return rc


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

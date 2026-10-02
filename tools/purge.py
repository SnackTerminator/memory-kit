#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本库内删除可复核 —— `purge`（真删）／`audit`（核验）／`verify`（回执链）。

设计依据：`01_计划与范围/设计_删除可核_v1_20261001.md`（**v1.1** · 外部评审 15 项全采纳）
三件：**本件**（命令）｜`_meta/deletion/receipt.tsv`（append-only 回执）｜`tests/deletion_audit.py`（验证脚本）

四条硬性质
- **只碰目标与命中副本**：除「目标 ＋ 全库同内容副本」外，**全库哈希集不变**（同 `curate` 判据 9 口径）
- **可核**：回执 append-only ＋ `prev_hash` 链；**仅存路径与哈希，禁存正文**（**证据面纪律**）
- **零依赖零网**：仅标准库（`audit_probe()` 可机检 · D7）
- **不越界**：**禁「写」`_meta/curation/` 下的控制件**（`ledger.tsv`／`proposals.*`／`state.json`）；
  ⚠️ 但**允许「删」`_meta/curation/hist/` 下命中的前像快照** —— 那是本命令的**删除对象**，不是"写"（v1.1 口径）。

覆盖规则（v1.1 · **按内容同一性，不按同名**）
  `primary`（目标本体）｜`archive-copy`（`_archive/**`）｜`hist-snapshot`（`_meta/curation/hist/**`）｜`other-copy`（全根其余，含 `.bak_*`）
  同路径但**内容不同**（旧版本）⇒ **默认只列不删**；`--sweep-archive` 才一并清 `_archive/**` 同名不同内容者。

用法
  python tools/purge.py purge  --root <库根> --target <相对路径> --operator <不透明 id> --preview
  python tools/purge.py purge  --root <库根> --target <相对路径> --operator <id> --yes --receipt-fingerprint <8位>
  python tools/purge.py audit  --root <库根> [--target <相对路径>]
  python tools/purge.py verify --root <库根>

退出码：0 成功／预览完成 ｜ 1 **有残留或拒** ｜ 3 参数/IO 错
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

CUR = Path("_meta") / "deletion"
RECEIPT = CUR / "receipt.tsv"
AUDIT_STATE = CUR / "audit_state.json"
ARCHIVE = "_archive"
HIST_DIR = Path("_meta") / "curation" / "hist"
INDEX_DIR = Path("08-检索索引")
# 证据面（**允许**出现路径与哈希，**禁正文**）—— 不参与「路径探针」
EVIDENCE_PREFIXES = (CUR.as_posix() + "/", (Path("_meta") / "curation").as_posix() + "/")
HEADER = ["ts", "action", "role", "target", "sha256", "bytes", "operator", "scope",
          "spec_version", "tool_version", "related", "lib_digest_pre", "lib_digest_post",
          "prev_hash", "row_hash"]
TOOL_VERSION = "purge/1.0"
BOUNDARY_4 = ("**本库根**", "**逻辑删除**", "**不含库外与宿主侧**", "**自存证 ≠ 第三方公证**")


# ────────────────────────── 基础设施 ──────────────────────────
def _now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _spec_version(root: Path) -> str:
    p = root.parent / "VERSION"
    try:
        return (p.read_text(encoding="utf-8").splitlines() or ["unknown"])[0].strip()
    except OSError:
        return "unknown"


def _atomic_write(p: Path, data: str):
    """原子写：同目录 temp ＋ `os.replace`，禁半态（同 `curate` 判据 10 口径）。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp_", suffix=p.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _walk_files(root: Path):
    """全库文件（排除本命令自己的回执面与 `__pycache__`）。"""
    skip = CUR.as_posix() + "/"
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for f in sorted(fns):
            p = Path(dp) / f
            rel = _rel(root, p)
            if rel.startswith(skip):
                continue
            yield p, rel


def _lib_digest(root: Path) -> str:
    """全库指纹（排除 `_meta/deletion/`）—— 供回执记 `lib_digest_pre/post`（D5）。"""
    h = hashlib.sha256()
    for p, rel in _walk_files(root):
        try:
            h.update(("%s\t%s\n" % (rel, _sha_file(p)[:16])).encode("utf-8"))
        except OSError:
            h.update(("%s\tERR\n" % rel).encode("utf-8"))
    return h.hexdigest()[:16]


def _row_hash(fields) -> str:
    """**与 `curate` 同式**：除 `row_hash` 外全列 TSV 拼接 → sha256[:12]（跨工具一致性向量的对象）。"""
    return hashlib.sha256("\t".join(fields).encode("utf-8")).hexdigest()[:12]


def _receipt_rows(root: Path):
    p = root / RECEIPT
    if not p.is_file():
        return []
    out = []
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines()):
        if not ln.strip():
            continue
        if i == 0 and ln.split("\t")[0] == "ts":
            continue
        out.append(ln)
    return out


def _verify_chain(root: Path):
    prev, bad = "GENESIS", []
    rows = _receipt_rows(root)
    for i, r in enumerate(rows, 1):
        f = r.split("\t")
        if len(f) != len(HEADER):
            bad.append("第 %d 行列数 %d≠%d" % (i, len(f), len(HEADER)))
            continue
        if f[13] != prev:
            bad.append("第 %d 行 prev_hash 断链" % i)
        if _row_hash(f[:14] + f[15:]) != f[14]:
            bad.append("第 %d 行自校验不符（行被改写？）" % i)
        prev = f[14]
    return bad


def _receipt_fingerprint(root: Path) -> str:
    p = root / RECEIPT
    if not p.is_file():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()[:8]


def _append_receipt(root: Path, new_rows):
    """回执**只用原子写整体重写**（非裸追加）—— append-only 语义由「只增不删」保证。"""
    p = root / RECEIPT
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else ["\t".join(HEADER)]
    lines.extend(new_rows)
    _atomic_write(p, "\n".join(lines) + "\n")


# ────────────────────────── 探针（按内容同一性）──────────────────────────
def _role_of(root: Path, rel: str) -> str:
    if rel.startswith(ARCHIVE + "/"):
        return "archive-copy"
    if rel.startswith(HIST_DIR.as_posix() + "/"):
        return "hist-snapshot"
    return "other-copy"


def _same_content_hits(root: Path, digest: str, exclude=()):
    """全根找**内容同一**者（sha256 相同）⇒ [(rel, role)]；排除本命令自己的回执面。"""
    hits = []
    for p, rel in _walk_files(root):
        if rel in exclude:
            continue
        try:
            if _sha_file(p) == digest:
                hits.append((rel, _role_of(root, rel)))
        except OSError:
            continue
    return hits


def _path_stale_hits(root: Path, rel_target: str):
    """**同路径但内容不同**（旧版本）⇒ 只列不删（默认）。"""
    out = []
    tgt = root / rel_target
    for p, rel in _walk_files(root):
        if rel == rel_target or rel.startswith(rel_target + "."):
            if p.is_file() and (not tgt.is_file() or _sha_file(p) != _sha_file(tgt)):
                if rel != rel_target:
                    out.append(rel)
    return out


def _index_path_hits(root: Path, rel_target: str):
    """**路径面**：可重建派生物（`08-检索索引/**`）里若含目标路径 ⇒ 残留（该面含 path ＋ 正文首段）。"""
    d = root / INDEX_DIR
    if not d.is_dir():
        return []
    hits = []
    for dp, dns, fns in os.walk(d):
        for f in sorted(fns):
            p = Path(dp) / f
            try:
                if rel_target in p.read_text(encoding="utf-8", errors="replace"):
                    hits.append(_rel(root, p))
            except OSError:
                continue
    return hits


# ────────────────────────── 命令 ──────────────────────────
def cmd_purge(a):
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root); return 3
    rel_target = a.target.replace("\\", "/").lstrip("./")
    tgt = root / rel_target

    # 归档态目标亦须可 purge（v1.1：v1 的 CLI 只示意活动件）
    arch = root / ARCHIVE / rel_target
    if tgt.is_file():
        digest, primary_rel, primary_state = _sha_file(tgt), rel_target, "active"
    elif arch.is_file():
        digest, primary_rel, primary_state = _sha_file(arch), "%s/%s" % (ARCHIVE, rel_target), "archived"
    else:
        print("[FAIL] 目标不存在（活动区与 `_archive/` 皆无）：%s" % rel_target); return 1

    hits = _same_content_hits(root, digest, exclude=(primary_rel,))
    stale = _path_stale_hits(root, rel_target)

    print("==== purge ｜ 目标：%s ｜ 状态：%s ｜ sha256[:12]：%s ｜ %d B"
          % (rel_target, primary_state, digest[:12], (root / primary_rel).stat().st_size))
    print("     命中副本（**按内容同一性**）：%d 处" % len(hits))
    for r, role in hits:
        print("       [%s] %s" % (role, r))
    if stale:
        print("     ⚠ 同路径但内容不同的旧版本（**默认只列不删**）：%d 处" % len(stale))
        for r in stale[:10]:
            print("       [keep] %s" % r)
        if a.sweep_archive:
            print("       （`--sweep-archive` 已开启 ⇒ `_archive/` 下旧版本一并清）")
    idx = _index_path_hits(root, rel_target)
    if idx:
        print("     ⚠ 可重建派生物内仍含该路径（重建后应清零）：%s" % idx[:5])

    cur_fp = _receipt_fingerprint(root)
    # 首次删除时回执尚不存在 ⇒ 期望值定为字面 `NEW`（**摩擦仍在**：用户须读 preview 输出才知传什么）
    want = cur_fp if cur_fp else "NEW"
    if a.preview:
        print("==== 预览完（**未删任何件**）")
        print("  ① 内容外锚（核对「删的是不是这条」用）：%s" % digest[:12])
        print("  ② 执行凭证（**回贴用** · 与①**不是一回事**）：加 `--yes --receipt-fingerprint %s`" % want)
        return 0
    if not a.yes:
        print("[FAIL] 须显式 `--yes` ⇒ 拒"); return 1
    if a.receipt_fingerprint != want:
        print("[FAIL] 须回贴回执指纹：期望 `%s`（首次无回执时传 `NEW`），实给 `%s` ⇒ 拒"
              % (want, a.receipt_fingerprint)); return 1

    pre = _lib_digest(root)
    rows = []
    ts = _now()
    spec = _spec_version(root)
    size = (root / primary_rel).stat().st_size
    deleted = []
    os.unlink(root / primary_rel)
    deleted.append(primary_rel)
    rows.append([ts, "purge", "primary", rel_target, digest, str(size), a.operator or "", "本库根",
                 spec, TOOL_VERSION, a.related or "", pre, "", "", ""])
    for r, role in hits:                      # **同内容者一律清**（v1.1：按内容同一性，不按同名）
        os.unlink(root / r)
        deleted.append(r)
        rows.append([ts, "purge", role, rel_target, digest, str(size), a.operator or "", "本库根",
                     spec, TOOL_VERSION, a.related or "", pre, "", "", ""])
    if a.sweep_archive:                       # 旧版本（同路径不同内容）**仅**此开关下清
        for r in stale:
            if r.startswith(ARCHIVE + "/"):
                try:
                    os.unlink(root / r)
                    deleted.append(r)
                    rows.append([ts, "purge", "stale-archive", rel_target, "", str(size), a.operator or "",
                                 "本库根", spec, TOOL_VERSION, a.related or "", pre, "", "", ""])
                except OSError:
                    pass
    post = _lib_digest(root)
    for r in rows:
        r[12] = post

    prev = "GENESIS"
    existing = _receipt_rows(root)
    if existing:
        prev = existing[-1].split("\t")[14]
    for r in rows:
        r[13] = prev
        f = r[:14] + [""] + r[15:]
        f[14] = _row_hash(f[:14] + f[15:])
        r[14] = f[14]
        prev = f[14]
    _append_receipt(root, ["\t".join(r) for r in rows])

    bad = _verify_chain(root)
    if bad:
        print("[FAIL] 回执链校验：%s" % bad[:3]); return 1
    print("[OK] 已删 %d 件（primary ＋ 命中副本）｜ 回执 %d 行 ｜ 链完整" % (len(deleted), len(rows)))
    print("[OK] lib_digest pre=%s → post=%s（供事后对账 · D5）" % (pre, post))
    print("     边界：本库根内删除可复核；**不覆盖**库外副本／宿主侧缓存与对话历史／介质级取证。")
    return 0


def cmd_audit(a):
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root); return 3
    residual = []
    if a.target:
        rel_target = a.target.replace("\\", "/").lstrip("./")
        digest = ""
        for r in reversed(_receipt_rows(root)):
            f = r.split("\t")
            if len(f) == len(HEADER) and f[3] == rel_target:
                digest = f[4]
                break
        if not digest:
            print("[FAIL] 回执里查不到该目标的 sha256 ⇒ 无法核（先 purge 或指定已删目标）"); return 1
        hits = _same_content_hits(root, digest)
        residual += [r for r, _ in hits]
        residual += _index_path_hits(root, rel_target)
        print("==== audit ｜ 目标：%s ｜ sha256[:12]：%s" % (rel_target, digest[:12]))
    else:
        print("==== audit ｜ 库根：%s" % root)

    # 三类面点数（**放运行时** · 不写死判据）
    counts = {"真源(01-记忆档案)": 0, "可重建派生物(%s)" % INDEX_DIR.as_posix(): 0,
              "证据面(_meta)": 0, "其余": 0}
    for p, rel in _walk_files(root):
        if rel.startswith("01-记忆档案/"):
            counts["真源(01-记忆档案)"] += 1
        elif rel.startswith(INDEX_DIR.as_posix() + "/"):
            counts["可重建派生物(%s)" % INDEX_DIR.as_posix()] += 1
        elif rel.startswith("_meta/"):
            counts["证据面(_meta)"] += 1
        else:
            counts["其余"] += 1
    for k, v in counts.items():
        print("       %-34s %d 件" % (k, v))

    st = {}
    sp = root / AUDIT_STATE
    if sp.is_file():
        try:
            st = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    last = st.get("counts") or {}
    changed = [k for k in counts if last.get(k) is not None and last.get(k) != counts[k]]
    if changed:
        print("       [面数变化] %s（上次 %s）" % (changed, {k: last.get(k) for k in changed}))
        for k in changed:
            print("         · %s：%d → %d" % (k, last[k], counts[k]))
    if a.target:
        residual = sorted(set(residual))
        if residual:
            print("[FAIL] **仍有残留 %d 处**：" % len(residual))
            for r in residual[:20]:
                print("       - %s" % r)
            print("       处方：清残留后重跑；索引面残留可跑 `tools/memory.py reindex` 重建后再核。")
            rc = 1
        else:
            print("[OK] 本库根内**不可达**（内容面 ＋ 路径面 均 0 命中）")
            rc = 0
    else:
        rc = 0
    print("     边界自白：%s ／ %s ／ %s ／ %s" % BOUNDARY_4)
    _atomic_write(sp, json.dumps({"schema": 1, "at": _now(), "counts": counts},
                                 ensure_ascii=False, indent=2) + "\n")
    return rc


def cmd_verify(a):
    root = Path(a.root).resolve()
    bad = _verify_chain(root)
    if bad:
        for b in bad[:10]:
            print("[FAIL] %s" % b)
        print("[结论] 回执链校验失败：%d 处" % len(bad)); return 1
    print("[结论] 回执链完整（%d 行）｜ 指纹 %s" % (len(_receipt_rows(root)), _receipt_fingerprint(root)))
    return 0


def audit_probe():
    """D7：零依赖零网机检 —— 源码 import 是否全为标准库。"""
    import ast
    src = Path(__file__).read_text(encoding="utf-8")
    std = set(getattr(sys, "stdlib_module_names", ()))
    bad = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name.split(".")[0] not in std:
                    bad.append(al.name)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.level == 0 and top and top not in std:
                bad.append(node.module)
    return bad


def main():
    ap = argparse.ArgumentParser(description="本库内删除可复核（purge／audit／verify）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("purge"); p1.add_argument("--root", required=True)
    p1.add_argument("--target", required=True); p1.add_argument("--operator", default="")
    p1.add_argument("--related", default=""); p1.add_argument("--preview", action="store_true")
    p1.add_argument("--yes", action="store_true"); p1.add_argument("--sweep-archive", dest="sweep_archive", action="store_true")
    p1.add_argument("--receipt-fingerprint", dest="receipt_fingerprint", default="")
    p2 = sub.add_parser("audit"); p2.add_argument("--root", required=True)
    p2.add_argument("--target", default="")
    p3 = sub.add_parser("verify"); p3.add_argument("--root", required=True)
    a = ap.parse_args()
    return {"purge": cmd_purge, "audit": cmd_audit, "verify": cmd_verify}[a.cmd](a)


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

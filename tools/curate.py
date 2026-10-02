#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""件 2「提案生成」＋ 件 3「确认应用」＋ 件 4「台账与前像」—— 整理层**三件一支执行体**（**出厂工具** · `tools/curate.py`）。

设计依据：`01_计划与范围/设计_整理层全量提案制_v1_20261001.md`
外部补强（Hermes 批3回件 · 台账 `O-97`）已并入：判据 **9 他源静默检测**／**10 原子写**／
**11 分叉可侦测**／**先账后动 WAL**／**批确认防呆四件套**／**`merge` 空档降级**。

四条硬性质
- **不删**：`retire` ＝ 移入 `_archive/`（条目消失 ⇔ `_archive/` 有全文 ⇔ 台账有行）
- **可回滚**：台账只增 ＋ 前像快照
- **零依赖零网**：仅标准库
- **不动无关文件**：apply 只碰目标文件 ＋ `_meta/curation/`

用法
  python curate.py propose --root <库根> [--candidates <清单文件>] [--quota 20]
  python curate.py apply   --root <库根> --preview [--only <id,...>] [--batch]
  python curate.py apply   --root <库根> --yes --proposal-fingerprint <8位>
                           [--only <id,...>] [--batch --batch-count N] [--accept-drift]
  python curate.py state   --root <库根>

退出码：0 成功/预览完成 ｜ 1 拒（含防呆拒、链坏、漂移）｜ 3 参数/IO 错 ｜ 5 有提案待处理
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

CUR = Path("_meta") / "curation"
ARCHIVE = "_archive"
LEDGER = CUR / "ledger.tsv"
PROP_JSON = CUR / "proposals.json"
PROP_MD = CUR / "proposals.md"
STATE = CUR / "state.json"
HIST = CUR / "hist"
HEADER = ["ts", "action", "target", "frm", "to", "prev_hash", "row_hash", "operator", "proposal_id"]
LIGHT = ("cool", "promote")          # 轻动作：可逆、不移动 ⇒ 可批
HEAVY = ("retire", "merge")          # 语义级：动「在不在」/「内容」⇒ 一律逐条
SCHEMA = 1
IDLE_LIMIT = 3                       # 熔断·空转阈值：连续空提案达此数 ⇒ 出声上报
# 熔断·借脑特征（**拼接构造** ⇒ 防本模块自我命中；设计稿 §八）
_BORROW_TOKENS = tuple("".join(t) for t in (
    ("re", "quests"), ("url", "lib"), ("sock", "et"), ("http", ".client"),
    ("open", "ai"), ("anthro", "pic"), ("clau", "de"), ("co", "dex"),
    ("host", "reasoner"), ("gem", "ini"),
))


# ────────────────────────── 基础设施 ──────────────────────────
def _now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_write(p: Path, data: str):
    """判据 10：原子写 —— 同目录 temp ＋ os.replace，禁半态。"""
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


def _load_state(root: Path) -> dict:
    """`state.json` ＝ **可弃缓存**（设计稿 §五）：删了不丢，重建＝重扫库 ＋ 读台账。"""
    p = root / STATE
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(root: Path, **kw):
    """**保留既有键**再合并 —— 禁整文件覆盖（否则丢 `idle_streak` 等累计量）。
    `pending_proposals` 置顶（设计稿 §三 接口化：**宿主若读此字段可见到期数**，不承诺任何宿主会读）。"""
    d = _load_state(root)
    d.update(kw)
    d["schema"] = SCHEMA
    if "pending_proposals" in d:                     # 置顶（不排序，保插入序）
        d = {"schema": d.pop("schema"), "pending_proposals": d.pop("pending_proposals"), **d}
    _atomic_write(root / STATE, json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    return d


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _fingerprint(root: Path, skip_targets=()) -> dict:
    """全库指纹（判据 9／11 的公共底座）。排除本层目录 `_meta/curation/`。"""
    out = {}
    cur_prefix = CUR.as_posix() + "/"
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for f in fns:
            p = Path(dp) / f
            rel = p.relative_to(root).as_posix()
            if rel.startswith(cur_prefix) or rel in skip_targets:
                continue
            try:
                out[rel] = _sha(p.read_bytes())[:16]
            except OSError:
                out[rel] = "ERR"
    return out


def _digest(fp: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(fp):
        h.update(("%s\t%s\n" % (k, fp[k])).encode("utf-8"))
    return h.hexdigest()[:16]


def _rows(root: Path):
    p = root / LEDGER
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


def _row_hash(fields):
    return hashlib.sha256("\t".join(fields).encode("utf-8")).hexdigest()[:12]


def _append_row(root: Path, fields):
    """台账只增 —— 仍是全文件 temp+replace（原子），非裸追加。"""
    p = root / LEDGER
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else ["\t".join(HEADER)]
    lines.append("\t".join(fields))
    _atomic_write(p, "\n".join(lines) + "\n")


def _ledger_row(root: Path, action, target, frm, to, operator, pid, snapshot="", ts=""):
    rows = _rows(root)
    prev = rows[-1].split("\t")[6] if rows else "GENESIS"
    f = [ts or _now(), action, target, frm or "", to or "", prev, "", operator or "", pid or ""]
    f[6] = _row_hash(f[:6] + f[7:])
    if snapshot:
        src = Path(snapshot)
        if not src.is_file():
            raise FileNotFoundError(snapshot)
        d = root / HIST
        d.mkdir(parents=True, exist_ok=True)
        # ⚠️ Windows：文件名内 `:` 会被解释为**备用数据流(ADS)** ⇒ 主文件 0 字节、静默写坏。
        #    故 action 里的 `:` 一律换成 `-`，并在写后**校验非空 ＋ 逐字节一致**（禁静默）。
        safe_action = action.replace(":", "-").replace("/", "-").replace("\\", "-")
        raw = src.read_bytes()
        name = "%s_%s_%s.snapshot" % (f[0].replace(":", ""), safe_action, _sha(raw)[:12])
        assert ":" not in name, "快照名仍含非法字符：" + name
        dst = d / name
        shutil.copyfile(src, dst)
        if dst.stat().st_size != len(raw) or dst.read_bytes() != raw:
            raise OSError("前像写后校验失败（大小/内容不符）：%s" % dst)
    _append_row(root, f)
    return f


def _verify_chain(root: Path):
    prev, bad = "GENESIS", []
    for i, r in enumerate(_rows(root), 1):
        f = r.split("\t")
        if len(f) != len(HEADER):
            bad.append("第 %d 行列数 %d≠%d" % (i, len(f), len(HEADER)))
            continue
        if f[5] != prev:
            bad.append("第 %d 行 prev_hash 断链" % i)
        if _row_hash(f[:6] + f[7:]) != f[6]:
            bad.append("第 %d 行自校验不符（行被改写？）" % i)
        prev = f[6]
    return bad


# ────────────────────────── 件 2：提案生成 ──────────────────────────
def _parse_ttl(root: Path, kit: Path):
    """调既有 `ttl_sweep.py --dry-run`（**复用不重造** · `R-38`），宽松解析其输出。"""
    s = kit / "tools" / "ttl_sweep.py"
    if not s.is_file():
        print("[WARN] 取不到 %s ⇒ 跳过到期扫描（**出声，不静默**）" % s)
        return []
    cp = subprocess.run([sys.executable, "-B", str(s), "--root", str(root), "--dry-run"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    txt = (cp.stdout or "") + (cp.stderr or "")
    found = []
    for m in re.finditer(r"([0-9A-Za-z_\-./\u4e00-\u9fa5]+\.md)", txt):
        rel = m.group(1).lstrip("./")
        if rel.startswith(CUR.as_posix()) or rel in found:
            continue
        found.append(rel)
    print("[ttl_sweep] rc=%d ｜ 解析到候选项 %d（原文 %d 字符）" % (cp.returncode, len(found), len(txt)))
    return found


def cmd_propose(a):
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root); return 3
    kit = Path(a.kit).resolve() if a.kit else Path(__file__).resolve().parent.parent   # 套件根（`ttl_sweep.py` 在同级 `tools/`）

    cands = []
    if a.candidates:
        cf = Path(a.candidates)
        if not cf.is_file():
            print("[ERR] --candidates 不存在：%s" % cf); return 3
        for ln in cf.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split("\t")
            cands.append({"target": parts[0], "action": (parts[1] if len(parts) > 1 else "retire"),
                          "reason": (parts[2] if len(parts) > 2 else "候选清单输入")})
    else:
        for rel in _parse_ttl(root, kit):
            cands.append({"target": rel, "action": "retire", "reason": "ttl_sweep 判到期"})

    f0 = _fingerprint(root)
    props = []
    for i, c in enumerate(cands, 1):
        t = c["target"]
        p = root / t
        if not p.is_file():
            print("[WARN] 候选项目标不存在，跳过：%s" % t); continue
        props.append({
            "id": "p%03d-%s" % (i, hashlib.sha256(t.encode()).hexdigest()[:6]),
            "action": c["action"], "target": t,
            "from": "active", "to": ("archived" if c["action"] == "retire" else c["action"]),
            "reason": c["reason"],
            "evidence": {"sha256_12": _sha(p.read_bytes())[:12], "bytes": p.stat().st_size},
        })

    if len(props) > a.quota:
        print("[FAIL] 提案 %d 条超配额 %d ⇒ **整批拒**（不写任何件）" % (len(props), a.quota))
        return 1

    f1 = _fingerprint(root)
    if f0 != f1:
        print("[FAIL] 起草过程中库内容发生变化（判据 2：起草不动内容）⇒ 拒写"); return 1

    doc = {"schema": SCHEMA, "generated_at": _now(), "root": str(root),
           "library_digest": _digest(f0), "library_files": len(f0), "library_fingerprint": f0,
           "counts": {"total": len(props)}, "proposals": props}
    body = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(root / PROP_JSON, body)
    fp8 = _sha(body.encode())[:8]
    md = ["# 整理提案（**派生物** · 由 `proposals.json` 生成）", "",
          "> **真源＝`proposals.json`**（md5 前 8：`%s`）。**手改本件不生效**。" % fp8,
          "> 生成：%s ｜ 条数：%d ｜ 配额：%d" % (doc["generated_at"], len(props), a.quota), "",
          "| id | action | target | 理由 |", "|---|---|---|---|"]
    for p in props:
        md.append("| `%s` | %s | `%s` | %s |" % (p["id"], p["action"], p["target"], p["reason"]))
    md.append("")
    _atomic_write(root / PROP_MD, "\n".join(md))

    # ── 熔断·空转计数 ＋ `pending_proposals` 接口字段（设计稿 §三／§八）──
    st = _load_state(root)
    streak = 0 if props else int(st.get("idle_streak") or 0) + 1
    _save_state(root, pending_proposals=len(props), idle_streak=streak, last_propose_at=_now())

    print("[OK] 提案 %d 条 ⇒ %s（指纹 %s）" % (len(props), PROP_JSON.as_posix(), fp8))
    print("[OK] 派生物 ⇒ %s" % PROP_MD.as_posix())
    if not props and streak >= IDLE_LIMIT:
        print("[FUSE:idle] 连续 %d 个周期空提案（阈值 %d）⇒ **停手上报**（防「每跑都无事＝假装在工作」）"
              % (streak, IDLE_LIMIT))
    return 5 if props else 0


# ────────────────────────── 件 3：确认应用 ──────────────────────────
def _load_props(root: Path):
    p = root / PROP_JSON
    if not p.is_file():
        return None, None, None
    raw = p.read_text(encoding="utf-8")
    return json.loads(raw), _sha(raw.encode())[:8], raw


def _do_one(root: Path, p: dict, operator: str):
    """单条应用（WAL：prepared → 改正文 → done）。返回 (ok, msg)。"""
    tgt = root / p["target"]
    if not tgt.is_file():
        return False, "目标不存在：%s" % p["target"]
    act = p["action"]
    if act == "retire":
        snap = tgt
        _ledger_row(root, "retire:prepared", p["target"], "active", "archived", operator, p["id"], snapshot=str(snap))
        dst = root / ARCHIVE / p["target"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(tgt), str(dst))                      # 原子移动，非删除
        _ledger_row(root, "retire:done", p["target"], "active", "archived", operator, p["id"])
        return True, "retire ⇒ %s" % (Path(ARCHIVE) / p["target"]).as_posix()
    if act == "merge":
        # 空档降级（Hermes §三/洞 A）：v1 **不生成新文本**，只互标关系
        _ledger_row(root, "merge:candidate", p["target"], "active", "duplicate-candidate", operator, p["id"])
        return True, "merge ⇒ 仅标为重复候选（**不生成新文本** · v1 降级）"
    if act in ("cool", "promote"):
        _ledger_row(root, act, p["target"], p.get("from", ""), p.get("to", ""), operator, p["id"])
        return True, "%s 记账（不动正文）" % act
    return False, "未知动作：%s" % act


def cmd_apply(a):
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root); return 3
    doc, fp8, _raw = _load_props(root)
    if doc is None:
        print("[FAIL] 取不到 %s —— 请先跑 propose" % PROP_JSON.as_posix()); return 1

    props = doc["proposals"]
    if a.only:
        want = set(x.strip() for x in a.only.split(",") if x.strip())
        props = [p for p in props if p["id"] in want]
    if not props:
        print("[OK] 无可应用提案（0 条）"); return 0

    # ── 防呆② 批模式 ＋ 动作分级（Hermes 四件套之①）──
    heavy = [p["id"] for p in props if p["action"] in HEAVY]
    if a.batch and heavy:
        print("[FAIL] 批模式含语义级动作 %s（`retire`/`merge` **一律逐条**）⇒ 拒" % heavy[:5]); return 1
    if a.batch:
        if a.batch_count is None:
            print("[FAIL] 批模式须显式 `--batch-count N`（与实际条数核对）⇒ 拒"); return 1
        if a.batch_count != len(props):
            print("[FAIL] `--batch-count %d` ≠ 实际 %d ⇒ 拒" % (a.batch_count, len(props))); return 1

    # ── 防呆③ 回贴提案指纹 ──
    if not a.preview:
        if not a.proposal_fingerprint:
            print("[FAIL] 须回贴提案指纹（`--proposal-fingerprint %s`）——「看过」的成本≥扫一遍 ⇒ 拒" % fp8); return 1
        if a.proposal_fingerprint != fp8:
            print("[FAIL] 指纹不符：给 %s ≠ 实际 %s ⇒ 拒" % (a.proposal_fingerprint, fp8)); return 1

    # ── 判据 11 分叉可侦测 ＋ 判据 9 他源静默（**自起草以来**库内容须未变）──
    f0 = _fingerprint(root)
    d0 = _digest(f0)
    base = doc.get("library_digest")
    if base and base != d0 and not a.accept_drift:
        diff = [k for k in (set(f0) | set(doc.get("library_fingerprint") or {}))
                if f0.get(k) != (doc.get("library_fingerprint") or {}).get(k)]
        print("[FAIL] **分叉/他源变更可侦测**：自起草（%s）以来库内容已变 ⇒ 出声不动手"
              "（草案指纹 %s ≠ 当前 %s；确要跑请 `--accept-drift`）" % (doc.get("generated_at"), base, d0))
        if diff:
            print("       变更文件（前 5）：%s" % diff[:5])
        return 1
    sp = root / STATE
    if sp.is_file():
        last = json.loads(sp.read_text(encoding="utf-8")).get("last_seen", {})
        if last.get("digest") and last["digest"] != d0 and not a.accept_drift:
            print("[FAIL] **分叉可侦测**：上次指纹 %s ≠ 当前 %s ⇒ 出声不动手（确要跑请 `--accept-drift`）"
                  % (last["digest"], d0)); return 1

    # ── 防呆④ 逐条 diff 预览（人确认的必须是「变更结果」）──
    print("==== 变更预览（%d 条）" % len(props))
    for p in props:
        print("  [%s] %-7s `%s` ⇒ %s" % (p["id"], p["action"], p["target"], p.get("to", "-")))
    if a.preview:
        print("==== 预览完（**未写任何件**）—— 确认后加 `--yes --proposal-fingerprint %s` 执行" % fp8)
        return 0
    if not a.yes:
        print("[FAIL] 须显式 `--yes` ⇒ 拒"); return 1

    # ── 幂等：已 done 的 proposal_id 跳过 ──
    done = set()
    for r in _rows(root):
        f = r.split("\t")
        if len(f) == len(HEADER) and f[1].endswith(":done"):
            done.add(f[8])

    operator = a.operator or "human:batch" if a.batch else (a.operator or "human:single")
    okn, skipn = 0, 0
    for p in props:
        if p["id"] in done:
            print("  [skip] %s 已应用（幂等）" % p["id"]); skipn += 1; continue
        ok, msg = _do_one(root, p, operator)
        print("  [%s] %s ｜ %s" % ("OK" if ok else "FAIL", p["id"], msg))
        okn += 1 if ok else 0

    # ── 判据 9 他源静默检测：非目标文件哈希必须不变 ──
    targets = set(p["target"] for p in props)
    f1 = _fingerprint(root)
    drift = [k for k in (set(f0) | set(f1))
             if (k not in targets) and f0.get(k) != f1.get(k) and not k.startswith(ARCHIVE + "/")]
    if drift:
        print("[FAIL] **他源静默变更检出**：非目标文件 %s 发生变化 ⇒ 出声并停（本批已改项可凭前像回滚）" % drift[:5])
        return 1

    _save_state(root, pending_proposals=max(0, len(doc["proposals"]) - (len(done) + okn)),
                last_seen={"at": _now(), "count": len(f1), "digest": _digest(f1)})
    bad = _verify_chain(root)
    if bad:
        print("[FAIL] 台账链校验：%s" % bad[:3]); return 1
    print("[OK] 应用 %d 条（跳过 %d）｜ 台账链完整 ｜ last_seen 已更新 → %s" % (okn, skipn, _digest(f1)))
    return 0


def cmd_state(a):
    root = Path(a.root).resolve()
    fp = _fingerprint(root)
    last = _load_state(root).get("last_seen", {}) or {}
    st = _load_state(root)
    print("库根：%s" % root)
    print("pending_proposals：%s（**接口字段** · 宿主若读可见到期数，**不承诺任何宿主会读** · 设计稿 §三）"
          % st.get("pending_proposals", 0))
    print("文件数：%d ｜ 当前指纹：%s" % (len(fp), _digest(fp)))
    print("上次指纹：%s（%s）" % (last.get("digest", "-"), last.get("at", "-")))
    if not last.get("digest"):
        verdict = "**无基线（首次）** —— 尚无上次指纹可比 ⇒ **不是漂移**"
    elif last.get("digest") == _digest(fp):
        verdict = "一致"
    else:
        verdict = "**已漂移**（承判据 11 出声）"
    print("判定：%s" % verdict)
    # ── 2026-10-01 补（外部实机测试 F6 驱动）：**与速读包首行对账** ──
    # 治「显示面静默失真」：待确认行没有任何工具会刷新 ⇒ 失真时比没有这一行更坏。
    # 本对账＝把 `spec/记忆形成与容量治理.md` §十一 已写好的判据**可执行化**（零新概念）。
    import re as _re
    rp = root / "01-记忆档案" / "记忆工程" / "会话速读包.md"
    pend = st.get("pending_proposals", 0)
    if not rp.is_file():
        print("[WARN] 对账：未见 01-记忆档案/记忆工程/会话速读包.md ⇒ 跳过（口径见规格 §十一）")
        return 0
    m = _re.search(r"待确认\**\s*[:：]\s*\**\s*(\d+)", rp.read_text(encoding="utf-8", errors="replace"))
    if not m:
        print("[WARN] 对账：速读包首行未见「待确认：N 条」⇒ 缺约定行（口径见规格 §十一）")
        return 0
    shown = int(m.group(1))
    if shown != pend:
        print("[FAIL] 对账：速读包首行「待确认：%d 条」≠ pending_proposals=%d ⇒ **显示面失真**（请会话更新该行）"
              % (shown, pend))
        return 1
    print("[OK] 对账：速读包首行 = pending_proposals = %d" % pend)
    return 0


# ────────────────────────── 件 4：台账与前像（**已并入 · 原 `curate_ledger.py`**）──────────────────────────
def cmd_ledger(a):
    """台账三子命令 —— 与件 2／件 3 **同执行体**（合并去重 · 批 3 收口）。
    判据不变：**只增**（无删除/改写分支）、**只写 `_meta/curation/`**、**不动记忆正文**、**零依赖零网**。"""
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root); return 3
    if a.ledger_cmd == "append":
        row = _ledger_row(root, a.action, a.target, a.frm, a.to, a.operator, a.proposal_id,
                          snapshot=a.snapshot, ts=a.ts)
        print("[OK] 已追加台账行：%s %s  (row_hash=%s, prev=%s)" % (row[1], row[2], row[6], row[5]))
        if a.snapshot:
            print("[OK] 前像：%s" % (HIST.as_posix()))
        return 0
    if a.ledger_cmd == "show":
        rows = _rows(root)
        print("台账：%s" % LEDGER.as_posix())
        print("行数：%d" % len(rows))
        for r in rows:
            print("  " + r)
        return 0
    bad = _verify_chain(root)                        # verify
    if bad:
        for b in bad[:10]:
            print("[FAIL] %s" % b)
        print("[结论] 校验失败：%d 处" % len(bad)); return 1
    print("[结论] 链条完整（%d 行）" % len(_rows(root)))
    return 0


# ────────────────────────── 熔断三类（设计稿 §八 · 代码化）──────────────────────────
def _borrow_brain_check(src: str):
    """熔断·借脑：**静态**自查自身源码 —— ① import 是否全为标准库 ② 是否现借脑特征串。
    返回 (ok, 证据列表)；`ok=False` ⇒ 触发。"""
    import ast
    hits = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return False, ["源码语法错：%s" % e]
    std = set(getattr(sys, "stdlib_module_names", ()))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name.split(".")[0] not in std:
                    hits.append("import %s（非标准库）" % al.name)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.level == 0 and top and top not in std:
                hits.append("from %s import …（非标准库）" % node.module)
    low = src.lower()
    for tk in _BORROW_TOKENS:
        if tk in low:
            hits.append("命中借脑特征：%s" % tk)
    return (not hits), hits[:8]


def cmd_fuse(a):
    """三类熔断状态（**代码化** · 各带触发点）：空转／误判／借脑。
    退出码：0 未触发 ｜ 1 **触发⇒停手上报** ｜ 3 参数/IO 错。"""
    root = Path(a.root).resolve()
    if not root.is_dir():
        print("[ERR] 库根不存在：%s" % root); return 3
    st = _load_state(root)
    fired = []

    # ① 空转（触发点＝每个周期 `propose` 之后由人看输出）
    streak = int(st.get("idle_streak") or 0)
    print("[FUSE:idle] 空转 —— 连续空提案 %d 周期 ／ 阈值 %d" % (streak, IDLE_LIMIT))
    if streak >= IDLE_LIMIT:
        fired.append("idle")
        print("        ⇒ 触发（防「每跑都无事＝假装在工作」）")

    # ② 误判（触发点＝取证期人工抽核）
    print("[FUSE:misjudge] 误判 —— 抽核 checked=%s ／ wrong=%s ／ 阈值=%s"
          % (a.checked if a.checked is not None else "-",
             a.wrong if a.wrong is not None else "-",
             a.max_wrong_rate if a.max_wrong_rate is not None else "**未定**（设计稿 §十-3）"))
    if a.checked:
        if a.max_wrong_rate is None:
            print("        ⇒ 阈值未定 ⇒ **仅记录、不熔断**（不猜阈值）")
        else:
            rate = (a.wrong or 0) / a.checked
            print("        误判率 %.3f" % rate)
            if rate > a.max_wrong_rate:
                fired.append("misjudge")
                print("        ⇒ 触发")
    else:
        print("        ⇒ 数据不足（未提供 --checked）")

    # ③ 借脑（触发点＝设计评审时）
    ok, hits = _borrow_brain_check(Path(__file__).read_text(encoding="utf-8"))
    print("[FUSE:borrow-brain] 借脑 —— 本执行体依赖自查：%s" % ("零外部依赖（仅标准库）" if ok else "命中 %s" % hits))
    if not ok:
        fired.append("borrow-brain")
        print("        ⇒ 触发（守零依赖 · 设计稿 §七-2／§八）")

    print("==== 熔断状态：%s ====" % ("**触发 %s ⇒ 停手上报**" % fired if fired else "三类均未触发"))
    return 1 if fired else 0


def main():
    ap = argparse.ArgumentParser(description="整理层件 2／件 3（原型）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("propose"); p1.add_argument("--root", required=True)
    p1.add_argument("--kit", default=""); p1.add_argument("--candidates", default="")
    p1.add_argument("--quota", type=int, default=20)
    p2 = sub.add_parser("apply"); p2.add_argument("--root", required=True)
    for f in ("--only", "--proposal-fingerprint", "--operator"): p2.add_argument(f, default="")
    p2.add_argument("--preview", action="store_true"); p2.add_argument("--yes", action="store_true")
    p2.add_argument("--batch", action="store_true"); p2.add_argument("--accept-drift", action="store_true")
    p2.add_argument("--batch-count", dest="batch_count", type=int, default=None)
    p3 = sub.add_parser("state"); p3.add_argument("--root", required=True)

    # 件 4 台账（**并入入口** —— 与件 2／件 3 同执行体）
    p4 = sub.add_parser("ledger")
    lsub = p4.add_subparsers(dest="ledger_cmd", required=True)
    la = lsub.add_parser("append")
    la.add_argument("--root", required=True)
    la.add_argument("--action", required=True); la.add_argument("--target", required=True)
    for f in ("--frm", "--to", "--operator", "--snapshot", "--ts"):
        la.add_argument(f, default="")
    la.add_argument("--proposal-id", dest="proposal_id", default="")
    for nm in ("show", "verify"):
        ls = lsub.add_parser(nm); ls.add_argument("--root", required=True)

    # 熔断三类（空转／误判／借脑）
    pf = sub.add_parser("fuse"); pf.add_argument("--root", required=True)
    pf.add_argument("--checked", type=int, default=None)
    pf.add_argument("--wrong", type=int, default=None)
    pf.add_argument("--max-wrong-rate", dest="max_wrong_rate", type=float, default=None)

    a = ap.parse_args()
    return {"propose": cmd_propose, "apply": cmd_apply, "state": cmd_state,
            "ledger": cmd_ledger, "fuse": cmd_fuse}[a.cmd](a)


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

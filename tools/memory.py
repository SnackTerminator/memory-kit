#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memory —— memory-kit 的读取路径（**无常驻 · 随盘跑 · 零依赖**）。

契约见同目录 `cli-spec.json`（本实现须与之一致）。

命令：
  python tools/memory.py get <相对路径>            # 原样输出该件
  python tools/memory.py search <关键词> [--layer L2] [--limit N]
  python tools/memory.py ask <问句> [--top-k N] [--layer L2]   # ★ 相关度检索（带分数）
  python tools/memory.py index [--dry-run]        # 建倒排索引（派生物 08-检索索引/inverted.json）
  python tools/memory.py list [--layer L2]
  python tools/memory.py reindex [--dry-run]      # 只写派生物 08-检索索引/_index.tsv

★ 读命令**一律不改库**；写命令只有 `reindex`／`index`，**只写派生物**，**不碰真源**。
★ `search` 与 `ask` 分工（2026-10-01 加）：
    - `search` ＝ **关键词定位**（逐行子串，给人/宿主精确定位用，语义未变）；
    - `ask`   ＝ **相关度检索**（倒排 ＋ BM25 打分 ＋ 稳定排序，给"提问→取最相关若干条"用）。

退出码：0 成功/有命中 ｜ 1 无命中 ｜ 3 参数错 ｜ 4 找不到该件
"""
import argparse
import json
import math
import os
import re
import sys
import time
import sys as _sys
sys.dont_write_bytecode = True  # ★ 保证「代码根只读」：禁写字节码（须在 import kitmeta 之前）—— 治 E631
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitmeta  # noqa: E402

INDEX_REL = "08-检索索引/_index.tsv"
INVERTED_FMT = "08-检索索引/inverted-{level}.json"   # level: doc ｜ line
# ★ 倒排索引**格式版本**（2026-10-02 起 · 升位 ⇒ 旧索引判「不新鲜」自动重建）。
#   1 = 中文**仅 bigram**（单字查询失效）；2 = 中文 **unigram ＋ bigram 同出**。
IDX_VERSION = 2

# ★ BM25 参数（倒排检索）——与「壳内 BM25 基线」同值，便于同管线可比
K1, B = 1.5, 0.75
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_ASCII = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list:
    """零依赖分词：英文/数字按词元；中文按**单字（unigram）＋ 二元组（bigram）同出**。

    ★ 中英混排两条都走 —— 中文无空格，bigram 是"零依赖"下最稳的可召回切法。
    ★ 2026-10-02 **加 unigram**（治「单字查询失效」：原先中文只出 bigram ⇒ 用户查单个字
      的键在索引里根本不存在，恒零命中）。**外部一手依据两条**：
        ① Elasticsearch `cjk_bigram` token filter 的 `output_unigrams`（官方文档原文：
           "emit tokens in both bigram and unigram form … used for a combined
           unigram+bigram approach"；现行 9.x API 仍具该属性）
        ② SQLite FTS5 第三方分词器 `cjk`（MIT）的 `unigram 1`（README 原文："index single
           characters so one-character queries match inside text"，索引约 **+70%**）
      代价＝索引膨胀（本机实测见 `CHANGELOG`）；**旧索引须重建** ⇒ 判据＝`IDX_VERSION` 升位。
    """
    t = (text or "").lower()
    out = [m.group(0) for m in _ASCII.finditer(t)]
    for m in _CJK.finditer(t):
        s = m.group(0)
        if len(s) == 1:
            out.append(s)
        else:
            out.extend(s[i:i + 1] for i in range(len(s)))        # 单字（unigram）
            out.extend(s[i:i + 2] for i in range(len(s) - 1))    # 二元组（bigram）
    return out


def _iter_docs(root: Path):
    """产出 (rel, text, meta)。复用 `iter_md` 的扫描面（`01-记忆档案/`，排除 `.private/`）。"""
    for p, rel in iter_md(root):
        if ".private/" in rel.replace("\\", "/"):
            continue
        text = read_text(p)
        meta, _b, _t = kitmeta.read_meta(p)
        yield rel, text, meta


def _index_path(root: Path, level: str = "line") -> Path:
    return root / INVERTED_FMT.format(level=level)


def _corpus_state(root: Path):
    """语料指纹（判索引是否过期）。**两级**（2026-10-01 加 · 治「静默过期」）：

      - 粗：文件数 ＋ 最新 mtime；
      - **细：逐件 `(rel, size)` 的 sha1 摘要** —— 同文件数、同 mtime 的**改名／等量替换**
        变化也能检出（外部评审第 6 轮构造复现的三类静默过期中，前两类由此覆盖）。

    **已知边界（如实写进 spec）**：改内容且**尺寸不变＋mtime 被伪回**⇒ 仍不可判。
    """
    base = root / kitmeta.ARCHIVE_DIR
    n, mx, acc = 0, 0.0, []
    if base.is_dir():
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if not d.startswith("_") and d != "__pycache__"]
            for fn in sorted(fns):
                if fn.lower().endswith(".md"):
                    p = os.path.join(dp, fn)
                    try:
                        n += 1
                        mx = max(mx, os.path.getmtime(p))
                        acc.append("%s|%d" % (os.path.relpath(p, root).replace("\\", "/"),
                                              os.path.getsize(p)))
                    except OSError:
                        pass
    import hashlib
    dig = hashlib.sha1("\n".join(sorted(acc)).encode("utf-8")).hexdigest()[:16]
    return {"files": n, "max_mtime": round(mx, 3), "digest": dig}


def build_index(root: Path, level: str = "line") -> dict:
    """全量重建倒排（纯内存计算，返回 dict；不落盘）。

    **两级粒度**（2026-10-01 加 · 治「件级排序过粗」）：
      - `doc`  ＝ **一件一条**（整篇正文当一个文档）；
      - `line` ＝ **一行一条**（一条记忆条目／一行正文当一个文档）⇒ **返回粒度高、排序更细**。
    两级各自成索引文件，互不覆盖。
    """
    docs, postings, df = [], {}, {}
    total_len = 0
    for rel, text, meta in _iter_docs(root):
        _m, body = kitmeta.parse_frontmatter(text)
        lay = str(meta.get("layer", "")).strip()
        fam = str(meta.get("family", "")).strip()
        if level == "line":
            units = [(no, ln) for no, ln in enumerate(body.splitlines(), 1) if ln.strip()]
        else:
            units = [(0, body)]
        for no, chunk in units:
            toks = tokenize(chunk)
            if not toks:
                continue
            i = len(docs)
            docs.append({"path": rel, "line": no, "len": len(toks),
                         "layer": lay, "family": fam, "head": chunk.strip()[:120]})
            total_len += len(toks)
            tf = {}
            for w in toks:
                tf[w] = tf.get(w, 0) + 1
            for w, c in tf.items():
                df[w] = df.get(w, 0) + 1
                postings.setdefault(w, []).append([i, c])
    n = len(docs) or 1
    return {"version": IDX_VERSION, "level": level, "built_at": int(time.time()), "n": len(docs),
            "avgdl": round(total_len / n, 4), "df": df, "postings": postings,
            "docs": docs, "corpus": _corpus_state(root)}


def index_is_fresh(root: Path, idx: dict, level: str = "line") -> bool:
    if not isinstance(idx, dict) or idx.get("version") != IDX_VERSION:
        return False
    if idx.get("level", "doc") != level:
        return False
    return idx.get("corpus") == _corpus_state(root)


def load_or_build(root: Path, level: str = "line"):
    """有**新鲜**索引就用；否则内存现建（并告知可 `index` 持久化）。

    返回 `(idx, source, stale)`：`stale=True` ＝**盘上有索引但已过期**（被判定不一致后重建）。
    """
    p = _index_path(root, level)
    if p.is_file():
        try:
            idx = json.loads(read_text(p))
            if index_is_fresh(root, idx, level):
                return idx, "index", False
            return build_index(root, level), "memory", True
        except (ValueError, OSError):
            pass
    return build_index(root, level), "memory", False


def bm25_scores(idx: dict, query: str, layer: str):
    """倒排 BM25 打分（**不截断**）。返回按分降序、同分按 docs 序的 `[(docIdx, score)]`。"""
    q = set(tokenize(query))
    n, avgdl = idx.get("n", 0), idx.get("avgdl", 1.0) or 1.0
    if not n or not q:
        return []
    acc = {}
    for w in sorted(q):                      # ★ 固定求和顺序（治「并列名次随 PYTHONHASHSEED 翻转」）
        pl = idx["postings"].get(w)
        if not pl:
            continue
        dfw = idx["df"].get(w, 0)
        idf = math.log(1 + (n - dfw + 0.5) / (dfw + 0.5))
        for di, tf in pl:
            dl = idx["docs"][di]["len"] or 1
            acc[di] = acc.get(di, 0.0) + idf * (tf * (K1 + 1)) / (
                tf + K1 * (1 - B + B * dl / avgdl))
    rows = [(di, s) for di, s in acc.items()
            if not (layer and idx["docs"][di].get("layer") != layer)]
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    return rows


def bm25_query(idx: dict, query: str, top_k: int, layer: str):
    """倒排 BM25 打分 → 前 top_k 条。**稳定排序**：分降序 → 同分按 docs 序（＝路径序）。"""
    rows = bm25_scores(idx, query, layer)
    out = []
    for di, s in rows[:top_k]:
        d = idx["docs"][di]
        out.append({"path": d["path"], "line": d.get("line", 0), "score": round(s, 6),
                    "head": d.get("head", ""),
                    "layer": d.get("layer", ""), "family": d.get("family", "")})
    return out


def bm25_by_session(idx: dict, query: str, top_k: int, layer: str):
    """**件级返回 ＋ 行级打分**（max 聚合 · 2026-10-01 加）。

    用途：行级给出的**排序精度**，件级给出的**覆盖广度**，二者本会互相挤压
    （实测：件级 Hit 97.71%／MRR 0.6930；行级 Hit 95.14%／MRR 0.7283）。
    本函数取 **max-pooling**：每个件取其**最相关那一行**的分作为件的分 ⇒ 兼得两者。
    """
    rows = bm25_scores(idx, query, layer)
    best = {}
    for di, s in rows:                      # rows 已按分降序 ⇒ 首次即该件最高分
        p = idx["docs"][di]["path"]
        if p not in best:
            d = idx["docs"][di]
            best[p] = {"path": p, "line": d.get("line", 0), "score": round(s, 6),
                       "head": d.get("head", ""), "layer": d.get("layer", ""),
                       "family": d.get("family", "")}
    ordered = sorted(best.values(), key=lambda h: (-h["score"], h["path"]))
    return ordered[:top_k]


def cmd_index(root: Path, level: str, dry_run: bool, as_json: bool) -> int:
    """建/重建倒排索引。**只写 08-检索索引/，不碰真源。**"""
    rel = INVERTED_FMT.format(level=level)
    if dry_run:
        st = _corpus_state(root)
        print(f"[dry] 将写 {rel} —— 语料 {st['files']} 件 · 粒度 {level}（**仅派生物，不动真源**）")
        return 0
    idx = build_index(root, level)
    target = _index_path(root, level)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")),
                      encoding="utf-8")
    size = target.stat().st_size
    if as_json:
        print(json.dumps({"written": rel, "level": level, "docs": idx["n"],
                          "terms": len(idx["df"]), "bytes": size}, ensure_ascii=False))
    else:
        print(f"-- 已建倒排索引：{rel} ｜ 粒度 {level} ｜ 文档 {idx['n']} "
              f"｜ 词项 {len(idx['df'])} ｜ {size:,} B（**仅派生物 · 真源未动**）")
    return 0



def find_root(explicit=None) -> Path:
    """库根：显式 > 含 AGENTS.md 的当前目录（向上找）> 套件根的 instance/ > 套件根。"""
    if explicit:
        return Path(explicit).resolve()
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / "AGENTS.md").is_file():
            return p
    kit = Path(__file__).resolve().parents[1]
    inst = kit / "instance"
    return inst if inst.is_dir() else kit


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def iter_md(root: Path):
    base = root / kitmeta.ARCHIVE_DIR
    if not base.is_dir():
        return
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if not d.startswith("_") and d != "__pycache__"]
        for fn in sorted(fns):
            if fn.lower().endswith(".md"):
                p = Path(dp) / fn
                yield p, p.relative_to(root).as_posix()


def cmd_get(root: Path, rel: str, as_json: bool) -> int:
    # ★ 两侧都须 resolve：Windows 下 `tempfile` 会给 8.3 短名（如 `WEIZHI~1`），
    #   而 `(root/rel).resolve()` 展开为长名 ⇒ 未规范 root 会使 relative_to 误判"越出库根"。
    root = root.resolve()
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        print(f"[FAIL] 路径越出库根：{rel}")
        return 3
    if not p.is_file():
        print(f"[FAIL] 找不到该件：{rel}")
        return 4
    text = read_text(p)
    if as_json:
        meta, body = kitmeta.parse_frontmatter(text)
        print(json.dumps({"path": rel, "meta": meta, "body": body}, ensure_ascii=False))
    else:
        sys.stdout.write(text)
    return 0


def cmd_search(root: Path, kw: str, layer: str, limit: int, as_json: bool) -> int:
    hits, scanned = [], 0
    for p, rel in iter_md(root):
        # 2026-10-01 补（外部实机测试 F5 驱动）：`.private/` 不进检索面 ——
        # 与 `MANIFEST §⑦`「陌生宿主对 .private 不出库」的约定**在实现层对齐**（原仅约定、非机制）。
        if ".private/" in rel.replace("\\", "/"):
            continue
        scanned += 1
        meta, _b, _t = kitmeta.read_meta(p)
        lay = str(meta.get("layer", "")).strip()
        if layer and lay != layer:
            continue
        for i, line in enumerate(read_text(p).splitlines(), 1):
            if kw in line:
                hits.append({"path": rel, "line": i, "text": line.strip()[:200]})
                if limit and len(hits) >= limit:
                    break
        if limit and len(hits) >= limit:
            break
    if as_json:
        print(json.dumps({"query": kw, "scanned": scanned, "hits": hits}, ensure_ascii=False))
    else:
        print(f"-- 扫描 {scanned} 件 ｜ 命中 {len(hits)} 处")
        for h in hits:
            print(f"{h['path']}:{h['line']}: {h['text']}")
    return 0 if hits else 1


def cmd_ask(root: Path, query: str, layer: str, top_k: int, level: str, as_json: bool) -> int:
    """**相关度检索**：问句 → 倒排 BM25 → 带分数的 top-k（顺序保留，供宿主直接消费）。

    `level` 三档：`session`（默认 · 件级返回 ＋ 行级打分 max 聚合）／`doc`／`line`。
    """
    idx_level = "line" if level == "session" else level
    idx, src, stale = load_or_build(root, idx_level)
    if level == "session":
        hits = bm25_by_session(idx, query, top_k, layer)
    else:
        hits = bm25_query(idx, query, top_k, layer)
    if as_json:
        print(json.dumps({"query": query, "backend": "bm25-index", "level": level,
                          "index_level": idx_level, "index": src, "stale": stale,
                          "n_docs": idx.get("n", 0), "hits": hits}, ensure_ascii=False))
    else:
        print(f"-- 索引来源 {src}{'（⚠ 盘上索引已过期 ⇒ 已内存重建）' if stale else ''} "
              f"｜ 粒度 {level} ｜ 文档 {idx.get('n', 0)} ｜ 命中 {len(hits)}")
        for h in hits:
            loc = f"{h['path']}:{h['line']}" if h.get("line") else h["path"]
            print(f"{h['score']:.4f}\t{loc}")
    return 0 if hits else 1


def cmd_list(root: Path, layer: str, as_json: bool) -> int:
    rows = []
    for _p, rel, meta, _b in kitmeta.iter_l2(root):
        lay = str(meta.get("layer", "")).strip()
        if layer and lay != layer:
            continue
        rows.append({"path": rel, "layer": lay, "family": str(meta.get("family", "")).strip(),
                     "ttl": str(meta.get("ttl", "")).strip()})
    if as_json:
        print(json.dumps({"count": len(rows), "items": rows}, ensure_ascii=False))
    else:
        print(f"-- 条目 {len(rows)} 件")
        for r in rows:
            print(f"{r['layer']}\t{r['family'] or '-'}\t{r['path']}")
    return 0


def cmd_reindex(root: Path, dry_run: bool, as_json: bool) -> int:
    """重建索引派生物。**只写 08-检索索引/，不碰真源。**"""
    rows = []
    for p, rel in iter_md(root):
        meta, body, _t = kitmeta.read_meta(p)
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        rows.append({
            "path": rel,
            "layer": str(meta.get("layer", "")).strip(),
            "family": str(meta.get("family", "")).strip(),
            "ttl": str(meta.get("ttl", "")).strip(),
            "chars": len(body),
            "head": first[:60].replace("\t", " "),
        })
    target = root / INDEX_REL
    if dry_run:
        print(f"[dry] 将写 {INDEX_REL} —— {len(rows)} 行（**仅派生物，不动真源**）")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["path\tlayer\tfamily\tttl\tchars\thead"]
    for r in rows:
        lines.append("\t".join([r["path"], r["layer"], r["family"], r["ttl"], str(r["chars"]), r["head"]]))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if as_json:
        print(json.dumps({"written": INDEX_REL, "rows": len(rows)}, ensure_ascii=False))
    else:
        print(f"-- 已重建索引：{INDEX_REL} ｜ {len(rows)} 行（**仅派生物 · 真源未动**）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="memory", description="memory-kit 读取路径（无常驻 · 零依赖）")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("get"); g.add_argument("path")
    s = sub.add_parser("search"); s.add_argument("kw"); s.add_argument("--layer", default=""); s.add_argument("--limit", type=int, default=0)
    k = sub.add_parser("ask"); k.add_argument("query"); k.add_argument("--layer", default=""); k.add_argument("--top-k", type=int, default=10); k.add_argument("--level", choices=["session", "doc", "line"], default="session")
    i = sub.add_parser("index"); i.add_argument("--dry-run", action="store_true"); i.add_argument("--level", choices=["doc", "line"], default="line")
    l = sub.add_parser("list"); l.add_argument("--layer", default="")
    r = sub.add_parser("reindex"); r.add_argument("--dry-run", action="store_true")
    # selftest 挂在这里（不进 spec 的命令面，属实现自检）
    sub.add_parser("selftest")

    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        return selftest()

    root = find_root(a.root)
    print(f"-- 库根：{root}", file=sys.stderr)

    if a.cmd == "get":
        return cmd_get(root, a.path, a.json)
    if a.cmd == "search":
        return cmd_search(root, a.kw, a.layer, a.limit, a.json)
    if a.cmd == "ask":
        return cmd_ask(root, a.query, a.layer, a.top_k, a.level, a.json)
    if a.cmd == "index":
        return cmd_index(root, a.level, a.dry_run, a.json)
    if a.cmd == "list":
        return cmd_list(root, a.layer, a.json)
    if a.cmd == "reindex":
        return cmd_reindex(root, a.dry_run, a.json)
    ap.print_help()
    return 3


def selftest() -> int:
    """八态自检：get ／ search ／ reindex ／ index ／ ask ／ 中文 bigram ／ 静默过期检出 ／ **中文单字**。（**全部只写派生物，不碰真源**）"""
    import tempfile
    print("== selftest（八态）==")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / kitmeta.ARCHIVE_DIR
        d.mkdir(parents=True)
        (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        (d / "a.md").write_text("---\nlayer: L2\nfamily: 测试\n---\n关键字XYZ 在这里\n", encoding="utf-8")
        # 中文样本：正文「我喜欢喝拿铁咖啡。」—— 用于验 **bigram 组合召回**
        # （查询「喜欢咖啡」**不是**正文的连续子串 ⇒ 只有 bigram 才能命中）
        (d / "b.md").write_text("---\nlayer: L2\nfamily: 中文测试\n---\n我喜欢喝拿铁咖啡。\n", encoding="utf-8")

        # 态1：get 命中
        c1 = (root / kitmeta.ARCHIVE_DIR / "a.md")
        rc1 = cmd_get(root, "01-记忆档案/a.md", False)
        ok1 = rc1 == 0 and c1.is_file()

        # 态2：search 命中 / 未命中
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc2a = cmd_search(root, "关键字XYZ", "", 0, True)
            rc2b = cmd_search(root, "绝不存在ZZZ", "", 0, True)
        ok2 = rc2a == 0 and rc2b == 1

        # 态3：reindex 只写派生物（真源 mtime/size 不变）+ 可重建（两次内容一致）
        before = (d / "a.md").stat().st_size
        cmd_reindex(root, False, True)
        idx = root / INDEX_REL
        first = read_text(idx)
        cmd_reindex(root, False, True)
        ok3 = (idx.is_file()
               and (d / "a.md").stat().st_size == before
               and first == read_text(idx)
               and "01-记忆档案/a.md" in first)

        # 态4：index 只写派生物（真源 size 不变）＋ 可重建（两次内容一致）
        before4 = (d / "a.md").stat().st_size
        cmd_index(root, "line", False, True)
        inv = root / INVERTED_FMT.format(level="line")
        inv1 = read_text(inv)
        cmd_index(root, "line", False, True)
        ok4 = (inv.is_file()
               and (d / "a.md").stat().st_size == before4
               and inv1 == read_text(inv))

        # 态5：ask 命中/未命中/带分数/顺序稳定（同查询两次结果逐字一致）
        def _ask(q):
            b2 = io.StringIO()
            with contextlib.redirect_stdout(b2):
                rc = cmd_ask(root, q, "", 5, "line", True)
            return rc, json.loads(b2.getvalue())

        rc5a, o5a = _ask("关键字XYZ")
        # ★ 阴性样本须与语料**无任何单字重叠**（2026-10-02 加 unigram 后修）：
        #   原「绝不存在ZZZ」含常用字「在」，而语料里有「在这里」⇒ 单字键命中 ⇒ 判据失效。
        rc5b, o5b = _ask("番茄炖牛腩QWE")
        rc5c, o5c = _ask("关键字XYZ")
        ok5 = (rc5a == 0 and bool(o5a["hits"]) and o5a["hits"][0]["score"] > 0
               and o5a["hits"][0]["path"] == "01-记忆档案/a.md"
               and rc5b == 1 and not o5b["hits"]
               and o5a["hits"] == o5c["hits"])

        # 态6：中文 bigram 召回 —— 「喜欢咖啡」不是正文的连续子串（正文＝「我喜欢喝拿铁咖啡。」）
        # ⇒ 只有 bigram 切法才能命中（排除「整句子串匹配」的退化情形）
        rc6, o6 = _ask("喜欢咖啡")
        ok6 = (rc6 == 0 and bool(o6["hits"])
               and o6["hits"][0]["path"] == "01-记忆档案/b.md")

        # 态7：**静默过期检出**（改名型 —— 文件数与 max mtime 均不变 ⇒ 只有 `(rel,size)` 摘要能抓）
        #   由来＝外部评审第 6 轮构造复现：旧指纹下 `ask` 仍返回**已不存在的旧路径**。
        (d / "a.md").rename(d / "a7.md")
        rc7, o7 = _ask("关键字XYZ")
        ok7 = (rc7 == 0 and bool(o7["hits"])
               and o7["hits"][0]["path"] == "01-记忆档案/a7.md"
               and o7.get("stale") is True)

        # 态8：**中文单字可命中**（2026-10-02 加 · 治「单字查询失效」）
        #   正文＝「我喜欢喝拿铁咖啡。」；旧实现中文**只出 bigram** ⇒ 查询键 `咖`
        #   在索引中根本不存在 ⇒ 恒零命中（外部评审第 6 轮抓出）。
        rc8, o8 = _ask("咖")
        ok8 = (rc8 == 0 and bool(o8["hits"])
               and o8["hits"][0]["path"] == "01-记忆档案/b.md")

    cases = [("态1 get 可读", ok1), ("态2 search 命中/未命中", ok2),
             ("态3 reindex 只写派生物且可重建", ok3),
             ("态4 index 只写派生物且可重建", ok4),
             ("态5 ask 打分命中/未命中/顺序稳定", ok5),
             ("态6 中文 bigram 召回", ok6),
             ("态7 静默过期检出（改名型）", ok7),
             ("态8 中文单字命中（unigram）", ok8)]
    good = True
    for name, r in cases:
        print(f"  [{'OK' if r else 'FAIL'}] {name}")
        good = good and r
    print(f"== selftest {'全绿' if good else '有红'}（{len(cases)} 态）==")
    return 0 if good else 1


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

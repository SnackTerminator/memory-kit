#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memory-kit 元数据与扫描公共模块（**纯标准库 · 零依赖 · 无常驻**）。

被四闸执行体共用（`l2_admit`／`capacity_gate`／`ttl_sweep`／`dedup_scan`／`pointer_check`）。
本模块**只做读取与解析**，不做任何判定、**不改库**。

### 条目元数据约定（v1 · 随 `spec/记忆形成与容量治理.md` 发行）

L2 条目＝markdown 件，头部带**极简 YAML 子集** frontmatter（只支持一层缩进，不引 yaml 库）：

    ---
    layer: L2
    created: 2026-09-29
    ttl: permanent          # permanent | YYYY-MM-DD | <n>d
    family: <族名>           # 可选；去重/蒸馏分组
    admit:                  # 入口闸三问
      new_fact: true
      changes_action: true
      source: "<来源>"
    supersedes: <旧条相对路径>    # 可选 · 修订
    deprecated: true             # 可选 · 废弃
    superseded_by: <新条相对路径>  # 废弃时必填（供 pointer_check 判）
    ---

**无 frontmatter 或 frontmatter 内无 `layer:` 的件 ⇒ 不视为 L2 条目**（直接跳过）。
"""
import os
import re
from pathlib import Path

ARCHIVE_DIR = "01-记忆档案"
CONF_NAME = "kit.conf"

# 内置默认上限（配置缺省时用；配置存在则覆盖）
DEFAULTS = {
    "L2_MAX_ITEMS": 300,      # L2 条目总数上限
    "L2_MAX_CHARS": 10000,    # 单件体积上限（字符）
    "TTL_DEFAULT_DAYS": 180,  # 未标 ttl 时按此天数判过期（0＝不判）
}


def parse_frontmatter(text: str):
    """返回 (meta: dict, body: str)。meta 值为 str / bool / dict（一层嵌套）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    meta, sub = {}, None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, _, val = raw.strip().partition(":")
        key, val = key.strip(), val.split(" #")[0].strip()
        if indent == 0:
            if val == "":
                sub = {}
                meta[key] = sub
            else:
                sub = None
                meta[key] = _coerce(val)
        elif sub is not None:
            sub[key] = _coerce(val)
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def _coerce(v: str):
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    return v.strip('"').strip("'")


def read_meta(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, "", ""
    meta, body = parse_frontmatter(text)
    return meta, body, text


def load_conf(root: Path):
    """读 <root>/kit.conf（key=value）。返回 (conf, 来源说明)。"""
    conf = dict(DEFAULTS)
    f = root / CONF_NAME
    if not f.is_file():
        return conf, "默认值（未找到 %s）" % CONF_NAME
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        v = v.split("#")[0].strip()
        try:
            conf[k.strip()] = int(v)
        except ValueError:
            conf[k.strip()] = v
    return conf, CONF_NAME


# ── 章节模式（2026-10-25 加 · 治「四闸零对象」，`O-145`）──────────────────────
# 由来（实测）：`iter_l2` 只认 `layer:` frontmatter 的件，而**真实记忆的真源形态是
#   「一个大 md 里若干 `## E823`／`## L1206` 章节」**（宿主侧 `ERRORS.md` 536 条 ＋
#   `LEARNINGS.md` 329 条，**带 layer 字段的件 = 0**）⇒ 四闸看的是 **0 条**，
#   而真实可检查对象 **865 条**。
# 判据取舍：**不复制文件**（复制＝造第二份真源，违「减副本」），改让读取面**认章节**。
# 触发面收窄（防波及）：**只对 `.learnings/` 下的 `ERRORS.md`／`LEARNINGS.md`**，
#   且**仅在没有 frontmatter layer 时**才走章节模式 ⇒ 其他件零影响。
SECTION_FILES = ("ERRORS.md", "LEARNINGS.md")   # 单册原名件（常量名保留，防外部引用断）
# ★ 2026-10-26 加 · `O-145`「分册」：分册件（`ERRORS_02.md`／`LEARNINGS_03.md`）与原名件
#   **同权走章节模式**。理由：分册的目的是「**每册各自不超上限**」，不是「把旧条目藏起来」
#   —— 冷册若不被看见，则既丢检索面（记忆变少），四闸又退回「零对象」（`O-145` 原病）。
SECTION_PREFIXES = ("ERRORS", "LEARNINGS")


def _is_section_file(fn: str) -> bool:
    """`.learnings` 大件的「册」判定（原名件 ＋ 分册件同权；备份/冲突件不算）。

    判据：`<前缀>.md` 或 `<前缀>_<任意>.md`。`ERRORS.md.bak_…` / `ERRORS.md.corrupted_…`
    因不以 `.md` 结尾而天然排除。
    """
    if not fn.lower().endswith(".md"):
        return False
    stem = fn[:-3]
    return any(stem == p or stem.startswith(p + "_") for p in SECTION_PREFIXES)
SNAPSHOT_MARKERS = ("快照", "归档", "_hist")   # 历史副本目录，不计入 L2 条目数
# 编号位数取 \d{2,4}：**早期条目是两位编号**（`L10`–`L99` 共 61 条），
# 首版写 \d{3,4} 把它们整批漏掉（实测 259 → 320）⇒ 口径必须从宽。
SECTION_RE = re.compile(r"^(#{2,4})\s+([EL]\d{2,4})\b(.*)$", re.M)


def split_sections(body: str, rel: str):
    """把大件切成 [(meta, 段正文), ...]；无章节则返回空表。"""
    marks = list(SECTION_RE.finditer(body))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        seg = body[m.start():end]
        sid = m.group(2)
        # `family` 用来分组（去重闸按 family 归族）；`id`／`source` 供指针闸与审计定位
        out.append(({"layer": "L2", "id": sid, "source": "%s#%s" % (rel, sid),
                     "family": "err" if sid[0] == "E" else "learn"}, seg))
    return out


def iter_l2(root: Path):
    """产出 (绝对路径, 相对路径, meta, 正文)。

    **两条来源**：① 带 `layer` frontmatter 的件（原行为，不变）
    ② **`ERRORS.md`／`LEARNINGS.md` 里的 `E#`／`L#` 章节**（2026-10-25 加，见上）。
    """
    base = root / ARCHIVE_DIR
    if not base.is_dir():
        return
    for dp, dns, fns in os.walk(base):
        # ★ 2026-10-25 加：**排除快照/归档目录** —— 那里是历史副本，
        #   计进 L2 条目数会让「四闸对象数」虚高（实测：宿主侧扫到
        #   `记忆工程快照/2026-09-27_周快照/.learnings/` 的旧副本）。
        dns[:] = [d for d in dns if not d.startswith("_") and d != "__pycache__"
                  and not any(k in d for k in SNAPSHOT_MARKERS)]
        for fn in sorted(fns):
            if not fn.lower().endswith(".md"):
                continue
            p = Path(dp) / fn
            meta, body, _txt = read_meta(p)
            rel = p.relative_to(root).as_posix()
            if "layer" in meta:
                yield p, rel, meta, body
                continue
            if _is_section_file(fn):                     # ← 章节模式（原名件 ＋ 分册件）
                for m2, seg in split_sections(body, rel):
                    yield p, rel, m2, seg


def ttl_state(meta: dict, today=None, default_days=None):
    """返回 (状态, 说明)。状态 ∈ permanent / due / expired / unset。"""
    import datetime
    today = today or datetime.date.today()
    raw = str(meta.get("ttl", "")).strip()
    if raw.lower() in ("permanent", "永久", "none", ""):
        return ("permanent", "永久") if raw else ("unset", "未标 ttl")
    m = re.fullmatch(r"(\d+)d", raw)
    if m:
        created = str(meta.get("created", "")).strip()
        if not created:
            return "unset", "标了 Nd 但缺 created ⇒ 无法推算"
        try:
            c = datetime.date.fromisoformat(created)
        except ValueError:
            return "unset", "created 格式非 YYYY-MM-DD"
        expire = c + datetime.timedelta(days=int(m.group(1)))
    else:
        try:
            expire = datetime.date.fromisoformat(raw)
        except ValueError:
            return "unset", "ttl 无法识别：%s" % raw
    if expire < today:
        return "expired", "已于 %s 过期" % expire
    return "due", "将于 %s 到期" % expire

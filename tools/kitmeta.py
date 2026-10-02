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


def iter_l2(root: Path):
    """产出 (绝对路径, 相对路径, meta, 正文)。只认带 layer 字段的件。"""
    base = root / ARCHIVE_DIR
    if not base.is_dir():
        return
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if not d.startswith("_") and d != "__pycache__"]
        for fn in sorted(fns):
            if not fn.lower().endswith(".md"):
                continue
            p = Path(dp) / fn
            meta, body, _txt = read_meta(p)
            if "layer" in meta:
                yield p, p.relative_to(root).as_posix(), meta, body


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

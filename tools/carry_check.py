#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""带走自检（carry check）—— **拔盘前 / 插盘后各跑一次**。

**为什么有它（本机实测 2026-10-02 抓出）**：库「是一个普通文件夹」⇒ 拷走天然成立（实测总指纹逐件一致）；
但 **拷走之后「能不能自证没坏」是另一件事** —— 实测 `verify.py`／`MANIFEST` **全无任何校验和机制**，
且 **`MANIFEST §②` 十条引用有八条在库内不存在**（母体家族路径）⇒ **带走了，却读不通**。
本脚本把这两件事变成**可机检的一行**。

做什么（三件事，全部只读）：
  ① **完整性**：全树逐件 md5 → 一份清单 ＋ 一个总指纹；与基线（`CHECKSUMS.tsv`）比对。
  ② **引用可达性**：`MANIFEST.md` 的「① 本轮必读」「② 按需」两段里引用的路径，逐条判在不在。
  ③ **带走姿态**：库所在盘形 ＋ 根变量能否读到 ＋ 有无`__pycache__`等运行态混入。

用法：
  python tools/carry_check.py --root <库> --write-baseline   # 拔盘前：生成/更新基线
  python tools/carry_check.py --root <库>                     # 插盘后：核对基线
  python tools/carry_check.py --root <库> --json

退出码：0 全部通过 ｜ 1 有差异（缺件/多件/改动/引用走失）｜ 3 参数或IO 错
边界（**如实 · 不假���完备**）：
  · 基线**只覆盖真源面**（默认排除派生物目录与运行态）；派生索引重建后会变，故**不纳入比对**。
  · ★ **本工具逐件比「内容 md5」⇒ 与 size／mtime 无关**
    （**同尺寸改内容照样抓得出** —— 2026-10-02 实测：`MEMORY.md` 2456→2456 字节仍报「内容变」）。
  · **真边界＝基线无签名**：「内容与基线**同被改**（或基线被静默再生成）⇒ 不可判」。
    ⇒ 对外口径＝「**防运输损坏，不防蓄意篡改**」（与「禁写防篡改」自洽）。
  · 首次运行（无基线）⇒ 只报现状，**不判通过**（避免"没基线就说好"的自欺）。
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# 不纳入完整性与基线的目录（派生物 / 运行态 —— 承 MANIFEST §③禁注入）
EXCLUDE_DIRS = {'08-检索索引', '__pycache__', '_run', '.git'}
# 基线文件自身不入基线
BASELINE_NAME = 'CHECKSUMS.tsv'


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def scan(root: Path):
    """全树扫描 → [(rel, size, md5)]（已排序），排除派生物与运行态。"""
    out = []
    for r, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in fs:
            if f == BASELINE_NAME or '.bak_' in f:
                continue
            p = Path(r) / f
            out.append((p.relative_to(root).as_posix(), p.stat().st_size, md5(p)))
    out.sort()
    return out


def fingerprint(items) -> str:
    h = hashlib.md5()
    for rel, _sz, m in items:
        h.update((rel + ':' + m).encode('utf-8'))
    return h.hexdigest()


def parse_manifest_refs(root: Path):
    """取 MANIFEST 的「① 本轮必读」「② 按需」两段里反引号引用的库内路径。"""
    man = root / 'MANIFEST.md'
    if not man.is_file():
        return []
    txt = man.read_text(encoding='utf-8', errors='replace')
    seg = txt
    for a, b in (('## ① 本轮必读', '## ②'), ('## ②', '## ③')):
        pass# 分段由下方统一处理
    out = []
    for marker, endm in (('## ① 本轮必读', '## ②'), ('## ②', '## ③')):
        if marker in txt:
            seg = txt.split(marker, 1)[1].split(endm, 1)[0]
            import re
            for m in re.finditer(r'`([^`]+)`', seg):
                s = m.group(1).strip()
                if s.startswith(('00-', '01-', '02-', '03-', '04-', '05-', '06-', '07-',
                                '08-', '09-', '10-', '11-', '12-', '13-')) or '/' in s:
                    out.append(s)
    # 去重保序
    seen, res = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            res.append(s)
    return res


HOSTSIDE_TAG = "〔宿主侧·族路径〕"


def check_refs(root: Path, refs, seg_raw_for=lambda r: ""):
    """可达性判定（三态）。

    ★ **先自辨本根是「库根」还是「套件根」**（承 `MANIFEST ⓪` 的唯一判据＝同目录有无 `01-记忆档案/`）——
      两种根的 `MANIFEST` 是**同一份**，但「引用走失」的含义完全不同：
        · **库根**：引用的是**记忆**，走失＝记忆真缺 ⇒ 报出来；
        · **套件根**：`01-记忆档案/` 由 `kernel-skeleton/` 提供（在 `kernel-skeleton/` 下，不在根）
          ⇒ 「走失」是**正常的**（那是出厂骨架，不是根的件）⇒ **不报**，只报 F 层自身在不在。
    （**这正是 `install/verify.py` 第②项在库根必 FAIL 的同一个病** —— 判据不辨根。）
    """
    is_lib = (root / '01-记忆档案').is_dir()
    ok, miss, skipped, declared = [], [], [], []
    for rel in refs:
        # 归一化：MANIFEST 里写 `<当日>` / `xxx/<uuid>` 之类占位的一律跳过（非具体路径）
        if any(c in rel for c in '<>*…'):
            skipped.append(rel)
            continue
        if (root / rel).exists():
            ok.append(rel)
        elif seg_raw_for(rel):
            # 已声明在宿主侧（§② 标了〔宿主侧·族路径〕）⇒ **不算走失**
            declared.append(rel)
        elif not is_lib:
            # 套件根：记忆面在 kernel-skeleton/ 下，属正常
            if rel.startswith('01-记忆档案'):
                skipped.append(rel)
            else:
                miss.append(rel)
        else:
            miss.append(rel)
    return ok, miss, skipped, declared


def root_kind(root: Path) -> str:
    """承 `MANIFEST ⓪`：同目录有 `01-记忆档案/` ＝ 库根；否则 ＝ 套件根。"""
    return '库根' if (root / '01-记忆档案').is_dir() else '套件根'



def drive_raw(root: Path) -> str:
    """盘形原始判据（只读，不猜）。Windows 用 DriveType；类 Unix 回落挂载表启发。"""
    if os.name == 'nt':
        try:
            import ctypes
            drive = str(root.resolve())[:3].upper()          # 如 'E:\\'
            TYPES = {0: '未知', 1: '不存在的盘', 2: '可移动盘(外置/软盘)', 3: '本地固定盘',
                     4: '网络盘(映射)', 5: '光驱', 6: 'RAM 盘'}
            dt = ctypes.windll.kernel32.GetDriveTypeW(drive + '\\')
            return TYPES.get(dt, 'DriveType=%s' % dt)
        except Exception as e:
            return '未判（%s）' % e
    # 类 Unix：从 mount 表找最长前缀
    try:
        best, kind = '', '本地盘'
        with open('/proc/mounts', encoding='utf-8', errors='replace') as f:
            for ln in f:
                p = ln.split()
                if len(p) >= 3:
                    mp = p[1].replace('\\040', ' ')
                    if str(root).startswith(mp) and len(mp) > len(best):
                        best, kind = mp, p[2]
        return {'nfs': '网络盘(NFS)', 'cifs': '网络盘(SMB)', 'fuseblk': '外置盘(FUSE)'}.get(kind, kind)
    except Exception:
        return '未判（非 Windows 且 /proc/mounts 不可读）'


def drive_kind(root: Path) -> str:
    """盘形归类（给判读用）—— **「能带走吗」的实面。**"""
    r = drive_raw(root)
    if '可移动' in r or '外置' in r or 'FUSE' in r or '光驱' in r:
        return r + '  → ★ **能带走**'
    if '网络' in r or 'NFS' in r or 'SMB' in r:
        return r + '  → ⚠️ **换环境即断**（云端还在，插到别的机未必自动接上）'
    if '本地固定' in r:
        return r + '  → 随机器走（换机须另拷）'
    return r

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, help='库根目录')
    ap.add_argument('--write-baseline', action='store_true', help='生成/更新基线（拔盘前）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    if not root.is_dir():
        print('[FAIL] 库根不存在：%s' % root)
        return 3

    items = scan(root)
    fp = fingerprint(items)
    total = sum(sz for _r, sz, _m in items)
    kind = root_kind(root)
    refs = parse_manifest_refs(root)
    raw = (root / "MANIFEST.md").read_text(encoding="utf-8", errors="replace") \
        if (root / "MANIFEST.md").is_file() else ""

    def _in_tagged_segment(rel):
        """该引用所在的 MANIFEST 行里，是否带了〔宿主侧·族路径〕标注。"""
        for ln in raw.splitlines():
            if rel in ln and HOSTSIDE_TAG in ln:
                return True
        return False

    ok_refs, miss_refs, skip_refs, decl_refs = check_refs(root, refs, _in_tagged_segment)

    baseline = root / BASELINE_NAME
    have_base = baseline.is_file()
    base_map = {}
    if have_base:
        for ln in baseline.read_text(encoding='utf-8', errors='replace').splitlines():
            if '\t' in ln and not ln.startswith('#'):
                rel, _sz, m = ln.split('\t', 2)
                base_map[rel] = m

    diffs = {'missing': [], 'extra': [], 'changed': []}
    cur_map = {rel: m for rel, _sz, m in items}
    if have_base:
        for rel, m in base_map.items():
            if rel not in cur_map:
                diffs['missing'].append(rel)
            elif cur_map[rel] != m:
                diffs['changed'].append(rel)
        for rel in cur_map:
            if rel not in base_map:
                diffs['extra'].append(rel)

    result = {
        'root': str(root),
        'files': len(items),
        'bytes': total,
        'fingerprint': fp,
        'has_baseline': have_base,
        'refs_total': len(ok_refs) + len(miss_refs),
        'refs_ok': len(ok_refs),
        'refs_missing': miss_refs,
        'refs_skipped': len(skip_refs),
        'refs_declared_hostside': len(decl_refs),
        'root_kind': kind,
        'diffs': diffs,
        'env': {
            'drive_kind': drive_kind(root),
            'drive_raw': drive_raw(root),
            'MEMORY_KIT_DATA': os.environ.get('MEMORY_KIT_DATA') or None,
            'MEMORY_KIT_LIB': os.environ.get('MEMORY_KIT_LIB') or None,
            'cwd': os.getcwd(),
        },
    }

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print('== 带走自检 ｜ %s：%s' % (kind, root))
    if kind == '套件根':
        print('-- （本根按  判为**套件根** ⇒ 记忆面在  下，'
              '**引用走失属正常**；本工具的用法场景是**库根**）')
    print('-- ① 完整性：真源面 %d 件 / %d 字节 ｜ 总指纹 %s' % (len(items), total, fp[:16]))
    if a.write_baseline:
        import datetime
        _now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        _host = os.environ.get('MEMORY_KIT_HOST_ID') or 'h_未标注'
        lines = ['# CHECKSUMS —— 真源面逐件 md5 基线（拔盘前生成）',
                 '# 覆盖范围：全树除派生物目录与运行态（%s）' % '/'.join(sorted(EXCLUDE_DIRS)),
                 '# 用途：插盘后 `carry_check.py` 比对⇒  记忆有没有在运输中少/多/变',
                 '# 重新生成会覆盖本行之后全部内容 —— **改记忆后请重跑 --write-baseline**',
                 '# ★ 生成时刻（UTC）：%s ｜ 生成者 host 代号：%s ｜ 场景：拔盘前基线' % (_now, _host),
                 '#   ↑ 这行是**多份带走判真的前提**：两份基线比「时戳 ＋ 指纹」，分歧交主人裁决（不自动合并）',
                 '# rel\tsize\tmd5']
        lines += ['%s\t%d\t%s' % (rel, sz, m) for rel, sz, m in items]
        baseline.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        print('-- 已写基线：%s（%d 行）' % (baseline, len(items)))
    elif not have_base:
        print('-- ⚠️ 无基线（%s 不存在）⇒ **只报现状，不判通过**' % BASELINE_NAME)
        print('   → 拔盘前请先跑一次：python tools/carry_check.py --root . --write-baseline')
    else:
        n = sum(len(v) for v in diffs.values())
        if n == 0:
            print('-- 与基线比对：**逐件一致 ✅**（无少件/ 无多件 / 无改动）')
        else:
            print('-- 与基线比对：**%d 处差异 ❌**' % n)
            for k, label in (('missing', '少件'), ('extra', '多件'), ('changed', '内容变')):
                for rel in diffs[k]:
                    print('     [%s] %s' % (label, rel))

    print('-- ② 引用可达性：MANIFEST ①/② 段引用 %d 条｜可达 %d｜已声明宿主侧 %d｜真走失 %d'
          % (result['refs_total'], result['refs_ok'], len(decl_refs), len(miss_refs)))
    for r in decl_refs:
        print('     ⚠ 已声明（宿主侧·族路径 · 本库没有）: %s' % r)
    for r in miss_refs:
        print('     ❌ 走失：%s' % r)
    if miss_refs:
        print('     ⇒ 走失＝**读者按规程办事会撞空**（母体家族路径多在宿主侧；'
              '如实说「本库没有」，禁为凑齐而复制）')

    print('-- ③ 带走姿态：盘形=%s ｜ 根变量 MEMORY_KIT_DATA=%s ｜ MEMORY_KIT_LIB=%s'
          % (result['env']['drive_kind'],
             result['env']['MEMORY_KIT_DATA'] or '（未设 · 走载体优先降级）',
             result['env']['MEMORY_KIT_LIB'] or '（未设）'))
    print('      ⇒ 盘形判读：**能带走**＝外置/移动盘；**换环境即断**＝网络盘；'
          '本地盘随机器走（备份另算）')

    bad = bool(miss_refs) or (have_base and any(diffs.values())) or (not have_base and not a.write_baseline)
    print('== 结论：%s' % ('⚠️ 有待处理项（见上）' if bad else '✅ 可带走 / 已完整接上'))
    return 1 if bad else 0


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

if __name__ == '__main__':
    sys.exit(main())

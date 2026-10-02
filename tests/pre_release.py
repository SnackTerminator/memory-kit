#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发行前闸 —— 打包前必跑：一条命令跑齐全部出厂判据。

为什么需要它（承 DSH 15:4x 否定性裁决 Q3）：
  "零私人内容"若只扫一次，**扫完之后新增的文件**就会漏出去。
  ⇒ 对策：把全部判据收成**一个发行前必跑闸**；每次打包前全量跑一次，
    任何"上次之后新增"的文件都会当场暴露（白名单判据是全量的）。

跑的判据：
  ① 白名单（G3①）  ② 内容黑名单（G3②，须传私有参照，否则报"审查不完整"）
  ③ N0 新生儿态（G3③）

用法：
  python tests/pre_release.py --root <包根> \
      --keywords <词表件> --private-ref <私有件目录>
  python tests/pre_release.py --root <包根> --allow-incomplete   # 仅调试用

退出码：0 全通过 ｜ 1 有任何红或审查不完整 ｜ 3 参数/IO 错误
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(args, label):
    cp = subprocess.run([sys.executable, "-B"] + args, capture_output=True,
                        text=True, encoding="utf-8", errors="replace")
    print(f"\n######## {label}（rc={cp.returncode}）")
    print((cp.stdout or "").rstrip())
    if cp.stderr:
        print("[stderr]", cp.stderr.rstrip())
    return cp.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--keywords", default=None)
    ap.add_argument("--private-ref", default=None)
    ap.add_argument("--allow-incomplete", action="store_true")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve() if a.root else HERE.parent
    if not root.is_dir():
        print(f"[FAIL] 包根不存在：{root}")
        return 3

    print(f"==== 发行前闸 ｜ 包根：{root}")
    results = []

    rc1 = run([str(HERE / "zero_private_scan.py"), "--root", str(root), "--whitelist"],
              "判据① 白名单")
    results.append(("①白名单", rc1))

    if a.keywords or a.private_ref:
        cmd = [str(HERE / "zero_private_scan.py"), "--root", str(root), "--content"]
        if a.keywords:
            cmd += ["--keywords", a.keywords]
        if a.private_ref:
            cmd += ["--private-ref", a.private_ref]
        rc2 = run(cmd, "判据② 内容黑名单")
        # 内容扫描：rc==2 才是命中；本闸把"跳过"另判
        results.append(("②内容", rc2))
    else:
        print("\n######## 判据② 内容黑名单：【未执行】")
        print("  未提供 --keywords / --private-ref ⇒ 本次发行审查【不完整】")
        rc2 = 0 if a.allow_incomplete else 1
        results.append(("②内容(未执行)", rc2))

    rc3 = run([str(HERE / "n0_bootstrap_check.py"), "--root", str(root)], "判据③ N0 新生儿态")
    results.append(("③N0", rc3))

    rc4 = run([str(HERE / "gates_selftest.py"), "--quiet"], "判据④ 四闸自检（F25）")
    results.append(("④四闸", rc4))

    # ★ 判据⑤（2026-10-01 批 1「上锁」加）：状态一致性（F 类）—— VERSION／CHANGELOG／README／
    #   发行物清单 四面一致、发行包指纹、禁物、白名单路径存在、强断言须带指向件。
    #   存在理由＝批 0 三处矛盾长期无人发现 ⇒ 人眼回扫不可作验收基准（项目审查 P0-3）。
    rc5 = run([str(HERE / "state_consistency.py"), "--root", str(root)], "判据⑤ 状态一致性（F 类）")
    results.append(("⑤一致性", rc5))

    print("\n==== 汇总")
    bad = 0
    for name, rc in results:
        flag = "OK" if rc == 0 else "RED"
        if rc != 0:
            bad += 1
        print(f"  [{flag}] {name}  (rc={rc})")
    print(f"==== 结果：{'通过，可打包' if bad == 0 else '未通过 ⇒ 禁止打包'}（红 {bad} 项）")
    return 0 if bad == 0 else 1


# ★ 输出编码治本（2026-09-29 DSH 第三方盲复现抓出）：中文 Windows 控制台默认 GBK，
#   输出含非 GBK 字符（如 ⇒）会 UnicodeEncodeError 崩溃。此处**显式重配置为 UTF-8**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())

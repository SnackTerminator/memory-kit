# 故障排查（TROUBLESHOOTING）

> **先做这三步**（90% 的问题自己会说话）：
> 1. `python tests/gates_selftest.py --quiet` —— 四闸自检
> 2. `python install/verify.py --root <你的库>` —— 新生儿态自检
> 3. 把**完整报错原文**复制下来（**别只截图、别只描述**）

---

## 一、常见症状 → 处置

| 症状 | 可能原因 | 处置 |
|---|---|---|
| `ModuleNotFoundError` | 你用了**系统 Python** 而脚本依赖某包 | 本套件**只用标准库** ⇒ 若仍报此错，多半是你自己加了东西；用 `python -c "import sys;print(sys.executable)"` 确认解释器 |
| 装完**必读件缺失** | 骨架被裁剪过 | 重跑 `install/init_instance.py --target <库> --force`；它会**生成占位并报出**缺哪些 |
| 助手**读不到**入口件 | 路径给错，或给的是**相对路径** | 给它**绝对路径**的 `AGENTS.md` |
| 助手读到了但**不问要点** | 它没按 `MANIFEST.md` 的读序走 | 明确要求：「按 `MANIFEST.md` ① 段**按序**读」 |
| 助手**编造**不存在的记忆 | 它没遵守 N0「不装懂」 | 明确纠正：「**没有就说没有**，不要补」 |
| 改了 `.md` 但助手读到**旧内容** | 宿主缓存 | 让宿主**重新读文件**；本套件**真源就是文件**，不存在服务端缓存 |
| 四闸报 `触顶`（`exit 3`） | L2 条目或单件体积超上限 | **不要扩上限** ⇒ 按提示**降冷或合并**；确需调高请**显式改 `kit.conf`** |
| 指针闸报 `exit 4` | 有 `deprecated: true` 但缺 `superseded_by` | 补指针（**蒸馏须可回溯**） |
| `selftest 有红` | 环境异常或文件被改 | 抄下**红的那一态**再报（见 `SUPPORT.md`） |

---

## 二、★ Windows 专章

> 本套件在 Windows 上**可用**，但有几处平台特性会咬人 —— 以下均为**实测踩过的坑**。

### 2.1 路径格式：**别把 Git Bash 路径直传给 Windows Python**

```bash
# 会失败（MSYS 风格 /c/... 传给 Windows 解释器）
python /c/Users/you/my-memory/install/init_instance.py --target /c/Users/you/mem

# 正确：先 cd，再用相对路径；或直接用 Windows 风格路径
cd /c/Users/you/my-memory
python install/init_instance.py --target "C:/Users/you/mem"
```

**判据**：脚本报"找不到文件/目录"，而你在资源管理器里**明明看得到** ⇒ 八成是这个。

### 2.2 中文路径

**可支持**（本套件实测含中文的路径可用），但注意：

- 传参时**加引号**：`--target "D:/我的记忆"`
- 若出现**乱码文件名**，是终端编码问题 ⇒ 设 `chcp 65001`（或改用 PowerShell / Windows Terminal）

### 2.3 控制台编码

Python 3.6+ 在 Windows 控制台默认可能用 GBK ⇒ 中文输出乱码。

```powershell
$env:PYTHONUTF8 = "1"     # 推荐：一次性让输出走 UTF-8
python install/init_instance.py --target "D:/mem"
```

### 2.4 行尾（CRLF ↔ LF）

- 本套件的**出厂文件统一 LF**；
- 你的编辑器若自动转 CRLF，**不影响使用**，但会让 `git diff` 出现整文件变更；
- **建议**：编辑器里对该目录关掉自动转换，或在 `.gitattributes` 里声明。

### 2.5 目录联接／符号链接

**不推荐**把记忆库目录做成 junction/symlink：

- 备份工具**大多不跟随链接**（备份会漏）；
- 删除时 `rm -rf` 有可能**跟随链接删掉真实内容**（危险）。

**要移动库** ⇒ 直接移动真实目录，别用链接。

### 2.6 权限与只读目录

若把库放在 `C:\Program Files\` 一类受保护目录，写入会失败。**放到你的用户目录**（`C:\Users\<你>\`）或数据盘。

---

## 三、仍然不通？

按 `SUPPORT.md` 的**反馈四件套**提交（缺一难查）：
1. 你敲的**完整命令**
2. **完整报错原文**
3. `python --version` 与操作系统
4. 自检输出（`gates_selftest --quiet` / `n0_bootstrap_check`）

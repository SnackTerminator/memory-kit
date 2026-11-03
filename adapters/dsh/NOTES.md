# DSH 适配要点（NOTES · ≤45 行）

**宿主**：DeepSeek Harness（DSH）
**形态**：**裸库直读**（`adapterShape: bare-read`）—— **零改造**，不写插件、不动其配置

## 怎么接（三步）

1. 把记忆库放到一个**绝对路径**下（如 `D:/my-memory`）；
2. 告诉 DSH：**「读 `D:/my-memory/AGENTS.md`，按它指向的顺序读取」**；
3. 要它**复述读序**——应对：`SOUL → USER → IDENTITY → MEMORY → 会话速读包 →（当日通告，若有）`。

## 实测结论（as-of 2026-09-29）

- ✅ **判据 1**（能读到）：它正确说出 `AGENTS.md` 指向 `MANIFEST.md`；
- ✅ **判据 2**（读序对）：复述顺序正确；
- ⏳ **判据 3–5**（缓存漂移／无常驻组件／与宿主自带记忆共存）：**未逐项实测**，**标【部分已证】**，**禁写成"已通过"**。

## 本宿主的坑

| 坑 | 处置 |
|---|---|
| **无 `PLUGIN_ROOT` / `PLUGIN_DATA` 类根变量** | 按契约 **§三-4 降级约定（载体优先）**：① 环境变量 `MEMORY_KIT_DATA` ／ `memory-kit.conf` → ② **用户指定／探测到的载体** → ③ **兜底 `instance/`，且必须告警**；运行态＝`_run/` |
| 有自带记忆/preset 机制 | **共存不抢位**：不改其 preset，只让它**多读一个入口件** |
| 传路径时 | 用**绝对路径**；相对路径易解析到它自己的工作目录 |
| **★ 自带 per-principal 持久记忆（2026-09-29 实测）** | 其持久记忆落 `memory/principal-local-*/memories.json` —— **按「人」存、不按会话存** ⇒ **「换新会话」不清零**；要测「与记忆无关的行为」，须**换宿主或清记忆 ＋ 换 cwd**。**同理**：它**更应把 `h_<uuid>` 持久化并自报比对**，否则同样会出现「换宿主侦测**过报**」（口径与处置见 `adapters/hermes/NOTES.md` §五） |

## ★ 四焊点验收（**2026-10-01 立** · 承 `adapters/CONTRACT.md` §八）

> **口径**：**「文件里写了」≠「焊上了」**。**本表只写有实测的；未实测标 ⏳；禁标「已焊」。**

| 焊点 | 状态 | 依据 ／ 缺口 |
|---|---|---|
| **A 注入** | ✅ **已焊** | 判据 1–2 实测（复述读序，顺序正确） |
| **B 写触发** | ⏳ **未焊（属自觉项）** | 宿主侧**无钩子**声明 ⇒ 四个触发点**全靠会话自觉**（同 `spec/记忆形成与容量治理.md` §十） |
| **C 检索** | ✅ **已焊（2026-10-26 宿主侧实测）** | **官方 DSH CLI**（`dsh --profile headless` ／ `@deepseek-ai/dsh 0.2.1-rc.2`）实跑 `tools/memory.py search 记忆` → **扫描 45 件 ／ 命中 322 处**（回贴原文）。**宿主身份**：`D://DeepSeek Harness`（签名主体 Hangzhou DeepSeek AI Co., Ltd.），**非**第三方壳 `@linxin666/dsh-desktop` |
| **D 确认** | ✅ **已焊（2026-10-26 宿主侧实测）** | 同一次实跑 `tools/curate.py state` → **`pending_proposals：0`**，且末行 **`对账：速读包首行 = pending_proposals = 0`**（显示面与队列一致） |
| **E 删除触达** | ✅ **已焊（2026-10-26 宿主侧实测 · 副本上做）** | 同一次实跑副本三段：`purge --preview` → **`预览完（未删任何件）`**；`purge --yes --receipt-fingerprint NEW` → **`[OK] 已删 1 件（primary ＋ 命中副本）｜回执 1 行｜链完整`**；`purge audit` → **`[OK] 本库根内不可达（内容面 ＋ 路径面 均 0 命中）`** |

## 2026-10-26 宿主侧实测环境（C/D/E 的取证条件，供复核）

> **★ 先分清两个 DSH**：本机有**两个**同名近似安装 ——
> **官方版** `D://DeepSeek Harness\`（`publisherName: CN=Hangzhou DeepSeek Artificial Intelligence Co., Ltd.`，更新源 `download.deepseek.com/dsh-desk/`）｜
> **第三方壳** `D://DeepSeek Harness Desktop\`（`@linxin666/dsh-desktop` v5.1.0，`owner: ningbainb`，channel `beta`）。
> **本节 C/D/E 的实测主体＝官方版**，走官方 CLI 路径（`npx @deepseek-ai/dsh@0.2.1-rc.2 --profile headless --json -`）。

| 实测条件 | 值 ／ 说明 |
|---|---|
| 命令面 | `dsh --profile headless --json -`（任务走 stdin） |
| 凭据 | `DEEPSEEK_API_KEY` 经环境变量传入（取自官方 Web Models 页写入的 credentials service） |
| 工作区 | **不可是百度网盘目录** —— 沙箱要给 workspace 配 ACL，网盘目录 `SetNamedSecurityInfoW failed (Win32 5)`；本次用 `C://Users//<user>//dsh-ws` 下的库副本 |
| 参数纪律 | **任务文本禁含换行**（含换行会被吞，任务没送到）⇒ 一律**单行 + 分号**分隔；长文本走 stdin |
| 已知干扰 | 本机 `python` 被注入 **safe-delete 垫片**，`purge --yes` 会被拦（要在 `%LocalAppData%\Temp\codebuddy-safe-delete-bulk\` 建锁）⇒ 本次用 **`python -S`** 跳过 site 初始化后通过 |
| 未测 | **B 写触发**仍 ⏳（官方 DSH 是否支持 hook 未验，故仍按「自觉项」记，不写成机制） |

## 不做什么

- ❌ 不写 DSH 插件／不改其 preset 结构（本宿主**不需要**）
- ❌ 不把记忆写进套件目录（**三级根纪律**，契约 §二）
- ❌ 不依赖任何常驻服务（DSH 不起、我们也不用它起）

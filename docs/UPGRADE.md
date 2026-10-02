# 升级（UPGRADE）

> **一句话**：**升级只动 F 层（框架），你的 I 层（记忆）不动** —— 且**升级前先备份**。
>
> **平台约定**：本文命令用 bash 写法；**命令里的 `~/my-memory` 一律换成你自己的绝对路径**（PowerShell 不展开 `~` · git-bash 会换成 POSIX 路径 ⇒ 详见 `QUICKSTART.md` 文首「约定②」）；PowerShell 下 `cp -r`／`mv` 等价于 `Copy-Item -Recurse`／`Move-Item`。

---

## 一、升级前（**必做**）

```bash
# 1) 备份你的库（整个目录拷贝一份即可）
cp -r ~/my-memory ~/my-memory.backup-$(date +%Y%m%d)

# 2) 记录当前版本
cat <memory-kit>/VERSION
```

> **为什么必须先备份**：升级**理论上不动 I 层**，但"理论"不等于"你的磁盘"。

---

## 二、升级（三步）

```bash
# 1) 取新版套件（clone / 解压 / 复制，同 QUICKSTART）
# 2) 读 CHANGELOG.md —— 看这一版动了什么、有没有"需要你做的事"
# 3) 用新版覆盖 F 层文件（AGENTS.md / MANIFEST.md / spec/ / tools/ / install/ / tests/ / docs/）
#     ★ 不要覆盖你的 I 层（01-记忆档案/ 下的内容）
```

**判据（升级成功的验证器）**：

```bash
python tests/gates_selftest.py --quiet         # 四闸自检应全绿
python install/verify.py --root <你的库>   # 应仍通过
```

> 你的**记忆文件一个都不应被改动** —— 用备份对比即可确认（文件数、体积、内容）。

---

## 三、版本与兼容

| 记号 | 含义 |
|---|---|
| `memory-kit X.Y.Z` | **套件版本**（F 层）—— 升级关注它 |
| `skeleton-schema: memory-root/N` | **骨架规范版本** —— 决定**元数据字段**与**读序** |

**兼容判据（记住这一条就够）**：

> **`skeleton-schema` 大版本不变 ⇒ 你的 I 层不用动。**

若新版把 `skeleton-schema` 升了大版本 ⇒ `CHANGELOG` 里会给出**迁移说明**（怎么把旧 I 层改到新规范）。

### 三·附 ★ 库实例身份放哪（**为什么不在 `MANIFEST.md` 里**）

`MANIFEST.md` 属**可被新版整体覆盖的 F 层文件**（见本文 §二）⇒ **任何"实例身份"写在那里，升级即静默丢失**（认不出"这还是同一个库" ⇒ 换机／换宿主的侦测退化为"从不触发"）。

> ⇒ **本套件把实例身份单独落一件**：**`01-记忆档案/carrier.yaml`**（**I 层** —— 本文 §二 明写"不要覆盖你的 `01-记忆档案/`"）⇒ **结构上丢不了**。
> `MANIFEST.md` 的 frontmatter 只留**一行指针**：`carrier: 01-记忆档案/carrier.yaml`。

**迁移（`memory-root/1 → /2`）—— 老库补 `carrier.yaml`**：

在库里新建 `01-记忆档案/carrier.yaml`：

```yaml
instance_id: <生成一个 UUID>       # 只需生成一次，此后永不变
label: <例：我的记忆>
created: <原库建立日期 YYYY-MM-DD>
last_host:
  host_id: h_<uuid>               # ★ 只写不透明代号，禁写宿主真名（见 MANIFEST §⑤ 不变量 2）
  machine_id: m_<uuid>
last_seen: <当前 UTC 时刻>
trust: [h_<当前宿主代号>]
principal:                          # ★ 新增（人轴）：换机/换盘/换宿主都不变
  principal_id: p_<uuid>            # 只写不透明代号，禁写人名
  label: <例：本人的记忆>
```

> 缺此件的旧库**不会坏** —— 只是**认不出换机／换宿主**；补上即恢复。
> **此后只更新 `last_host` / `last_seen` / `trust`**；`instance_id` **永不变**（它是"这个库是谁"的锚）。

---

## 四、冲突处理（**只报不改**）

升级时如果发现：

- 你**改过** F 层的某个文件（例如手改了 `MANIFEST.md`）⇒ 新版覆盖会**丢掉你的改动**；
- **正确做法**：
  1. **别直接覆盖** —— 先 diff 看差在哪；
  2. 判断你的改动属**可定制面**（→ 搬进 `kit.conf`）还是**内核不变量**（→ 提"议题"）；
  3. 确实要保留的，**手工合并**并记一句理由。

> **设计立场**：**升级冲突只报不改** —— 任何"自动帮你合并"的行为都可能在你看不见的地方改掉你的记忆规则。

---

## 五、回滚

```bash
# 直接把备份换回来
mv ~/my-memory ~/my-memory.failed
cp -r ~/my-memory.backup-YYYYMMDD ~/my-memory
```

**回滚是最安全的操作** —— 记忆是文件，**文件能拷回来**。

---

## 六、什么时候**不要**升级

| 情况 | 建议 |
|---|---|
| 你正在用旧版**做重要的事** | 等做完再升 |
| `CHANGELOG` 里有你**看不懂的迁移项** | 先看 `docs/` 对应章节，或提"议题"问清楚 |
| 你没有备份 | **先备份**，其他免谈 |

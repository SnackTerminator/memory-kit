# 示例实例（EXAMPLES）

> **目的**：让你**不配置任何东西**，先看一眼"**记忆长什么样**"。
> **本目录**：`demo-instance/` ＝ 一个**脱敏的迷你记忆库**（内容**纯虚构**，与任何人无关）。

---

## 一、零配置跑一次

```bash
# 看它有哪些记忆条目
python tools/memory.py --root examples/demo-instance list

# 检索一条
python tools/memory.py --root examples/demo-instance search 蒸馏

# 取出一件的原文
python tools/memory.py --root examples/demo-instance get "01-记忆档案/示例-长期记忆.md"

# 看索引是怎么长出来的（只写派生物）
python tools/memory.py --root examples/demo-instance reindex --dry-run
```

**判据**：上面四条**不需要任何配置、不需要密钥、不需要联网**就该跑通。

---

## 二、这个示例演示了什么

| 演示点 | 在哪看 |
|---|---|
| **记忆 ≠ 记录**：条目头部带**元数据**（层级／族／寿命／准入三问） | `demo-instance/01-记忆档案/*.md` 的 frontmatter |
| **四闸**怎么判：入口闸读 `admit` 三问、合并闸按 `family` 分组、寿命闸看 `ttl` | 同上 ＋ 跑 `python tools/l2_admit.py --root examples/demo-instance` |
| **速读包**＝"当前在做什么" | `demo-instance/01-记忆档案/记忆工程/会话速读包.md` |

> **示例实例只有"记忆内容"**，没有 `AGENTS.md`／`MANIFEST.md`（那两件在包根，全库共用一套）。

---

## 三、它**不是**什么

- ❌ 不是"最佳实践的权威样本" —— 只是**格式演示**；
- ❌ 不含任何真实人物／组织信息（`spec/零私人内容判据.md` 同样适用于本目录）；
- ❌ 不要拿它当你的库使用 —— 你的库请用 `install/init_instance.py` 生成。

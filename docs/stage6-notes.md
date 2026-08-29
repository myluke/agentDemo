# 阶段 6 · 检索增强生成（RAG）— 回顾笔记

配套代码：[`rag_basic.py`](../rag_basic.py)

---

## 一句话机制

**RAG = 先从外部资料里检索相关片段，再把片段和问题一起交给模型。**

模型参数没有被训练或修改；每次回答前，只是动态给提示词补了一份“小抄”。

## 五步流水线

```text
原始资料 → 切成 chunks → embedding 向量 → vector store 检索 → context + question → Claude
```

| 步骤 | demo 中的实现 | 作用 |
|---|---|---|
| 加载 | 一个字符串 `DOC` | 获取原始知识；生产可换 PDF、网页、数据库 |
| 切分 | `RecursiveCharacterTextSplitter` | 把长文拆成可单独召回的小块 |
| 向量化 | `LocalEmbeddings` | 把文块和问题映射为同维向量 |
| 存储 / 检索 | `InMemoryVectorStore` + retriever | 按余弦相似度取最相关的 k 块 |
| 生成 | prompt → Claude → parser | 只依据取回的 context 回答 |

## 为什么不能直接把整篇文档塞给模型

小文档当然可以，RAG 在那种情况下没有必要。文档多或长时才显出价值：

- 整库可能超过上下文窗口；
- 每次重发全部资料浪费 token 和延迟；
- 无关内容越多，真正答案越不突出；
- 检索能按用户权限、来源、时间等元数据先过滤。

所以先切分，再只拿相关片段。`chunk_size` 太小会割裂语义，太大则召回不精准；
`chunk_overlap` 给切口两侧留一点重复，避免答案刚好被劈开。

## embedding 和 vector store 各做什么

embedding 把文本变成一串数字；语义越近，向量通常越近。vector store 保存文块及其
向量，查询时把问题也转成向量，再找最近邻。

本 demo 的 `LocalEmbeddings` 只是字符 bigram 哈希词袋，只懂字面重叠，不懂真正语义：
“会员到期”能命中“会员到期”，但“喵星人”未必能命中“猫”。之所以用它，是因为当前
网关没有 embedding 端点；它实现了 LangChain 的标准 `Embeddings` 接口，所以以后只需
替换这一处：

```python
store = InMemoryVectorStore.from_documents(chunks, RealEmbeddings())
```

后面的 retriever 和 LCEL 链完全不动。

## `/v1/embeddings` 到底是什么

它是**把文本转成一串数字（向量）的 API 端点**——OpenAI 定的事实标准路径，绝大多数
网关都照抄。上表「向量化」那一步，正常情况下就是调它。

```bash
POST /v1/embeddings
{"model": "text-embedding-3-small", "input": "我家的猫"}
```

返回一个定长浮点数组（这里是 1536 维）：

```json
{"data": [{"embedding": [0.021, -0.043, 0.118, ...]}]}
```

这串数字是这句话在「语义空间」里的坐标：**意思越接近，坐标越接近。**

```text
"我家的猫"     → [ 0.02, -0.04, 0.11, ...]
"我养的喵星人"  → [ 0.03, -0.04, 0.10, ...]   ← 距离近（说的是一回事）
"今天股市大跌"  → [-0.31,  0.77, 0.05, ...]   ← 距离远
```

关键在于：「猫」和「喵星人」一个字都不重叠，但向量是近的。**关键词搜索做不到这件事，
embedding 能**——这就是 RAG 不用 `LIKE '%猫%'` 而用向量库的原因。

一次 RAG 里它被调用两次，用的是同一个模型（必须同一个，否则两组向量不在同一空间，
算出来的距离没有意义）：

| 时机 | 调用 | 对应代码 |
|---|---|---|
| 建库时 | 每个文块转一次向量，连同原文存进 vector store | `InMemoryVectorStore.from_documents(chunks, ...)` |
| 提问时 | 问题转一次向量，拿去找最近邻 | `retriever.invoke(question)` |

### 本仓库为什么用本地实现

当前网关的 `/v1/embeddings` 返回 404——这不是配置漏了：**Anthropic 本身不提供
embedding 服务**（官方推荐搭配 Voyage AI），所以走 Anthropic 协议的网关没有这个端点
是正常的。因此 demo 里用 `LocalEmbeddings` 顶上，按**字面重叠**算相似度。

差别很实际：

| 提问 | 真 embedding | 本 demo 的 `LocalEmbeddings` |
|---|---|---|
| 「会员到期后数据保留多久」 | ✅ 命中 | ✅ 命中（字面重合多） |
| 「账号注销后资料还在吗」 | ✅ 命中（懂语义） | ❌ 漏掉（一个字不重叠） |

demo 里的问题字面重合度高，所以跑得通；换个说法就会露馅。这正是它只能教学、
生产必换的原因。

### 换成真 embedding 时选什么

| 模型 | 维度 | 备注 |
|---|---|---|
| `text-embedding-3-small` | 1536 | OpenAI，便宜，够用 |
| `text-embedding-3-large` | 3072 | 更准，更贵 |
| `bge-m3` / `bge-large-zh` | 1024 | 开源，中文强，可本地跑（需装 sentence-transformers） |

两条路：找一个带 embedding 端点的网关，或本地跑开源模型。无论哪条，改动都只有
下面那一行——retriever 和整条 LCEL 链一个字都不用动。

## retriever 为什么能直接接进 LCEL

retriever 本身就是 Runnable：输入问题字符串，输出 `list[Document]`。因此可以像前面
几阶段的链一样直接用管道组合：

```python
rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | model
    | StrOutputParser()
)
```

字典这一步并行准备两个 prompt 变量：`context` 走检索链，`question` 原样透传。
这不是 Agent；检索步骤和顺序都由代码写死，模型没有自主选路。

## grounded generation：约束模型别猜

RAG 不会自动消灭幻觉。关键约束在 system prompt：

> 只依据资料回答；资料里没有写的，明确说“资料里没有提到”，不要猜测。

demo 用“是否支持海外配送”验证资料缺失路径。它只能降低幻觉，不构成硬保证；生产系统
还要做引用、忠实度评测，并把外部文档视为不可信输入，防范其中夹带 prompt injection。

## 三个最重要的调参

- `chunk_size`：一个文块多大；
- `chunk_overlap`：相邻块重复多少；
- `k`：每次取几块。

没有通用最佳值。用真实问题集看“答案所在块有没有被召回”（recall），再看最终回答是否
忠于资料；不要只凭肉眼挑数字。

---

**一句话**：RAG 不让模型凭空变聪明，而是在回答前替它找对资料；检索决定“看什么”，
模型决定“怎么说”。

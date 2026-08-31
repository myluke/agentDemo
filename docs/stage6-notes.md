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

### 常见误解：能不能直接把整个文档丢给它？

**不能。`/v1/embeddings` 是个「哑函数」：给一段文本，返回一个向量，仅此而已。**
它不接受文件、不解析 PDF、不切分、不理解文档结构——切分是你的活。

两个硬约束：

**1. 有 token 上限，塞不下整篇**

| 模型 | 单次输入上限 |
|---|---|
| `text-embedding-3-small` / `-large` | 8191 token |
| `text-embedding-v4`（千问） | 8192 token，且单次最多 10 条 |
| `embedding-3`（智谱） | 8K |

一份产品手册几万字，直接扔进去要么报错，要么被**静默截断**——后者更坑，你以为存进去
了，其实只有开头一段。

**2. 就算塞得下，一个向量代表整篇也没用**

这才是根本原因。假设手册里有退货、退款、会员、客服四类内容，压成一个向量后，它落在
这四个主题的「平均位置」——一个谁都不像的点：

```text
问「退款多久到账」→ 整篇的向量   → 相似度 0.31（不高不低，谁都不像）
                 → 退款那一块   → 相似度 0.88（明确命中）
```

而且检索到了也没用：你会把整篇几万字塞进 prompt，那 RAG 就白做了——本来就是为了
**不发全文**才检索的。

所以流水线里这四步，接口只管其中一步：

```text
读文件 → 提取纯文本 → 切分 → 调 /v1/embeddings → 存向量库
  ↑         ↑          ↑          ↑
 你的活    你的活     你的活    接口只管这一步
```

`rag_basic.py` 里对应的就是那两行：

```python
splitter = RecursiveCharacterTextSplitter(chunk_size=60, chunk_overlap=15)
chunks = splitter.create_documents([DOC])
```

### 「什么都不用管」的东西确实存在：托管向量库

如果确实不想管切分，那要找的不是 embedding 接口，而是**托管向量库**——OpenAI 的
`/v1/vector_stores` 把解析、切分、向量化、建索引全包了：

```bash
curl .../v1/vector_stores/vs_abc/files  -d '{"file_id": "file_xyz"}'   # PDF 直接传
curl .../v1/vector_stores/vs_abc/search -d '{"query": "退款多久到账"}'  # 直接问
```

| | 管什么 | 你要做什么 |
|---|---|---|
| `/v1/embeddings` | 只做「文本 → 向量」 | 解析、切分、存储、检索全自己来 |
| `/v1/vector_stores` | 从文件到检索全包 | 传文件、发问 |

代价是 `chunk_size`、`chunk_overlap`、`k` 全由平台定，出了问题（该召回的没召回）你
没有旋钮可调。Anthropic 没有对应产品；国内阿里云百炼、智谱有类似的知识库服务。

**阶段 6 故意走前者**：先手搓一遍，才知道那三个参数影响的是什么。真上生产嫌调参麻烦
再换托管不迟；反过来先用托管，出了问题连该怪哪一步都定位不了。

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

## 从「跑通」到「能用」：业内私有部署通用方案

`rag_basic.py` 演示的是最小闭环；企业内部知识问答通常把检索部分升级成下面这条流水线：

```text
问题 ─┬─ BM25 关键词召回 ─┐
      └─ 向量语义召回   ──┴─ RRF 融合 ─→ rerank 重排 ─→ top-k context ─→ 大模型
             （召回 20~100）       （精排 3~10）
```

### 为什么不是只用向量检索

两类检索的强项互补：

| 检索 | 擅长 | 弱点 |
|---|---|---|
| 向量（dense） | 同义表达、自然语言语义；如「喵星人」找「猫」 | 型号、编号、专有名词、罕见 token 可能被语义平均掉 |
| BM25（sparse） | 精确词、数字、错误码、产品型号；罕见词有高 IDF 权重 | 换一种说法就可能完全匹配不到 |

因此业内常见做法是两路并行召回，再用 **RRF（Reciprocal Rank Fusion）** 按名次合并。两路分数的量纲不同：向量余弦相似度通常在 0～1，BM25 没有固定上限，不能未经归一化就直接相加；RRF 只使用名次，默认不需要为每批语料重新调权重。

本仓库的 [`rag_hybrid.py`](../rag_hybrid.py) 用零依赖 BM25 + `InMemoryVectorStore` + RRF 演示这一步，并用带 `VIP-2049` 的罕见编号验证 BM25 的价值。它和 [`rag_basic.py`](../rag_basic.py) 共用 `bigrams`，确保差异来自检索算法，而不是切词差异。

### 常见误解：向量数据库和 Elasticsearch 是同一个东西吗

不是，但两者的边界正在重叠。它们是上表两路检索各自的**存储载体**：

| | 向量数据库（Milvus / Qdrant / Chroma / FAISS） | Elasticsearch / OpenSearch |
|---|---|---|
| 存什么 | 定长浮点向量 + 原文和 metadata | 倒排索引（词 → 文档列表） |
| 怎么找 | 向量距离最近邻（ANN 近似搜索） | 关键词匹配，用 BM25 打分 |
| 擅长 | 语义相似：「喵星人」能召回「猫」 | 字面精确：型号 `VIP-2049`、错误码、人名 |
| 短板 | 生僻专名和编号容易被语义平均掉 | 换一种说法就完全召不回 |

对应到本仓库：

- `rag_basic.py` 的 `LocalEmbeddings` + `InMemoryVectorStore` 是**向量库那一路**的最小版；
- `rag_hybrid.py` 的 BM25 是 **Elasticsearch 那一路的算法内核**——ES 的默认打分函数就是
  BM25，这里只是没起一个 ES 服务，直接在内存里跑了同一个公式。

需要留意一个反直觉的点：`LocalEmbeddings` 虽然挂在「向量」这一路，算的却是字面 bigram
重叠，因此它更像一个手搓的弱化 BM25，而不是真正的语义检索。要看到上表「向量」那一列
的能力，必须换成真 embedding 模型。

所谓 hybrid RAG，就是把这两类系统并起来再融合排序，各自补对方的短板。

**边界重叠**：ES 8.x 起自带 `dense_vector` 字段和 kNN 检索，一套系统就能跑两路；反过来
Milvus / Qdrant 也在补 sparse 向量和全文检索。所以选型往往不是「谁能做」，而是「团队
已经在运维哪一个」——已有 ES 集群就先在 ES 里加向量字段，已有 PostgreSQL 就先上
pgvector，别为一个 demo 规模的知识库多引入一套需要独立运维的存储。

### 为什么还需要 rerank

召回和精排是两个目标：

1. **召回（recall）**：候选宁可多一些，确保答案所在的块在候选里；
2. **重排（precision）**：候选多会稀释重点、增加 token，因此用更精确的模型把候选收敛到少数几块。

生产常用 cross-encoder，例如 `bge-reranker-v2-m3`：它把“问题 + 文块”成对输入，直接判断相关性，比两个独立向量的距离更细。`rag_hybrid.py` 为了不再增加依赖，使用已有的 Claude Haiku 结构化输出，只让它返回候选编号；这是同样的 rerank 接口形状，但成本和延迟通常高于本地 cross-encoder。实际部署应把它替换成自托管 reranker 服务。

### 一套常见的私有化组件栈

| 环节 | 常见选型 | 关键考虑 |
|---|---|---|
| 文档解析 | MinerU、Docling、Unstructured、OCR | PDF 版面、表格、扫描件质量往往比模型大小更影响效果 |
| 切分 | 版面感知切分、父子块 | 小块用于召回，父块用于提供完整上下文；保留标题、页码和来源 |
| Embedding | 本地 `bge-m3`、Qwen Embedding；TEI/vLLM/Xinference | embedding 服务和索引必须使用同一模型/维度 |
| 向量库 | Milvus、Qdrant；已有 PostgreSQL 可用 pgvector | 持久化、metadata filter、租户隔离、备份和扩容 |
| 关键词检索 | Elasticsearch / OpenSearch，或向量库自带 sparse/BM25 | 专有名词、编号、错误码检索；通常和 dense 结果做 RRF |
| 重排 | `bge-reranker-v2-m3`、Qwen Reranker | 召回 20～100，精排到 3～10；关注吞吐和延迟 |
| 生成模型 | vLLM/SGLang 自托管 Qwen、DeepSeek、GLM 等 | GPU、并发、上下文窗口、量化和模型许可 |
| 编排 | LangChain / LlamaIndex，或自建薄服务 | 保持 retriever 的输入/输出契约，方便替换组件 |
| 评估与观测 | RAGAS、Langfuse（均可私有部署） | 召回率、忠实度、引用正确性、延迟、token 和失败样本 |

### 两种落地路线

**开箱即用**：RAGFlow、Dify、FastGPT 等 Docker 私有部署产品。适合先交付内部知识库、权限和工作流，少写基础设施；代价是检索细节、模型服务和版本升级受平台约束。

**自建组合**：`解析器 + LangChain/LlamaIndex + Milvus/Qdrant + bge-m3 + bge-reranker + vLLM/SGLang`。适合需要接入既有 IAM/组织权限、定制召回策略、审计和多租户隔离的团队；运维、GPU、索引重建和评测成本由自己承担。

无论选哪条，真正不能省的是：

- **权限过滤**：按 tenant、部门、角色、文档密级做 metadata filter，且在 BM25 和向量库查询阶段执行；不能先召回全部内容再靠 prompt 防泄露。
- **来源引用**：每个 chunk 保留文档 ID、版本、页码/段落，回答返回可追溯来源。
- **不可信文档隔离**：文档可能夹带 prompt injection；检索内容只能作为资料，不能变成系统指令。`rag_hybrid.py` 的 reranker 已做最小示范，生成链仍需在生产环境配合隔离和测试。
- **可评测调参**：用真实问题集调 `chunk_size`、`overlap`、两路召回数量、RRF 参数和最终 `k`，同时看 recall、答案忠实度、延迟和成本。

**一句话**：私有 RAG 的通用升级不是“换一个更大的模型”，而是“解析好 → dense+sparse 召回 → RRF → rerank → 带引用生成”，再把权限和评测放到检索链路里。

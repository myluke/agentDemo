# 向量数据库：选型与 Chroma 实战笔记

> 本文档是参考笔记，不属于 ROADMAP 阶段主线。
> 素材来自一次完整的讨论与实战：数据去哪了 → 选哪个库 → 用 Chroma 落地
> （对应 demo：[`s06_rag_chroma.py`](../s06_rag_chroma.py)，阶段 6 的存储后端对照）。

## 一、先澄清一个误解：RAG 框架会把数据传给 OpenAI 吗？

不会。LlamaIndex / LangChain 这类框架本身不「上传数据」——索引构建、向量存储
默认都在本地。整条管线只有两个调用点会把数据发出去：

1. **Embedding 调用**：建索引时，文档切块发给嵌入端点算向量；
2. **LLM 调用**：查询时，检索到的文本片段拼进 prompt 发给模型端点。

关键认知：**协议是 OpenAI 的，数据流向由 `base_url` 决定**。本仓库配置
（`llm.py` 的常量 + `OpenAILike` / `ChatOpenAI`）只走自定义网关；嵌入若用本地
实现（`LocalEmbeddings` 或 HuggingFaceEmbedding），嵌入环节连网络都不出。
配上自托管向量库，整条 RAG 管线可以是纯本地的。

## 二、市面主流向量库选型

### 学习 / 原型阶段

| 库 | 特点 |
|---|---|
| **Chroma** | 嵌入式，`pip install` 即用，零运维，教程界事实标准 |
| **FAISS** | Meta 出品，纯库（不算「数据库」），内存检索极快，无持久化服务概念 |
| **LanceDB** | 嵌入式 + 列式存储落盘，serverless 风格 |

### 生产自托管

| 库 | 特点 |
|---|---|
| **Qdrant** | Rust 实现，性能/过滤能力强，API 干净，社区口碑最好的一档 |
| **Milvus** | 功能最全、可水平扩展，适合大规模；运维复杂度也最高 |
| **Weaviate** | 内置混合检索（BM25 + 向量）、模块化插件 |
| **pgvector** | Postgres 扩展。**已有 PG 就优先选它**——不加新组件，事务/备份/权限全复用，千万级以下够用 |

### 托管云服务

Pinecone（纯托管鼻祖）、pgvector 托管版（Supabase / Neon / RDS）、
Elasticsearch / OpenSearch（已有 ES 栈时顺手启用向量字段）。

### 选型原则

- 学习原型：Chroma 或 FAISS，两大框架都有一等公民集成；
- 上生产先问「是否已有 Postgres」——有就 pgvector；需要独立向量服务再选
  Qdrant（轻中型）或 Milvus（大规模）；
- **反 Occam 剃刀的常见错误**：项目没到百万向量就上 Milvus 集群。
  数据量小时嵌入式方案和 pgvector 完全够，别为不存在的规模付运维税。

## 三、Chroma 实战（`s06_rag_chroma.py`）

与 `s06_rag_basic.py` 是同一条 RAG 流水线，只有第 4 步「存」换了实现：

```python
# 原：进程退出即丢
store = InMemoryVectorStore.from_documents(chunks, LocalEmbeddings())
# 现：落盘持久化
store = Chroma(collection_name=..., embedding_function=LocalEmbeddings(),
               persist_directory=str(PERSIST_DIR))
```

### 收获 1：「换库只改一行」是接口契约兑现的承诺

LangChain 把「文本怎么变向量」（`Embeddings`）和「向量存哪、怎么查」
（`VectorStore`）拆成两个接口。`store.as_retriever()` 返回的都是同一个
Retriever Runnable，所以 `retriever | format_docs | prompt | model` 那条链
一个字不用改。换 PGVector / Qdrant / Milvus 同理。

### 收获 2：持久化解决的是「重复嵌入」问题

`InMemoryVectorStore` 每次启动都要全量重新嵌入。demo 里无感；真实项目里嵌入
要调外部 API——按 token 收费、有速率限制、几万块文档跑几分钟。落盘后二次启动
直接复用：

```
RUN 1: [store] 首次建库，嵌入 6 块并写入 chroma_db/
RUN 2: [store] 复用已落盘的 6 条向量，跳过嵌入
```

已知边界：只判集合空不空，不判内容版本——源文档改了不会自动重建。
升级路径：内容哈希当 id + upsert。

### 收获 3（最重要的坑）：内置 `hash()` 不能用于持久化

`LocalEmbeddings._vec` 原来用 `hash(g)` 给 bigram 分桶。Python 对 str 的 hash
**每个进程随机加盐**（PYTHONHASHSEED），同一个 bigram 这次进程算出桶 17、
下次算出桶 300：

- 内存库：建库和查询在同一进程，盐相同，**看不出任何问题**；
- 落盘后：下次进程的查询向量与库里文档向量落在完全不同的维度，
  点积趋近 0，**检索静默失效——不报错，只是永远搜不到**。

修复：改用确定性的 `zlib.crc32(g.encode())`。验证方式：用两个不同的
`PYTHONHASHSEED` 各跑一次，均命中已落盘向量且自检通过。

**通用教训**：凡是要落盘、要跨进程复现的哈希，都不能用内置 `hash()`；
这类 bug 只在「上持久化」这一步才暴露，且以静默降级而非报错的形式出现——
所以换存储后端时，必须带着与原实现相同的检索断言（self-check）回归。

## 四、用 GUI 工具连接 chroma_db/（嵌入式 vs client/server）

Chroma 有两种形态，**同一份数据目录两种方式都能打开**：

| 形态 | 谁在读写数据 | 场景 |
|---|---|---|
| 嵌入式 | 库进程直接读写本地目录，零运维 | demo 用的这种（`persist_directory=`） |
| client/server | 独立服务 + HTTP API | GUI 工具、多进程共享时 |

关键认知：`chroma_db/` 只是个**数据目录，不是服务**。GUI 数据库工具走 HTTP
客户端模式，连不上一个没在监听的端口——要连，先把 Chroma 以服务形式跑起来，
指向同一个目录：

```bash
cd /Users/luke/websites/agentDemo
.venv/bin/chroma run --path chroma_db --host 127.0.0.1 --port 8001
```

GUI 连接参数：主机 `127.0.0.1`、端口 `8001`，用户名/密码留空（本地服务默认
无鉴权），数据库留空，URL 参数清掉 `sslmode=prefer` 之类（那是 Postgres 的
参数，Chroma 用不上）。连上即可看到 demo 建的 collection 和 6 条向量。

三个注意点：

1. **端口别用 8000**：`s10_web_agent.py` 绑在 8000，避开；
2. **别双开写入**：嵌入式模式对数据目录是独占访问。服务跑着时再运行
   `s06_rag_chroma.py`（嵌入式打开同一目录）可能锁冲突或读到不一致状态。
   GUI 看完数据，关掉服务再跑 demo；
3. **服务是前台进程**：`chroma run` 占住终端，Ctrl+C 即停；数据始终在
   `chroma_db/` 目录里，服务停了 demo 照常用。

## 五、相关文件

| 文件 | 角色 |
|---|---|
| `s06_rag_basic.py` | 内存版基线（含 crc32 修复） |
| `s06_rag_chroma.py` | Chroma 持久化对照 |
| `docs/stage6-notes.md` | 阶段 6 主线笔记 |
| `docs/llamaindex.md` | LlamaIndex 参考（数据流向的讨论起点） |
| `chroma_db/` | 落盘目录，已 gitignore，删掉即回到首次建库状态 |

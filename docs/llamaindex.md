# LlamaIndex 简介

> 本文档是参考笔记，不属于 ROADMAP 阶段主线（主线是 LangChain）。
> 目的：了解 LlamaIndex 是什么、解决什么问题、与 LangChain 的分工差异，以及基本用法。

## 一、LlamaIndex 是什么

LlamaIndex（前身 GPT Index）是一个 **以数据为中心（data-centric）的 LLM 应用框架**，
核心定位是把「你的私有数据」接入 LLM——即 RAG（检索增强生成）场景的专用框架。

一句话对比：

- **LangChain**：通用编排框架，重心在「链 / Agent / 工具调用」的流程组织（本仓库阶段 1–9 所学）。
- **LlamaIndex**：数据接入框架，重心在「加载 → 切分 → 索引 → 检索 → 合成」这条数据管道。

两者不互斥，常见组合是：LlamaIndex 做检索层，LangChain（或裸写循环）做编排层。

## 二、解决什么问题

LLM 的固有限制：

1. 训练数据有截止日期，不知道你的私有 / 最新数据；
2. 上下文窗口有限，不能把整个知识库塞进 prompt。

LlamaIndex 的答案就是标准 RAG 流水线，并把每一环做成可插拔组件：

```
数据源 → Reader(加载) → Node(切分) → Index(索引) → Retriever(检索) → Query Engine(合成回答)
```

## 三、核心概念

| 概念 | 作用 | 类比本仓库 |
|---|---|---|
| `Document` / `Node` | 原始文档与切分后的文本块（带元数据） | `s06_rag_basic.py` 里的 chunk |
| `Reader`（数据连接器） | 从 PDF / Notion / 数据库 / API 加载数据，生态叫 LlamaHub，有数百个连接器 | 手写的文件读取 |
| `Index` | 组织 Node 的结构。最常用 `VectorStoreIndex`；还有 `SummaryIndex`、`KeywordTableIndex`、`KnowledgeGraphIndex` | 向量库 |
| `Retriever` | 从索引召回相关 Node，支持混合检索、rerank | `s06_rag_hybrid.py` 做的事 |
| `Query Engine` | 检索 + 合成回答的一站式封装，一行 `.query()` | 手拼的 RAG chain |
| `Chat Engine` | 带多轮记忆的 Query Engine | `s05_chat_memory.py` |
| `Agent` | 工具调用循环（FunctionAgent / ReActAgent） | `s08_tools.py` / `s09_agent_graph.py` |

设计哲学差异：LangChain 给你积木（LCEL 自由拼装），LlamaIndex 给你成品电器
（`VectorStoreIndex.from_documents()` 一步到位），需要时再逐层下钻替换组件。

## 四、怎么用

### 安装

```bash
pip install llama-index                     # 全家桶（默认绑 OpenAI）
# 或按需最小化安装：
pip install llama-index-core llama-index-llms-openai llama-index-embeddings-openai
```

### 最小 RAG 示例（5 行）

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

documents = SimpleDirectoryReader("data").load_data()   # 加载 data/ 下所有文件
index = VectorStoreIndex.from_documents(documents)      # 切分 + 嵌入 + 建索引
query_engine = index.as_query_engine()
print(query_engine.query("这份文档讲了什么？"))
```

### 对接自定义网关（本仓库风格）

LlamaIndex 同样支持 OpenAI 协议的自定义 `base_url`，可复用 `llm.py` 里的常量：

```python
from llama_index.llms.openai_like import OpenAILike
from llama_index.core import Settings
from llm import API_KEY, BASE_URL, MODEL   # 只取常量，与教程主线规则一致

Settings.llm = OpenAILike(
    model=MODEL,
    api_base=BASE_URL + "/v1",
    api_key=API_KEY,
    is_chat_model=True,
)
# 注意：嵌入模型需另配 Settings.embed_model，网关若不提供 embeddings 端点，
# 可用本地嵌入（如 HuggingFaceEmbedding）替代。
```

### 持久化与增量

```python
index.storage_context.persist(persist_dir="./storage")  # 落盘，避免每次重建

from llama_index.core import StorageContext, load_index_from_storage
storage = StorageContext.from_defaults(persist_dir="./storage")
index = load_index_from_storage(storage)
```

### 常见进阶方向

- **检索质量**：`SentenceWindowNodeParser`（小块检索、大块合成）、rerank 后处理器、混合检索——对应本仓库 `s06_rag_hybrid.py` 的思路；
- **结构化数据**：`NLSQLTableQueryEngine` 直接对 SQL 库做自然语言查询；
- **多文档路由**：`RouterQueryEngine` 按问题分发到不同索引；
- **可观测**：内置 instrumentation，可接 LangSmith / Arize Phoenix 等。

## 五、选型建议

| 场景 | 建议 |
|---|---|
| 纯 RAG / 知识库问答，想快速出效果 | LlamaIndex，开箱即用 |
| 复杂流程编排、多 Agent、自定义控制流 | LangChain / LangGraph |
| 想理解底层原理 | 像本仓库 `harness/` 一样裸写一遍，两个框架都只是封装 |

## 参考

- 官方文档：https://docs.llamaindex.ai
- 连接器生态：https://llamahub.ai

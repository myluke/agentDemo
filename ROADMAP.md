# LangChain 学习路线

## LangChain vs LangGraph

| | LangChain (LCEL) | LangGraph |
|---|---|---|
| 结构 | **有向无环**管道，一条路走到底 | **状态图**，节点可循环、可回头 |
| 谁决定走向 | 你写死（`\|`、`RunnableBranch`） | 模型自己决定（下一步调哪个工具、还调不调） |
| 状态 | 每步的输入输出，链结束即丢 | 显式 `State`，跨节点累积、可持久化、可中断恢复 |
| 适合 | 步骤已知的流水线：翻译→润色、RAG 问答 | 步骤未知的循环：Agent 反复「思考→调工具→看结果」直到收工 |
| 本仓库 | 阶段 1–4、6–7；阶段 5 是记忆例外 | 阶段 5 的 checkpointer、阶段 8 的 Agent |

一句话：**LangChain 是「链」，你规定顺序；LangGraph 是「图」，模型规定顺序。**

LangGraph 不是 LangChain 的替代品，是它的上层编排。图里每个节点装的仍然是
LCEL 链——所以阶段 1–7 不是铺垫，是阶段 8 的零件。

历史包袱：老教程里的 `AgentExecutor` / `initialize_agent` 是 LangGraph 之前
的 Agent 方案，黑盒、难调试、无法中断，已不推荐，本仓库不用。


由简到繁，每阶段一个可跑 demo。`👉` 标记当前进度。

| # | 阶段 | 核心概念 | demo | 状态 |
|---|------|---------|------|------|
| 1 | LCEL 基础 | `prompt \| model \| parser` 管道 | `hello.py` | ✅ |
| 2 | 顺序链 | `RunnablePassthrough.assign`，上一步喂下一步 | `multi_step_chain.py` | ✅ |
| 3 | 结构化输出 | 让模型返回 JSON/对象，`with_structured_output` | `structured_output.py` | ✅ |
| 4 | 并行 & 分支 | `RunnableParallel` 并发、`RunnableBranch` 条件分流 | `parallel_branch.py` | ✅ |
| 5 | 记忆 / 多轮 | `MessagesState`、checkpointer、`thread_id` | `chat_memory.py` | ✅（例外用 LangGraph） |
| 6 | 检索 (RAG) | 加载→切分→向量化→检索→喂给模型；混合检索 + 重排 | `rag_basic.py` / `rag_hybrid.py` | ✅ |
| 7 | 工具调用 | 给模型挂工具（function calling），模型自己决定调不调 | `tools.py` | 👉 下一步 |
| 8 | Agent | 用 **LangGraph** 编排能自主循环、选工具的 Agent | `agent_graph.py` | ⬜ |

## 约定
- 第 5 阶段因 LangChain core 的消息历史封装已弃用，例外使用 LangGraph checkpointer；阶段 6–7 仍以 LCEL 为主。
- 第 8 阶段用 **LangGraph** 编排 Agent，不用过时的 `AgentExecutor`/`initialize_agent`。
- 流式、异步、LangSmith 可观测性不单列，穿插进各 demo 顺带演示。
- 每完成一阶段：改本表状态为 ✅、移动 `👉`，并在 `implementation-notes.md` 追加记录。

## 为什么用框架？裸写不行吗？

行。`rag_basic.py` 的核心流程翻成 Go 裸写就四步——调 `/v1/embeddings` 拿向量、
点积排序取 top-k、拼提示词、调 `/v1/chat/completions` 解析 SSE，大概 200 行。
`InMemoryVectorStore` 就是 list + 余弦相似度，`|` 就是 `__or__` 重载，没有魔法。
**需求锁死在一条链上，裸写更好**：更快、单二进制、没有 `.venv` 和版本震荡。

框架买到的不是「做不到的能力」，是「不用你写」和「换实现只改一行」：

| 买到 | 本仓库的体现 | 裸写要付的代价 |
|---|---|---|
| 接口契约 | `LocalEmbeddings` 继承 `Embeddings`，换真 embedding 只删这一个类，下游 store/retriever/chain 一行不改 | 自己定 interface 不难，难在**别人的实现都按你的 interface 写**；Chroma/PGVector/Qdrant 各是各的形状，每家都要写适配层 |
| 集成存量 | `RecursiveCharacterTextSplitter` 那套「段落→句→字」逐级降级切，被几万个项目磨过边界 | 中文、Markdown、代码、带表格的 PDF，每种切法都是一个坑，`chunk_overlap` 怎么不劈断句子要自己调 |
| 横切能力 | 链拼好即得 `.invoke` / `.batch` / `.astream` / `.astream_events`；加 `.with_retry()` / `.with_fallbacks()` 一行 | 流式 + 并发 + 重试 + 超时 + 取消，每条链都要重写一遍编排 |
| 可观测性 | 一个 `LANGSMITH_TRACING=true`，每一跳的输入输出、token、耗时全录 | 自己埋 trace；多 agent / 工具循环时没这层基本是瞎调 |
| Agent 循环 | 阶段 7–8 的 tool calling 与自主循环 | 逻辑不难，难在**每家 provider 的 tool_call 格式、并行调用、错误回灌语义都不一样** |

抽象成本是真实的（链里那些 `RunnablePassthrough` 就是抽象税），换来的是
「今天内存库明天 PGVector、今天 gpt-5.4 明天 claude」只动一行。

**选型分界线**
- 单条固定链、上线要稳、团队是 Go → 裸写，框架的灵活性你用不上。
- 要试多种检索/编排组合、要换模型换向量库、要 agent 工具循环 → 用框架，
  否则裸写到第三个月会长出一个更烂的 LangChain。

Go 生态对应物：`langchaingo`（成熟度远不如 Python 版）、Eino（字节，国内生态更贴）。
真上 Go 生产：编排层裸写，但别自己发明切分器和 embedding 抽象，那两块抄现成的。

**本仓库为什么用它**：学的是 RAG/Agent 的**形状**，框架把形状显式化了；
裸写会让形状淹没在 HTTP 和 JSON 解析里。

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
| 6 | 检索 (RAG) | 加载→切分→向量化→检索→喂给模型 | `rag_basic.py` | ✅ |
| 7 | 工具调用 | 给模型挂工具（function calling），模型自己决定调不调 | `tools.py` | 👉 下一步 |
| 8 | Agent | 用 **LangGraph** 编排能自主循环、选工具的 Agent | `agent_graph.py` | ⬜ |

## 约定
- 第 5 阶段因 LangChain core 的消息历史封装已弃用，例外使用 LangGraph checkpointer；阶段 6–7 仍以 LCEL 为主。
- 第 8 阶段用 **LangGraph** 编排 Agent，不用过时的 `AgentExecutor`/`initialize_agent`。
- 流式、异步、LangSmith 可观测性不单列，穿插进各 demo 顺带演示。
- 每完成一阶段：改本表状态为 ✅、移动 `👉`，并在 `implementation-notes.md` 追加记录。

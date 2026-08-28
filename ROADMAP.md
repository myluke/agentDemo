# LangChain 学习路线

由简到繁，每阶段一个可跑 demo。`👉` 标记当前进度。

| # | 阶段 | 核心概念 | demo | 状态 |
|---|------|---------|------|------|
| 1 | LCEL 基础 | `prompt \| model \| parser` 管道 | `hello.py` | ✅ |
| 2 | 顺序链 | `RunnablePassthrough.assign`，上一步喂下一步 | `multi_step_chain.py` | ✅ |
| 3 | 结构化输出 | 让模型返回 JSON/对象，`with_structured_output` | `structured_output.py` | ✅ |
| 4 | 并行 & 分支 | `RunnableParallel` 并发、`RunnableBranch` 条件分流 | `parallel_branch.py` | ✅ |
| 5 | 记忆 / 多轮 | 消息历史，让链记住上下文 | `chat_memory.py` | 👉 下一步 |
| 6 | 检索 (RAG) | 加载→切分→向量化→检索→喂给模型 | `rag_basic.py` | ⬜ |
| 7 | 工具调用 | 给模型挂工具（function calling），模型自己决定调不调 | `tools.py` | ⬜ |
| 8 | Agent | 用 **LangGraph** 编排能自主循环、选工具的 Agent | `agent_graph.py` | ⬜ |

## 约定
- 第 8 阶段用 **LangGraph**，不用过时的 `AgentExecutor`/`initialize_agent`。
- 流式、异步、LangSmith 可观测性不单列，穿插进各 demo 顺带演示。
- 每完成一阶段：改本表状态为 ✅、移动 `👉`，并在 `implementation-notes.md` 追加记录。

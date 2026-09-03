# agentDemo

一个**分阶段的 LangChain 学习仓库**：9 个阶段，每阶段一个可独立运行的 demo，
从 LCEL 管道一路推到 LangGraph Agent。所有模型调用走自建网关（OpenAI 协议，
`langchain-openai`），统一由 `llm.py` 提供客户端。

## 阶段与 demo

| # | 阶段 | 核心概念 | demo |
|---|------|---------|------|
| 1 | LCEL 基础 | `prompt \| model \| parser` | `s01_hello.py` |
| 2 | 顺序链 | `RunnablePassthrough.assign` | `s02_multi_step_chain.py` |
| 3 | 结构化输出 | `with_structured_output` | `s03_structured_output.py` |
| 4 | 并行 & 分支 | `RunnableParallel` / `RunnableBranch` | `s04_parallel_branch.py` |
| 5 | 记忆 / 多轮 | `MessagesState` + checkpointer + `thread_id` | `s05_chat_memory.py` |
| 6 | 检索 (RAG) | 加载→切分→向量化→检索；混合检索 + 重排 | `s06_rag_basic.py` / `s06_rag_hybrid.py` |
| 7 | 可观测性 | `collect_runs` 本地 run 树，LangSmith 上传可选 | `s07_langsmith_tracing.py` |
| 8 | 工具调用 | `@tool` + `bind_tools`，手写 tool 循环 | `s08_tools.py` |
| 9 | Agent | LangGraph `ToolNode` + `tools_condition` 成环 | `s09_agent_graph.py` |

demo 之间**故意互相 import**：`s08_tools.py` 复用 `s06_rag_basic.py` 的 retriever，
`s09_agent_graph.py` 复用 `s08_tools.py` 的工具与已绑定模型——后一阶段是前一阶段的组装，
不是重写。

## harness/ — 主线之外的对照组

[`harness/`](harness/) **不是第 10 阶段**：同一个 agent 循环去掉框架裸写一遍，
只用 `requests` + 标准库直发 `/v1/chat/completions`。五个零件（循环、注册分发、
结果回灌、压缩、确认门）逐一对应框架概念，用来看清阶段 8/9 里 LangChain/LangGraph
到底替你做了什么。与主线**互不 import**（只从 `llm.py` 取凭据常量）；它的工具层
`harness/tools.py` 和主线阶段 8 的 `s08_tools.py` 是两个独立实现。详见
[harness/README.md](harness/README.md)。

## 运行

```bash
pip install -r requirements.txt     # 版本全部钉死
.venv/bin/python s01_hello.py           # 任意一个 demo，各自可独立跑
```

## 配置

复制 `config.ini.example` 为 `config.ini`（已 gitignore），填 `[api]` 的
`api_key` / `base_url`；也可改用 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` /
`ANTHROPIC_BASE_URL` 环境变量。凭据只在 `llm.py` 里读一次，demo 一律从它 import。

## 文档

- [ROADMAP.md](ROADMAP.md) — 学习路线、LangChain vs LangGraph、以及「为什么用框架」的选型讨论
- [implementation-notes.md](implementation-notes.md) — 决策依据与演进历史（为什么这么做、边界在哪）
- `docs/stage{1..9}-notes.md` — 每阶段的详细笔记
- `docs/api-openai.md` / `docs/api-anthropic.md` — 网关侧协议记录

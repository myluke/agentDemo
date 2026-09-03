# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A staged LangChain learning repository. Stages 1–4 cover LCEL basics, sequential
chains, structured output, and parallel/branch workflows; stage 5 covers multi-turn
memory with a LangGraph checkpointer as the one deliberate exception to the LCEL
sequence; stage 6 covers RAG — basic pipeline plus hybrid retrieval and reranking; stage 7 covers
tracing/observability (local `collect_runs` run trees, LangSmith upload optional); stage 8
covers tool calling with a hand-written tool loop; stage 9 wraps that loop in a LangGraph
ReAct graph with a checkpointer. All against the gateway via `langchain-openai` (OpenAI protocol).

`harness/` sits **outside** the staged track: a framework-free agent harness written
against the raw HTTP API (see "harness/ 与教程主线的区别" below).

Demos import each other on purpose: `s08_tools.py` reuses `s06_rag_basic.py`'s retriever,
`s09_agent_graph.py` reuses `s08_tools.py`'s tools and bound model.

课程文件按 `sNN_` 前缀编号，`NN` 即 ROADMAP 的阶段号（阶段 6 有两个 demo，同为 `s06_`）；
`llm.py` 是公共基础设施，不编号。

## Run

```bash
.venv/bin/python s01_hello.py
.venv/bin/python s02_multi_step_chain.py
.venv/bin/python s03_structured_output.py
.venv/bin/python s04_parallel_branch.py
.venv/bin/python s05_chat_memory.py
.venv/bin/python s06_rag_basic.py
.venv/bin/python s06_rag_hybrid.py
.venv/bin/python s07_langsmith_tracing.py
.venv/bin/python s08_tools.py
.venv/bin/python s09_agent_graph.py
.venv/bin/python s10_web_agent.py    # http://127.0.0.1:8000
.venv/bin/python harness/harness.py   # 裸写 harness REPL（教程主线之外，见下节）
pip install -r requirements.txt    # rebuild deps on a fresh machine
```

## harness/ 与教程主线的区别

`harness/` 不是第 10 阶段，是主线的**对照组**——同一个 agent 循环，去掉框架重写一遍：

| | 教程主线（阶段 1–9，仓库根） | `harness/` |
|---|---|---|
| 依赖 | LangChain / LangGraph / `langchain-openai` | 仅 `requests` + 标准库，零新增 |
| 调模型 | `llm.py` 的 `openai_chat()` → `ChatOpenAI` | 自拼 `BASE_URL + "/v1/chat/completions"`，`requests.post` 裸发 |
| 消息 | `AIMessage` / `ToolMessage` 对象 | 原始 dict 进出 |
| 工具 | `@tool` + `bind_tools` + `ToolNode`（根 `s08_tools.py`） | `@register` 注册表 + `dispatch()`（`harness/tools.py`） |
| 历史管理 | checkpointer / `trim_messages` | 手写 `compact()` 摘要压缩 |
| 确认门 | 无 | 危险工具 `[y/N]`，拒绝也回灌 |

改动规则：
- **两边互不 import**。`harness/` 只从 `llm.py` 取 `API_KEY / BASE_URL / MODEL / EFFORT` 常量，不碰任何 LangChain 对象；教程 demo 也不 import `harness/`。
- 根目录的工具 demo 已更名 `s08_tools.py`，与 `harness/tools.py` 不再同名，import 劫持的可能性随之消失。`harness/harness.py` 仍用 `sys.path.append`（不是 `insert(0)`）把仓库根加到**末尾**——它只需要根「能被找到」以 import `llm`，保留这个写法无害。
- 推进学习阶段、改教程 demo → 动仓库根，跟 ROADMAP 阶段表走；改裸写对照 → 只动 `harness/`，不进阶段表。

## Credentials

All model clients come from `llm.py` — `openai_chat(model, **kwargs)` builds a
`ChatOpenAI` against the custom gateway (`base_url` + `/v1`). Credentials are read
once in `llm.py`: `config.ini`'s `[api]` section (`api_key` / `base_url`) first,
falling back to the `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`
env vars. `config.ini` is gitignored; copy `config.ini.example`. Never re-read these
env vars in a demo file — import from `llm.py`.

## implementation-notes.md（必须同步）

实现或变更功能时，**必须**同步在 `implementation-notes.md` 顶部追加一条记录
（按日期倒序）。分工：CLAUDE.md 写当前生效的规则与架构现状（每次会话自动注入）；
notes 写决策依据与演进历史，记「为什么这么做、边界在哪、契约与安全语义、踩过的坑」
（需显式阅读）。

## 学习路线（必须先看）

本仓库用于学习 LangChain，demo 由简到繁推进。开始新 demo 或推进阶段前，
**先读 [ROADMAP.md](ROADMAP.md)** 确认当前进度（`👉` 标记）与下一步。

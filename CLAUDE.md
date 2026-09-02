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

Demos import each other on purpose: `tools.py` reuses `rag_basic.py`'s retriever,
`agent_graph.py` reuses `tools.py`'s tools and bound model.

## Run

```bash
.venv/bin/python hello.py
.venv/bin/python multi_step_chain.py
.venv/bin/python structured_output.py
.venv/bin/python parallel_branch.py
.venv/bin/python chat_memory.py
.venv/bin/python rag_basic.py
.venv/bin/python rag_hybrid.py
.venv/bin/python langsmith_tracing.py
.venv/bin/python tools.py
.venv/bin/python agent_graph.py
.venv/bin/python web_agent.py    # http://127.0.0.1:8000
pip install -r requirements.txt    # rebuild deps on a fresh machine
```

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

# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this is

A staged LangChain learning repository. Stages 1–4 cover LCEL basics, sequential
chains, structured output, and parallel/branch workflows; stage 5 covers multi-turn
memory with a LangGraph checkpointer as the one deliberate exception to the LCEL
sequence, all against Codex via `langchain-anthropic`.

## Run

```bash
.venv/bin/python s01_hello.py
.venv/bin/python s02_multi_step_chain.py
.venv/bin/python s03_structured_output.py
.venv/bin/python s04_parallel_branch.py
.venv/bin/python s05_chat_memory.py
.venv/bin/python s06_rag_basic.py
.venv/bin/python s06_rag_hybrid.py
pip install -r requirements.txt    # rebuild deps on a fresh machine
```

## Credentials

The `ChatAnthropic` client reads `ANTHROPIC_AUTH_TOKEN` (falling back to
`ANTHROPIC_API_KEY`) and `ANTHROPIC_BASE_URL` from the environment — this points
at a custom gateway, not Anthropic's default endpoint. Both are expected to be
set in the shell already; there is no `.env`.

## implementation-notes.md（必须同步）

实现或变更功能时，**必须**同步在 `implementation-notes.md` 顶部追加一条记录
（按日期倒序）。分工：AGENTS.md 写当前生效的规则与架构现状（每次会话自动注入）；
notes 写决策依据与演进历史，记「为什么这么做、边界在哪、契约与安全语义、踩过的坑」
（需显式阅读）。

## 学习路线（必须先看）

本仓库用于学习 LangChain，demo 由简到繁推进。开始新 demo 或推进阶段前，
**先读 [ROADMAP.md](ROADMAP.md)** 确认当前进度（`👉` 标记）与下一步。

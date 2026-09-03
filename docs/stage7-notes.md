# 阶段 7 · LangSmith 可观测性 — 回顾笔记

配套代码：[`s07_langsmith_tracing.py`](../s07_langsmith_tracing.py)

---

## 一句话机制

**每个 Runnable 跑一次就是一个 run；run 按调用关系嵌套成树，每个节点自带
输入、输出、耗时、token、错误。** tracing 就是把这棵树留下来。

链短的时候 `print` 够用；链一长（阶段 6 的 RAG 有检索、拼接、模型三层，
阶段 9 的 Agent 还会循环 N 圈），出问题时你需要的是「哪一步慢、哪一步错、
模型实际收到了什么」，print 给不出这些。

## 三个开关，别混为一谈

| 开关 | 看到什么 | 依赖 | 什么时候用 |
|---|---|---|---|
| `collect_runs()` | 本地 run 树：层级、每步耗时、token、错误节点 | 无 | 写自检、离线调试 |
| `LANGSMITH_TRACING=true` | 同一棵树上传到网页，可跨运行筛选/对比/分享 | API key + 网络 | 团队排查、看历史趋势 |
| `OPENAI_LOG=debug` | 单次 HTTP 请求的报文（阶段 3 用过） | 无 | 怀疑 SDK / 网关层出问题 |

关键区别：**`LANGSMITH_TRACING` 不产生 run 树，只决定这棵树上不上传**。
树本来就有，`collect_runs()` 只是在本地把它接住。所以：

- 想在代码里断言 trace 内容 → `collect_runs()`，不用 key、不用网络。
- `OPENAI_LOG` 不知道「链」的存在——它看到的是 N 次独立的 HTTP 请求，
  给不出父子层级，也不知道哪次属于哪一步。两者互补，不互替。

要看网页版：

```bash
LANGSMITH_TRACING=true LANGSMITH_API_KEY=ls__xxx LANGSMITH_PROJECT=agentDemo \
  .venv/bin/python s06_rag_basic.py
```

代码一行不改——这就是「旁路观测」的含义。

## 读一棵 run 树

```text
intro-writer [chain] 3.71s
  draft [chain] 2.02s
    ChatPromptTemplate [prompt] 0.00s
    ChatOpenAI [llm] 2.02s  tokens in/out=29/39
    StrOutputParser [parser] 0.00s
  polish [chain] 1.69s
    ...
```

三件事一眼可见：

- **哪一步慢**：3.71s 里 draft 占 2.02s，且几乎全在 `ChatOpenAI` 上——
  慢在模型，不是在拼提示词或解析。这个判断 print 做不到。
- **token 账单按步骤拆开**：只有 `run_type == "llm"` 的 run 有 token，位置在
  `outputs["llm_output"]["token_usage"]`（`prompt_tokens` / `completion_tokens`）。
  chain 节点没有，别在父节点上找。
- **注意 `in=64`**：polish 的输入 token 比 draft 多一倍——因为它的提示词里包含了
  draft 的输出。多步链的成本不是线性叠加，trace 让这件事变得可见。

## 命名：`with_config(run_name=...)`

不起名的话树上全是 `RunnableSequence`，三层嵌套之后完全认不出谁是谁。

```python
draft = (prompt | model | parser).with_config(run_name="draft")
```

纯观测配置，去掉它链照跑。**给每条有意义的子链起名**是 trace 可读的前提。

## `tags` / `metadata`：筛选维度

在 invoke 时传，不是在构造时传：

```python
chain.invoke(payload, config={"tags": ["stage7", "demo"],
                              "metadata": {"env": "local", "stage": 7}})
```

用途是在 LangSmith 里过滤：只看生产环境的、只看某个版本的、只看失败的。
本地则从 `root.tags` / `root.extra["metadata"]` 读回。

**安全边界**：tags 和 metadata 会随 prompt、响应、检索片段一起上传。
密钥、token、用户身份信息一律不放这里。

## 错误定位

一个节点炸了，异常会沿树往上冒，所以**根节点和出错节点都会记 error**。
定位靠的是找**最深的**那个带 error 的节点：

```text
intro-writer-broken [chain] 2.16s  ❌ ValueError('下游解析失败（模拟）')
  draft [chain] 2.16s                     ← 成功，无 error
  post-process [chain] 0.00s  ❌ ValueError('下游解析失败（模拟）')   ← 真凶
```

自检就卡这个语义：出错的是 `post-process` 而不是 `draft`。

**坑**：`run.error` 是完整 traceback 字符串，直接打印会把树冲垮，
要截到第一行（demo 里按 `Traceback` 切）。

## 隐私边界（上生产前必读）

开 tracing 等于把这些东西发到 LangSmith 服务器：

- 完整 prompt（含你拼进去的一切）
- 模型响应
- RAG 检索到的原文片段 ← 最容易泄露业务数据的地方
- tags / metadata

上线前至少要做：

| 事项 | 做法 |
|---|---|
| 脱敏 | 敏感字段进 prompt 前替换掉，或用 LangSmith 的 masking |
| 采样 | 不必 100% 上传，按比例采样降低暴露面和成本 |
| 保留策略 | 配置数据保留期限，别让 trace 无限堆积 |
| 访问权限 | LangSmith 项目按团队隔离，别所有人都能看生产 trace |
| 密钥 | 永远不进 prompt / tags / metadata |

**tracing 关掉必须不影响业务结果**——它是旁路，不是链的一环。
demo 的自检显式断言 `LANGSMITH_TRACING == "false"`，把这件事测住了。

## 和阶段 8–9 的关系

阶段 8 的工具调用、阶段 9 的 Agent 循环，run 树会明显变深：
agent → tools → agent → tools → ... 每圈都是一层。**先学会看树，再进循环**，
否则 Agent 跑了 5 圈却答错时，你只能靠 print 猜它第几圈跑偏的。

---

**一句话**：run 树是链的执行记录，`collect_runs()` 留在本地、
`LANGSMITH_TRACING` 决定上不上传；看树回答「哪一步慢、哪一步错、
模型实际看到了什么」，而 `OPENAI_LOG` 只看得到单次 HTTP 报文。

# 阶段 9 · Agent（LangGraph 编排）— 回顾笔记

配套代码：[`s09_agent_graph.py`](../s09_agent_graph.py)

---

## 一句话机制

**把阶段 8 手写的「模型说要调 → 执行 → 回灌 → 再问模型」循环，
交给一张有回边的状态图，由模型决定转几圈。**

```text
START → agent ──(有 tool_calls)──→ tools ──┐
          ↑                                │
          └────────────────────────────────┘
          └──(无 tool_calls)──→ END
```

## 链和图的根本区别：那条回边

阶段 1–8 用 `|` 拼的链是**有向无环**的——走到底就结束，顺序你写死。
这里 `tools → agent` 是一条**回边**，形成环。跑几圈由模型的 tool_calls 决定，
你在代码里写不死。

**这就是全部区别。** 不是 LangGraph 有什么魔法，是有环和无环的区别。

| | 链（LCEL） | 图（LangGraph） |
|---|---|---|
| 结构 | 有向无环，一条路走到底 | 状态图，可循环、可回头 |
| 谁定顺序 | 你（`\|`、`RunnableBranch`） | 模型（下一步调不调工具） |
| 跑多少步 | 编译期已知 | 运行期才知道 |

自检直接读边来断言这件事：

```python
edges = {(e[0], e[1]) for e in graph.get_graph().edges if e[1] != "__end__"}
assert ("tools", "agent") in edges   # 没有回边就退化成单向链，Agent 名存实亡
```

## 零件全是前面阶段的

| 零件 | 来自 | 作用 |
|---|---|---|
| `TOOLS`、已 bind 的 `model` | 阶段 8 `s08_tools.py` | 决策 + 动手 |
| `search_policy` → retriever | 阶段 6 `s06_rag_basic.py` | 模型想查才查 |
| `checkpointer` + `thread_id` | 阶段 5 `s05_chat_memory.py` | 跨轮记忆 |
| `ToolNode` / `tools_condition` | LangGraph 预制件 | 替掉阶段 8 手写的两段 |

`s09_agent_graph.py` 直接 `from s08_tools import TOOLS, model`，不复制。
**教学价值恰恰在这条复用链上**：阶段 6 的检索器原样成为阶段 8 的工具，
阶段 8 的工具原样进阶段 9 的图。

## 三行组装

```python
builder.add_node(agent)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
builder.add_edge("tools", "agent")          # ← 回边
```

| 预制件 | 等价于阶段 8 的 |
|---|---|
| `tools_condition` | `if not ai.tool_calls: return ai.content` |
| `ToolNode(TOOLS)` | `for call in ai.tool_calls: ...append(ToolMessage(...))` |
| 回边 + `recursion_limit` | `for _ in range(max_turns)` |

`tools_condition` 的语义可以直接断言（不用调模型）：

```python
assert tools_condition({"messages": [带tool_calls的AIMessage]}) == "tools"
assert tools_condition({"messages": [AIMessage("答完了")]}) == END
```

## system 提示不进 state

```python
def agent(state: MessagesState) -> dict:
    return {"messages": model.invoke([SYSTEM] + state["messages"])}
```

每次现拼，不存进 state。存进去的话会被 checkpointer 跟着消息历史反复持久化，
多轮后还可能被裁剪策略误伤。**固定指令归代码，对话历史归 state。**

## 实际跑起来是什么样

```text
【第1轮】黑金会员买 288 元的猫粮，按会员折扣要付多少？
  [调用] search_policy({'query': '黑金会员折扣规则...'})
  [结果] ...黑金会员无限免运费，且享有全场九折...
  [调用] exchange({'amount': 288, 'rate': 0.9})
  [结果] 259.2
  [答] 黑金会员享受全场九折，288 元猫粮折后应付 259.2 元。
```

一个问题触发**两类工具、两圈循环**：先查政策拿到「九折」，再拿这个数去算钱。
**代码里没有任何编排**——调几次、什么顺序、用不用第二个工具，全是模型看着
上一步结果决定的。这在阶段 4 的 `RunnableBranch` 里做不到（分支是你写死的）。

第 2 轮只说「那普通会员呢」，没重复上下文——靠 checkpointer 接住（阶段 5 语义原样生效）。

## 护栏

| 风险 | 护栏 |
|---|---|
| 无限循环烧 token | `recursion_limit`（默认 25），超了抛 `GraphRecursionError` |
| 工具报错拖垮整轮 | ToolNode 默认把异常转成 ToolMessage 回灌，让模型自己纠错 |
| 模型凭印象作答 | system 里明确要求「涉及政策必须先 search_policy 查证」 |
| 跨用户串数据 | `thread_id` 是**分区键不是鉴权**，服务端必须校验归属（阶段 5 同款警告） |

## 为什么不用 `AgentExecutor` / `initialize_agent`

老教程里的这两个 API 干同样的事，但是黑盒：不能在中间打断点、不能改状态、
不能持久化、不能人工介入。已被官方标记不推荐。

图的每个节点都是普通函数，能断点、能改 state、能挂 checkpointer 中断恢复。
**同样是循环，一个是黑盒一个是白盒。**

`create_react_agent` 是 LangGraph 自己的一行版预制件，做的正是本文件这四行组装。
demo 手写是为了看清结构；生产里直接用它没问题。

## 什么时候不该上 Agent

Agent 的代价是**不可预测**：跑几圈、花多少 token、走哪条路都不确定，
调试成本比链高一个量级。

- 步骤已知固定 → 用链（阶段 1–4）。写死的流程更快、更便宜、更好测。
- 只是要检索后回答 → 用阶段 6 的 RAG 链，别套 Agent。
- 步骤取决于中间结果、工具要不要用不确定 → 才上 Agent。

**先问「这真的需要模型来决定顺序吗」**，多数业务的答案是不需要。

---

**一句话**：Agent = 阶段 8 的循环 + 一条回边 + 阶段 5 的记忆；
链是你规定顺序，图是模型规定跑几圈——代价是不可预测，所以能用链就别用图。

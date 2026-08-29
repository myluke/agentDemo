# 阶段 5 · 记忆 / 多轮对话 — 回顾笔记

配套代码：[`chat_memory.py`](../chat_memory.py)

---

## 核心：把过去的消息，作为消息再喂回模型

模型本身是无状态的——每次请求都是"失忆"的。多轮记忆不是模型自己记住了，
而是**每一轮都把之前的 human/ai 消息一起发回去**。这正是阶段 2
[「为什么不用 `ai` 消息」](stage2-notes.md) 埋的伏笔：那里传的是数据，
这里传的才是真正的对话历史。

## 为什么本阶段例外用 LangGraph

LCEL 里做消息历史的现成封装是 `RunnableWithMessageHistory`，但它在
`langchain-core` 1.3.3 起**已被官方弃用**，构造即打印告警，告警原文就是
"改用 LangGraph 的内置 persistence"；core 里也没有未弃用的等价替代。

所以阶段 5 破例提前借用 LangGraph，但**只借一件事**：用 checkpointer 按
`thread_id` 存取消息历史。循环、条件跳转、工具、自主决策一律不碰——那些是
阶段 8 的内容。阶段 6–7 仍回到 LCEL。

## 三件套

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

def call_model(state: MessagesState) -> dict:
    return {"messages": model.invoke(state["messages"])}

builder = StateGraph(MessagesState)
builder.add_node(call_model)
builder.add_edge(START, "call_model")
graph = builder.compile(checkpointer=InMemorySaver())
```

| 组件 | 作用 |
|---|---|
| `MessagesState` | 内置 `add_messages` reducer——节点返回的消息**自动追加**进历史，不用手写 append |
| `checkpointer`（`InMemorySaver`） | 每轮结束存下整个状态，下一轮同 `thread_id` 自动读回 |
| `thread_id` | 状态分区键：不同 `thread_id` 各自独立记忆，互不串 |

## `thread_id`：多会话隔离

每次 `invoke` 必须在 config 里带 `thread_id`（不传会直接报错）：

```python
graph.invoke({"messages": [HumanMessage("我叫 Luke")]},
             config={"configurable": {"thread_id": "A"}})
```

- 同一 `thread_id` 连续 invoke → 共享历史，模型记得上文。
- 换一个 `thread_id` → 全新记忆。demo 里线程 A 记住 Luke，线程 B 问名字答不出，
  就是隔离生效。

**安全边界**：`thread_id` 只是分区键，**不是鉴权**。真实服务里必须在服务端
校验当前用户是否有权访问这个 thread，不能直接信任外部传进来的 ID——否则
换一个别人的 thread_id 就能读到别人的对话历史。

## 记忆的持久性

`InMemorySaver` 只存在**当前 Python 进程的内存**里，进程一退出记忆就没了
（demo 每次重跑都是干净的）。官方 docstring 明确写它只用于调试/测试。

生产要跨进程/重启保留记忆，换持久化 saver：`PostgresSaver`、`SqliteSaver` 等
（各自独立的包，落盘存储，重启后历史还在）。换 saver 不改图结构，只改
`compile(checkpointer=...)` 那一处。

## 和阶段 8 的关系

这里的 `StateGraph` / `MessagesState` / `checkpointer` / `thread_id` 不是
阶段 5 的一次性道具，正是阶段 8 完整 Agent 的零件。阶段 8 会在此基础上加
条件边和工具节点，让图**循环**（思考→调工具→看结果→再思考）。阶段 5 先把
"带记忆的一步"跑通。

---

**一句话**：多轮记忆 = 每轮把历史消息再喂回模型；LangGraph 用 `MessagesState`
累加消息、`checkpointer` 存历史、`thread_id` 隔离会话，三件套搞定。

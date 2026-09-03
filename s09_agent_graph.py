"""Agent 演示：用 LangGraph 把阶段 8 的手写循环变成一张会自己转的图。

阶段 8 的 `run()` 里那个 for 循环——「模型说要调 → 执行 → 结果回灌 → 再问模型」——
就是 Agent 的全部。本阶段只做两件事：把循环交给状态图，以及给它记忆。

图长这样（ReAct 模式）：

    START → agent ──(有 tool_calls)──→ tools ──┐
              ↑                                │
              └────────────────────────────────┘
              └──(无 tool_calls)──→ END

和阶段 1-8 的**根本区别**：`|` 拼出来的链是有向无环的，走到底就结束；
这里 tools 有一条边**回指** agent，形成环。跑几圈由模型的 tool_calls 决定，
你写死不了——这就是「模型规定顺序」。

零件全是前面阶段的：
- 工具、模型：阶段 8 的 `tools.py`（含复用阶段 6 retriever 的 search_policy）。
- checkpointer + thread_id：阶段 5 的记忆，让 Agent 跨轮记得上文。
- ToolNode / tools_condition：LangGraph 预制件，等价于阶段 8 手写的
  「遍历 tool_calls 执行、包成 ToolMessage」和「还有没有 tool_calls」判断。

历史包袱：老教程的 `AgentExecutor` / `initialize_agent` 干同样的事，但是黑盒、
不可中断、难调试，已不推荐。图的每个节点都能打断点、能改状态、能持久化。
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from tools import TOOLS, model  # 阶段 8 的工具与已 bind_tools 的模型

SYSTEM = SystemMessage(
    "你是喵星速递的客服助手。涉及公司政策必须先用 search_policy 查证再回答，"
    "不要凭印象作答；需要算数就用工具算，不要心算。"
)


def agent(state: MessagesState) -> dict:
    """决策节点：看完整历史，决定「继续调工具」还是「给出答案」。

    system 提示每次现拼在最前面，而不是存进 state——它是固定指令，
    没必要跟着消息历史一起被 checkpointer 存 N 份。
    """
    return {"messages": model.invoke([SYSTEM] + state["messages"])}


builder = StateGraph(MessagesState)
builder.add_node(agent)
builder.add_node("tools", ToolNode(TOOLS))  # 执行 tool_calls，结果自动包成 ToolMessage
builder.add_edge(START, "agent")
# 条件边：tools_condition 看最后一条消息有没有 tool_calls，有就去 "tools"，没有就 END。
builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
# 关键的那条回边：工具跑完不结束，回到 agent 让它看着结果再决定 —— 环由此形成。
builder.add_edge("tools", "agent")

# 挂 checkpointer（阶段 5 同款）：同一个 thread_id 的多轮对话共享消息历史。
graph = builder.compile(checkpointer=InMemorySaver())


def ask(text: str, thread_id: str = "demo") -> list:
    """问一句，返回本轮新增的消息（含中间的 tool_call / ToolMessage，便于观察循环）。"""
    config = {"configurable": {"thread_id": thread_id}}
    before = len(graph.get_state(config).values.get("messages", []))
    result = graph.invoke({"messages": [HumanMessage(text)]}, config=config)
    return result["messages"][before:]


def show(messages: list) -> None:
    """把一轮里的每一跳打出来：模型要调什么、工具返回了什么、最后答了什么。"""
    for m in messages:
        if getattr(m, "tool_calls", None):
            for c in m.tool_calls:
                print(f"  [调用] {c['name']}({c['args']})")
        elif m.type == "tool":
            print(f"  [结果] {m.content[:60].replace(chr(10), ' ')}…")
        elif m.type == "ai" and m.content:
            print(f"  [答] {m.content}")


if __name__ == "__main__":
    # 第 1 轮：一个问题需要**两类**工具（先查政策拿到折扣，再算钱）——
    # 调几次、什么顺序，全由模型看着上一步结果决定，代码里没有任何编排。
    print("【第1轮】黑金会员买 288 元的猫粮，按会员折扣要付多少？")
    show(ask("黑金会员买 288 元的猫粮，按会员折扣要付多少？"))

    # 第 2 轮：只说「那普通会员呢」，没重复上下文 —— 靠 checkpointer 记忆接住。
    print("\n【第2轮】那普通会员呢？")
    show(ask("那普通会员呢？"))

    # —— 自检：测图的结构与循环语义，尽量不依赖模型措辞 ——
    # 1) 环确实存在：tools 回指 agent。没有这条边就退化成阶段 8 之前的单向链。
    edges = {(e[0], e[1]) for e in graph.get_graph().edges if not e[1] == "__end__"}
    assert ("tools", "agent") in edges, f"缺少回边，图不成环：{edges}"
    # 2) 路由语义：有 tool_calls 去 tools，没有就 END —— Agent 何时收工的判据。
    from langchain_core.messages import AIMessage
    calling = AIMessage("", tool_calls=[{"name": "add", "args": {"a": 1, "b": 2}, "id": "x"}])
    assert tools_condition({"messages": [calling]}) == "tools"
    assert tools_condition({"messages": [AIMessage("答完了")]}) == END
    # 3) 真跑一圈：算术问题必须**经过** tools 节点，而不是模型心算。
    msgs = ask("1234.5 加 8765.5 是多少？", thread_id="check")
    assert any(m.type == "tool" for m in msgs), "该走工具节点，实际没调"
    assert "10000" in msgs[-1].content, f"工具结果没被用上：{msgs[-1].content}"
    # 4) 记忆隔离（阶段 5 语义仍在）：新 thread 不带旧上下文。
    fresh = graph.get_state({"configurable": {"thread_id": "empty"}}).values
    assert not fresh.get("messages"), "新 thread 不该有历史"
    print("\n[self-check] 图成环、路由正确、工具真被执行、thread 隔离 ✓")

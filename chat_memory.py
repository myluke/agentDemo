"""记忆 / 多轮对话演示：让链记住上一轮说过什么。

多轮记忆的本质，阶段 2 那节「为什么不用 ai 消息」已经埋了伏笔：
把过去的 human/ai 消息作为**消息**再喂回模型，模型才有上下文。

本阶段例外用 **LangGraph**（阶段 8 才正式讲），原因见 ROADMAP：
LCEL 里干这件事的 `RunnableWithMessageHistory` 已被官方弃用并指向 LangGraph，
core 里没有未弃用的替代。这里只借它一件事——用 checkpointer 按 thread_id
存取消息历史，**不碰**循环/工具/自主决策（那些留到阶段 8）。

关键三件套：
- MessagesState：内置 add_messages reducer，节点返回的消息自动累加进历史。
- checkpointer（InMemorySaver）：每轮结束把状态存下来，下一轮自动读回。
- thread_id：不同 thread_id 各自独立记忆，互不串（多用户/多会话隔离）。
"""
import os

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

# 与前四个 demo 同款：走自定义网关，不用官方骨架里的 init_chat_model。
model = ChatAnthropic(
    model="claude-opus-4-8",
    max_tokens=1024,
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)


def call_model(state: MessagesState) -> dict:
    """唯一的节点：把到目前为止累计的所有消息喂给模型，返回它的回复。

    state["messages"] 是这个 thread 的完整历史（含本轮新问题）；
    返回的 {"messages": ...} 会被 add_messages reducer 追加进历史。
    """
    return {"messages": model.invoke(state["messages"])}


# 一个最小的状态图：START → call_model。图只跑一步，不循环——
# 循环、条件跳转是阶段 8 的内容，这里只要「带记忆的一步」。
builder = StateGraph(MessagesState)
builder.add_node(call_model)
builder.add_edge(START, "call_model")

# compile 时挂上 checkpointer，图才有记忆：每次 invoke 结束存状态，
# 下次同 thread_id invoke 时自动把历史读回来接着走。
graph = builder.compile(checkpointer=InMemorySaver())


def ask(text: str, thread_id: str) -> str:
    """向指定 thread 发一句话，返回模型回复。thread_id 决定用哪份记忆。"""
    result = graph.invoke(
        {"messages": [HumanMessage(text)]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["messages"][-1].content


def history_of(thread_id: str) -> list:
    """读某个 thread 当前存下来的完整消息历史。"""
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    return state.values.get("messages", [])


if __name__ == "__main__":
    # 线程 A：连说两轮，第二轮问名字——记忆生效则答得出 Luke。
    print("【线程 A · 第1轮】我叫 Luke。")
    print("  →", ask("我叫 Luke，请记住。", thread_id="A"))
    print("【线程 A · 第2轮】我叫什么？")
    a2 = ask("我叫什么名字？", thread_id="A")
    print("  →", a2)

    # 线程 B：全新记忆，同样问名字——隔离生效则答不出 Luke。
    print("\n【线程 B · 第1轮】我叫什么？（B 从没听过 Luke）")
    b1 = ask("我叫什么名字？", thread_id="B")
    print("  →", b1)

    # —— 自检：测的是 checkpointer 存取与 thread 隔离机制，不靠模型措辞 ——
    # 线程 A 跑了两轮 = 2×(human+ai) = 4 条消息累计在它自己的历史里。
    assert len(history_of("A")) == 4, f"线程 A 历史应有 4 条，实得 {len(history_of('A'))}"
    # 线程 B 只跑了一轮 = human+ai = 2 条，且它的历史里不该出现线程 A 的 "Luke"。
    assert len(history_of("B")) == 2, f"线程 B 历史应有 2 条，实得 {len(history_of('B'))}"
    b_text = "".join(m.content for m in history_of("B") if isinstance(m.content, str))
    assert "Luke" not in b_text, "线程 B 不该知道线程 A 的名字（thread 未隔离）"
    print("\n[self-check] 记忆累加 + thread 隔离通过 ✓")

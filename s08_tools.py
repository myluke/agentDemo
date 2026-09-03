"""工具调用（function calling）演示：模型自己决定要不要调工具、调哪个、传什么参。

前七阶段模型只能吐字。工具调用补的是「动手」：你把函数的**签名和用途**告诉模型，
模型在回答前先返回一个 `tool_call`（函数名 + 参数），你执行它，再把结果喂回去。

注意模型**不会**执行任何代码——它只填了张调用单：
  1) 你 bind_tools 把函数 schema 一起发过去；
  2) 模型回一条 AIMessage，content 为空，tool_calls 里写着调谁、传什么；
  3) **你的代码**执行函数，把结果包成 ToolMessage（带上 tool_call_id）；
  4) 再 invoke 一次，模型看着结果说人话。

第 3、4 步的手动循环就是阶段 9 Agent 里那个自动循环——这里手写一遍，
看清每一跳的消息长什么样，阶段 9 再交给 LangGraph 自动转。

关键点：
- `@tool` 装饰器：函数名 → 工具名，类型注解 → 参数 schema，docstring → 用途说明。
  **docstring 是模型选工具的唯一依据**，写清楚比什么都重要。
- 工具不一定是计算：`search_policy` 直接复用阶段 6 的 retriever，把 RAG 变成
  「模型想查才查」，而不是每问必检索。
"""
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

from llm import openai_chat
from s06_rag_basic import format_docs, retriever  # 阶段 6 的检索器，原样当工具用


@tool
def add(a: float, b: float) -> float:
    """计算两个数相加的结果。"""
    return a + b


@tool
def exchange(amount: float, rate: float) -> float:
    """按给定汇率把金额换算成另一种货币：amount * rate。"""
    return amount * rate


@tool
def search_policy(query: str) -> str:
    """查询喵星速递的会员、退货、退款、客服政策条款。问到公司规定时用这个。"""
    return format_docs(retriever.invoke(query))


TOOLS = [add, exchange, search_policy]
BY_NAME = {t.name: t for t in TOOLS}

# bind_tools 把工具 schema 挂到每次请求上。模型仍可以直接回话（不调工具），
# 调不调是它看着 docstring 自己判断的——这正是与「你写死流程」的分界。
model = openai_chat(max_tokens=1024).bind_tools(TOOLS)


def run(question: str, max_turns: int = 5) -> str:
    """手写的「模型说要调 → 我执行 → 结果回灌」循环，直到模型不再要求调工具。

    max_turns 是安全阀：模型可能反复要求调工具（真实场景里工具报错就容易这样），
    没有上限就是无限循环烧 token。阶段 9 的 Agent 也需要同样的护栏。
    """
    messages = [HumanMessage(question)]
    for _ in range(max_turns):
        ai = model.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:  # 模型不再要工具 = 收工，content 就是最终答案
            return ai.content
        for call in ai.tool_calls:
            print(f"  [调用] {call['name']}({call['args']})")
            # 一次可能返回多个 tool_call（并行调用），每个都要回一条 ToolMessage，
            # 且 tool_call_id 必须对上——模型靠它把结果和调用单配对。
            result = BY_NAME[call["name"]].invoke(call["args"])
            messages.append(ToolMessage(str(result), tool_call_id=call["id"]))
    raise RuntimeError(f"{max_turns} 轮仍未收敛")


if __name__ == "__main__":
    for q in [
        "1234.5 加 8765.5 是多少？",
        "会员到期后数据保留多久？",
        "你好，你是谁？",  # 闲聊，不该调任何工具
    ]:
        print(f"【问】{q}")
        print(f"【答】{run(q)}\n")

    # —— 自检：测「模型是否选对工具」，只跑到第一跳，不等完整回答 ——
    # 1) 算术问题 → 选 add，参数解析正确。
    call = model.invoke([HumanMessage("100 加 23 等于几？")]).tool_calls
    assert call and call[0]["name"] == "add", f"算术该选 add，实得 {call}"
    assert {call[0]["args"]["a"], call[0]["args"]["b"]} == {100, 23}, call[0]["args"]
    # 2) 政策问题 → 选 search_policy（靠 docstring 区分，不是靠关键词写死）。
    call = model.invoke([HumanMessage("拆封的猫粮能退吗？")]).tool_calls
    assert call and call[0]["name"] == "search_policy", f"政策该选 search_policy，实得 {call}"
    # 3) 闲聊 → 一个工具都不调，说明「调不调」确实是模型在判断。
    assert not model.invoke([HumanMessage("你好呀")]).tool_calls, "闲聊不该调工具"
    # 4) 工具本身是普通函数，脱离模型也能直接调（可单测、可复用）。
    assert add.invoke({"a": 1, "b": 2}) == 3
    print("[self-check] 选工具/传参/不该调时不调 ✓")

# 阶段 8 · 工具调用（function calling）— 回顾笔记

配套代码：[`tools.py`](../tools.py)

---

## 一句话机制

**你把函数的签名和用途告诉模型，模型在回答前先返回一张「调用单」
（函数名 + 参数），你的代码执行它，再把结果喂回去。**

前七阶段模型只能吐字。工具调用补的是「动手」——查数据库、算数、发请求、
调内部 API。

## 最大的误解：模型不执行任何代码

模型**只填了张单子**。执行是你的事。完整四跳：

```text
1) 你：bind_tools 把工具 schema 随请求一起发过去
2) 模型：回一条 AIMessage，content 为空，tool_calls=[{name, args, id}]
3) 你：执行函数，结果包成 ToolMessage(内容, tool_call_id=同一个 id)
4) 你：带着全部历史再 invoke 一次，模型看着结果说人话
```

第 3、4 步就是 demo 里 `run()` 那个 for 循环。**这个循环就是 Agent 的全部**——
阶段 9 只是把它交给 LangGraph 自动转。先手写一遍看清每一跳的消息形状，
阶段 9 换成 `ToolNode` 时才知道预制件替掉的是哪几行。

## `@tool`：三样东西喂给模型

```python
@tool
def search_policy(query: str) -> str:
    """查询喵星速递的会员、退货、退款、客服政策条款。问到公司规定时用这个。"""
    return format_docs(retriever.invoke(query))
```

| 代码里的 | 模型看到的 |
|---|---|
| 函数名 | 工具名 |
| 类型注解 `query: str` | 参数 schema（类型、必填与否） |
| **docstring** | **这个工具是干什么的、什么时候用** |

**docstring 是模型选工具的唯一依据**。写得含糊，模型就选错工具或该调时不调。
这是本阶段唯一需要"调"的东西——比任何提示词技巧都重要。

## 工具不一定是计算

`search_policy` 直接复用阶段 6 的 retriever。这一句 import 把 RAG 从
**「每问必检索」变成「模型想查才查」**：

- 阶段 6 的链：问什么都先跑一遍检索，闲聊也检索，浪费且稀释。
- 变成工具后：模型判断「这问的是政策」才调，问「你好」就直接答。

判断权从你的代码转移到了模型——这是通往 Agent 的关键一步。

## `max_turns` 不是可选装饰

```python
def run(question: str, max_turns: int = 5) -> str:
    for _ in range(max_turns):
        ...
    raise RuntimeError(f"{max_turns} 轮仍未收敛")
```

模型可能反复要求调工具——工具报错、结果不符合预期时尤其容易。
没有上限就是无限循环烧 token。阶段 9 的图靠 `recursion_limit`（默认 25）
做同一件事。**任何自主循环都要有护栏。**

## `tool_call_id` 必须对上

一次响应可能带**多个** tool_call（并行调用）：

```python
for call in ai.tool_calls:
    result = BY_NAME[call["name"]].invoke(call["args"])
    messages.append(ToolMessage(str(result), tool_call_id=call["id"]))
```

每个 tool_call 都要回一条 ToolMessage，模型靠 `id` 把结果和调用单配对。
漏一条、id 对不上，下一跳就报错。

## 消息历史必须完整回传

`messages` 里要依次留着：HumanMessage → AIMessage(带 tool_calls) →
ToolMessage → ...。少了中间的 AIMessage，模型就不知道这个 ToolMessage
在回应什么。这也是为什么 `run()` 里每一步都 `messages.append(...)`。

## 工具仍是普通函数

```python
assert add.invoke({"a": 1, "b": 2}) == 3
```

`@tool` 包了一层，但业务逻辑还是可以脱离模型直接调、直接单测。
**别把模型调用混进工具实现里**——工具应该是确定性的，不确定性留在模型那侧。

## 自检怎么测

测「模型是否选对工具」，只跑到**第一跳**，不等完整回答（省时省钱）：

```python
call = model.invoke([HumanMessage("100 加 23 等于几？")]).tool_calls
assert call[0]["name"] == "add"
assert not model.invoke([HumanMessage("你好呀")]).tool_calls   # 闲聊不该调
```

第三条最有价值：**闲聊时一个工具都不调**，证明「调不调」确实是模型在判断，
而不是你写死的关键词匹配。

## 和阶段 9 的关系

阶段 9 把 `run()` 里的 for 循环换成状态图：

| 阶段 8 手写 | 阶段 9 预制件 |
|---|---|
| `if not ai.tool_calls: return` | `tools_condition` 条件边 |
| `for call in ai.tool_calls: ...append(ToolMessage)` | `ToolNode(TOOLS)` |
| `for _ in range(max_turns)` | 图的回边 + `recursion_limit` |

工具本身、模型本身**原样复用**——`agent_graph.py` 直接
`from tools import TOOLS, model`。

---

**一句话**：工具调用 = 模型填调用单、你执行、结果回灌；docstring 决定它选不选、
选哪个，`tool_call_id` 决定结果能不能对上，`max_turns` 决定它不会无限转。

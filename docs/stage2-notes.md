# 阶段 2 · 顺序链 — 回顾笔记

配套代码：[`s02_multi_step_chain.py`](../s02_multi_step_chain.py)

---

## 核心：上一步的输出，自动喂给下一步

流程：话题 → **[第1步]** 生成一个观点 → **[第2步]** 反驳这个观点。
关键点：第 2 步的输入依赖第 1 步的输出；一次普通 API 请求只能完成其中一步，多步得靠链把它们串起来。

## `RunnablePassthrough.assign` 是怎么串的

```python
full_chain = (
    RunnablePassthrough.assign(opinion=step1_argue)    # 跑 step1，结果存进 "opinion"
    | RunnablePassthrough.assign(rebuttal=step2_rebut) # 读 "opinion" 跑 step2，结果存进 "rebuttal"
)
```

`.assign(key=子链)` 的语义：**在原有输入字典基础上，跑一遍子链，把结果加到 `key` 字段，其余字段原样保留**。所以字典像滚雪球一样越滚越大：

| 阶段 | 字典内容 |
|---|---|
| 输入 | `{"topic": ...}` |
| 第 1 个 assign 后 | `{"topic": ..., "opinion": 第1步结果}` |
| 第 2 个 assign 后 | `{"topic": ..., "opinion": ..., "rebuttal": 第2步结果}` |

第 2 步的模板 `"对方观点是：{opinion}。"` 能直接取到第 1 步塞进去的 `opinion`——这就是「前一步输出成为后一步输入」。

## 每个子链自己也是一条 LCEL 链

```python
step1_argue = ChatPromptTemplate.from_messages([...]) | model | StrOutputParser()
```

`StrOutputParser()` 在这里是必须的：抠成纯字符串，下一步的模板才能把它当普通文本填进 `{opinion}`。少了它，传下去的是 `AIMessage` 对象，模板填充会出问题。

## 为什么只 `invoke` 一次

```python
result = full_chain.invoke({"topic": topic})  # 只调一次完整链
```

完整链只调用一次，内部会**依次**产生两次模型请求。好处：避免为了打印第 1 步结果而把它单独重复调一遍——中间输出已经存在字典里，直接 `result['opinion']` 取。

## 为什么这里不用 `ai` 消息（易混点）

容易和「多轮对话」搞混：既然第 2 步要用第 1 步的结果，为什么不把第 1 步的观点作为 `("ai", ...)` 历史消息发回去？因为**多步链**和**多轮对话**是两套不同机制。

- **阶段 2 传的是「数据」**：第 1 步的文本结果被存进字典的 `opinion`，再作为**普通字符串**填进第 2 步的 `human` 模板 `"对方观点是：{opinion}。请反驳。"`。对第 2 步的模型来说，这就是一次**全新的单轮提问**，它根本不知道有「第 1 步」存在。
- **`ai` 消息传的是「对话历史」**：把模型之前说过的话，在同一次请求里一起发回去，让这次生成能看到前文、保持记忆——那是**多轮对话**，阶段 5 `s05_chat_memory.py` 才做。

| | 阶段 2 多步链 | 阶段 5 多轮对话 |
|---|---|---|
| 上一步结果怎么传 | 填进下一步的 `human` 模板文本 | 作为 `ai` 历史消息发回 |
| 第 2 次请求看得到第 1 次吗 | 看不到，独立单轮 | 看得到，带完整历史 |
| 靠什么机制 | `assign` 存字典 + 模板填充 | `MessagesPlaceholder` 累积消息列表 |
| 模型视角 | 「这是个全新问题」 | 「我们在连续对话」 |

一句话：阶段 2 需要的是**把上一步的产出当新输入**，不是**让模型记住之前说过什么**，所以 `human` 模板变量就够了，`ai` 消息用不上。

---

## 边界

- 输入必须含 `topic`；输出含 `topic`、`opinion`、`rebuttal` 三个键。
- 两步**串行**、第 2 步依赖第 1 步；任一步失败整条链失败。
- 这是**固定流程的 workflow**，步骤写死；不是会自主选步骤/工具的 Agent（那是阶段 9）。

---

**一句话**：`RunnablePassthrough.assign` 让链一边跑子步骤、一边把结果累积进同一个字典，实现「上一步喂下一步」的顺序编排。

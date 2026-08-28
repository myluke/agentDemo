# 阶段 1 · LCEL 基础 — 回顾笔记

配套代码：[`hello.py`](../hello.py)

---

## 核心：一条 LCEL 链 `prompt | model | parser`

```python
chain = (
    ChatPromptTemplate.from_messages([
        ("system", "你是一个简洁的助手，用一句话回答。"),
        ("human", "{question}"),
    ])
    | model
    | StrOutputParser()
)
chain.invoke({"question": "..."})
```

`|` 就是 LCEL（LangChain Expression Language）的管道运算符。数据从左往右流：**套模板 → 交给模型 → 抠成纯字符串**。三个组件各司其职，用 `|` 拼成一个可 `invoke` 的整体。

## 三个组件

| 组件 | 干什么 | 输入 → 输出 |
|---|---|---|
| `ChatPromptTemplate` | 把 `{question}` 填进对话模板 | dict → 消息列表 |
| `model`（`ChatAnthropic`） | 调 Claude 生成回复 | 消息列表 → `AIMessage` |
| `StrOutputParser` | 从消息对象里抠出纯文本 | `AIMessage` → str |

没有 `StrOutputParser` 时，`chain.invoke` 返回的是 `AIMessage` 对象，得自己 `.content`；加上它，直接拿到字符串。

## 模型客户端 & 凭证

```python
model = ChatAnthropic(
    model="claude-opus-4-8",
    max_tokens=1024,
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)
```

- `api_key`：优先读自定义网关的 `ANTHROPIC_AUTH_TOKEN`，缺失才退回官方 `ANTHROPIC_API_KEY`。
- `base_url`：指向自定义网关，不是 Anthropic 默认地址。两者都从环境变量读，仓库里没有 `.env`。

## 易踩点

- `if __name__ == "__main__":` 包住执行代码——被 `import` 时不触发模型调用，只有直接 `python hello.py` 才跑。
- `{question}` 是模板占位符，`invoke` 时用 dict 的键去填，键名必须对上。

---

**一句话**：LCEL 用 `|` 把「提示词 → 模型 → 解析器」串成一条可调用的链，这是后续所有 demo 的地基。

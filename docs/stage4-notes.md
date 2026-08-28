# 阶段 4 · 并行 & 分支 — 回顾笔记

配套代码：[`parallel_branch.py`](../parallel_branch.py)

---

## 核心：先并发抽取，再按结果分流

一条用户反馈同时做两项互不依赖的判断：**情绪**和**类别**；两项都完成后，再按类别选择回复策略。

```python
analyze = RunnableParallel(
    sentiment=sentiment_chain,
    category=category_chain,
    feedback=itemgetter("feedback"),
)

route = RunnableBranch(
    (lambda x: x["category"] == "投诉", complaint_reply),
    (lambda x: x["category"] == "咨询", inquiry_reply),
    fallback_reply,
)

full_chain = analyze | RunnablePassthrough.assign(reply=route)
```

## `RunnableParallel`：并发执行，合并成字典

传给 `RunnableParallel` 的每个键对应一条子链。所有子链收到同一份原始输入，并发执行后按键名合并结果：

```python
{"feedback": "App 又崩了"}
# analyze 输出
{
    "sentiment": "负面",
    "category": "投诉",
    "feedback": "App 又崩了",
}
```

情绪判断和类别判断互不依赖，适合并发；若串行执行，请求耗时约为两者相加，并发时则接近较慢的那个。后面的回复依赖分析结果，不能和它们并发。

### `itemgetter("feedback")` 的坑

`RunnableParallel` 的每条子链都收到完整输入字典。要把原文保留到输出里，需明确取出字符串：

```python
feedback=itemgetter("feedback")
```

若写 `feedback=RunnablePassthrough()`，得到的会是整个输入字典：

```python
{"feedback": {"feedback": "App 又崩了"}}
```

后续模板中的 `{feedback}` 就会看到字典文本，而不是原文。

## `RunnableBranch`：首个命中，否则兜底

构造格式是若干个 `(条件, 分支)`，最后放一条不带条件的兜底分支：

```python
RunnableBranch(
    (条件1, 分支1),
    (条件2, 分支2),
    兜底分支,
)
```

条件函数收到完整的分析结果字典，并按书写顺序检查；**第一个返回 `True` 的分支执行，后面不再检查**。条件可能重叠时，顺序就是业务规则。全不命中则执行兜底。

分类器使用阶段 3 的 `with_structured_output`：`Sentiment` 和 `Category` 的
`label` 字段分别用 `Literal` 枚举限定合法值，并显式使用网关支持的
`method="function_calling"`。这样分类结果会先经过 Pydantic 校验，再映射为标签字符串；
模型即使被要求只回一个词，也不会把 `"投诉。"` 或 `"类别：投诉"` 这类表外格式传给路由。
因此下游可以安全使用 `x["category"] == "投诉"` 精确比较。结构化输出解决的是格式和取值契约，
不保证模型对含糊反馈的业务判断永远正确；语义质量仍与模型能力和提示词有关。

### 按任务选择模型

回复链需要生成自然语言，因此使用能力更强的 Opus；情绪和类别链只需判断并返回一个
枚举标签，使用 Haiku 即可：

```python
model = ChatAnthropic(model="claude-opus-4-8", **_creds)  # reply 使用
fast = ChatAnthropic(model="claude-haiku-4-5", **_creds)   # 两个分类器使用
```

`classifier()` 内部调用 `fast.with_structured_output(...)`，`reply()` 内部仍调用
`model`。这不是说 Haiku 一定不会判断错：结构化输出只保证格式和取值合法，语义判断
仍受模型能力、提示词和输入质量影响；这里只是把能力和成本匹配到任务难度。

## 整链数据流

| 阶段 | 数据 |
|---|---|
| 输入 | `{"feedback": 原文}` |
| `analyze` 后 | `{"sentiment": 情绪, "category": 类别, "feedback": 原文}` |
| `assign(reply=route)` 后 | 保留以上三项，再增加 `"reply"` |

这里用 `.assign` 而不是直接 `analyze | route`：后者只返回回复字符串，会丢掉并行阶段的情绪和类别；前者把分支结果追加到同一个字典，便于观察和继续编排。

## 和普通 `if`、Agent 的边界

- **普通 `if`**：少量本地 Python 逻辑时更直接；无需为了框架而用 `RunnableBranch`。
- **`RunnableBranch`**：适合分支本身也是 Runnable、需要继续接入 LCEL 链的固定流程；路由规则仍由代码写死。
- **Agent**：由模型根据目标和上下文自主决定下一步或调用什么工具。这里没有自主决策，只是确定性的 workflow，不是 Agent。

## `|` 到底是什么

`|` 本是 Python 的按位或运算符，LangChain 在 `Runnable` 基类里重载了 `__or__`，
把它变成「管道」：**左边的输出原样作为右边的输入**，心智模型和 shell 的
`cat a.txt | grep x | wc -l` 一致。

```python
chain = prompt | model | parser
# 等价于 prompt.__or__(model).__or__(parser)
# 实际构造出 RunnableSequence(prompt, model, parser)

chain.invoke({"topic": "猫"})
# 1. prompt.invoke({"topic": "猫"}) → PromptValue
# 2. model.invoke(PromptValue)      → AIMessage
# 3. parser.invoke(AIMessage)       → str
```

重载大致是这样，关键在 `coerce_to_runnable`：

```python
class Runnable:
    def __or__(self, other):
        return RunnableSequence(self, coerce_to_runnable(other))
```

它会把右边的普通对象自动转成 Runnable，所以链里可以直接写函数和字典：

| 写法 | 自动变成 |
|---|---|
| `chain \| some_function` | `RunnableLambda(some_function)` |
| `chain \| {"a": c1, "b": c2}` | `RunnableParallel(a=c1, b=c2)` |
| `chain \| runnable` | 原样使用 |

因此本阶段的 `analyze | RunnablePassthrough.assign(reply=route)`
就是 `RunnableSequence(analyze, RunnablePassthrough.assign(reply=route))` 的语法糖。

### 坑：左边必须是 Runnable

`__or__` 定义在 `Runnable` 上，所以纯 dict 开头会失败：

```python
{"a": chain1} | chain2      # ✗ TypeError，dict 不认识 | Runnable
chain0 | {"a": chain1}      # ✓ 左边是 Runnable，右边被 coerce
```

要以 dict 开头就显式包一层：`RunnableParallel(a=chain1) | chain2`。

## Runnable 家族速查

先纠正一个常见误解：`RunnableParallel` / `RunnableBranch` / `RunnablePassthrough`
**不是函数，是 LangChain 的 Runnable 类**（LCEL 组件），实例化后靠 `|` 组装成链。

| 组件 | 作用 | 一句话 |
|---|---|---|
| `RunnableParallel` | 并发跑多个分支，结果合并成一个 dict | 扇出：一份输入 → 多个 key 同时算 |
| `RunnableBranch` | 按条件选一条链走（if/elif/else） | 路由：第一个命中的条件决定走哪条链 |
| `RunnablePassthrough` | 原样透传输入，或用 `.assign()` 往 dict 里追加字段 | 搬运：不改数据，只透传或追加 |

```python
# RunnableParallel —— 两种等价写法
chain = RunnableParallel(joke=chain1, poem=chain2)
chain = {"joke": chain1, "poem": chain2}        # dict 字面量会自动转成 Parallel
# 输入 x → {"joke": chain1(x), "poem": chain2(x)}

# RunnablePassthrough.assign —— 保留原输入，再加一个字段
chain = RunnablePassthrough.assign(context=retriever)
# {"q": "..."} → {"q": "...", "context": retriever({"q": "..."})}

# RunnableBranch —— (条件, 链) 元组列表 + 兜底
chain = RunnableBranch(
    (lambda x: "code" in x["topic"], code_chain),
    (lambda x: "math" in x["topic"], math_chain),
    default_chain,   # 都不匹配走这条
)
```

### 还有哪些 Runnable

**常用（LCEL 必备）**

- `RunnableSequence` —— `|` 管道的底层，串联。写 `a | b` 就是在造它。
- `RunnableLambda` —— 把普通函数塞进链里，如 `RunnableLambda(lambda x: x.upper())`。
- `RunnablePassthrough` / `RunnableParallel` / `RunnableBranch` —— 本阶段这三个。

**次常用**

- `RunnableConfig` —— 不是链，是调用时的配置（`callbacks` / `tags` / `max_concurrency`）。
- `RunnableWithFallbacks` —— `.with_fallbacks([...])`，主链失败时切备用链。
- `RunnableWithMessageHistory` —— 给链加对话记忆，多轮聊天用。
- `RunnableBinding` —— `.bind()` / `.with_config()` 的底层，预先固定部分参数。

**少用 / 进阶**

- `RunnableRetry` —— `.with_retry()`，失败重试。
- `RunnableGenerator` —— 流式生成器场景。
- `RunnableEach` —— 对列表里每个元素跑同一条链。
- `DynamicRunnable` —— `.configurable_fields()` / `.configurable_alternatives()`，运行时切换模型或参数。

日常大约九成场景只会用到「常用」那几个，而且多半不用手写类名：`|`、dict 字面量、
`.assign()`、`.bind()` 这些语法糖会自动构造对应的 Runnable。

---

**一句话**：`RunnableParallel` 并发完成互不依赖的步骤并合并字典，`RunnableBranch` 再按字典里的结果执行第一个命中的固定分支。

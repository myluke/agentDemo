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

分类结果先经过 `.strip()` 去掉首尾空白和换行，避免 `"投诉\n"` 在精确比较时误走兜底。这里有意不解析同义词或标点：分类器契约仍是只返回指定标签，若模型返回 `"投诉。"`，会走兜底。

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

---

**一句话**：`RunnableParallel` 并发完成互不依赖的步骤并合并字典，`RunnableBranch` 再按字典里的结果执行第一个命中的固定分支。

# 阶段 3 · 结构化输出 — 回顾笔记

配套代码：[`structured_output.py`](../structured_output.py)

---

## 1. `__main__` 里的两行 `assert` 是测试用例吗？

```python
assert job2.min_salary_k is None, f"未提薪资应为 None，实得 {job2.min_salary_k}"
assert job2.remote is False, f"现场办公 remote 应为 False，实得 {job2.remote}"
```

算，但不是 pytest 那种正式测试，而是内嵌在 `__main__` 里的**轻量自检（self-check）**。

- **不是独立测试文件**：没有框架，不会被测试运行器自动收集；只在手动 `python structured_output.py` 跑 demo 时顺带执行一次。
- **作用**：守住核心契约——「可选字段在原文没提到时必须留空，而不是被模型编造」。拿一段没写薪资、明说现场办公的文本，断言 `min_salary_k is None`、`remote is False`。逻辑退化成乱填时会立刻 `AssertionError`，而不是静默返回错数据。
- **局限**：依赖真实模型调用，不是确定性单测，模型某次抽取抖动理论上也可能触发。对教学 demo「跑一次能自证核心行为没坏」已足够，不值得为它搭 mock 和框架。
- **何时升级**：真要进 CI，才拆成 `test_*.py` + mock 模型响应。

---

## 2. `("human", "{posting}")` 里的 `"human"` 是什么？

是 LangChain 预定义的**角色标识字符串**，不是随便起的名字。

`ChatPromptTemplate.from_messages` 收 `(角色, 内容)` 元组列表，第一个元素只能从这组角色里选：

| 字符串 | 映射到的消息类 | 含义 |
|---|---|---|
| `"system"` | `SystemMessage` | 系统指令，设定模型身份/规则 |
| `"human"` / `"user"` | `HumanMessage` | 用户输入（两者别名，等价） |
| `"ai"` / `"assistant"` | `AIMessage` | 模型回复（多轮时放历史回答） |
| `"placeholder"` | `MessagesPlaceholder` | 占位，运行时插入一段消息列表（阶段 5「记忆」会用到） |

底层等价关系：

```python
("system", "...")  ≈  SystemMessage(content="...")
("human", "...")   ≈  HumanMessage(content="...")
```

- **为什么用字符串**：省事，`from_messages` 帮你把 `"human"` 翻译成 `HumanMessage`；元组写法是简写，等价于直接构造消息类。
- **易踩点**：`"human"`/`"user"` 通、`"ai"`/`"assistant"` 通，但别自己发明角色（如 `"customer"`）会报错。这套角色名对应聊天模型 API 的固定协议，不是自由文本。

---

---

## 3. 怎么打印 AI 返回的完整内容？

分两层，别混。

**解析后的对象** —— Pydantic 自带：

```python
print(job.model_dump_json(indent=2))
```

**解析前的原始消息** —— 给 `with_structured_output` 加 `include_raw=True`：

```python
model.with_structured_output(JobPosting, method="function_calling", include_raw=True)
```

返回从 `JobPosting` 实例变成字典，三个键：

| 键 | 内容 |
|---|---|
| `parsed` | 解析后的 `JobPosting`，解析失败时为 `None` |
| `raw` | 解析前的完整 `AIMessage` |
| `parsing_error` | 解析异常，成功时为 `None` |

注意 `raw.content` 在 `function_calling` 下不是文本，而是 `tool_use` 块——结构化结果在
`raw.tool_calls[0]["args"]`（或底层 `raw.content[0]["input"]`），两者内容相同，业务代码用前者。

---

## 4. `raw` 是模型返回的原始数据吗？

**不是。** 它是 LangChain 标准化后的 `AIMessage`，不是 HTTP 响应的原始 JSON。

```text
网关原始 HTTP JSON
      ↓ ChatAnthropic 转换
LangChain AIMessage        ← include_raw=True 看到的是这层
      ↓ with_structured_output 解析
JobPosting 对象
```

`raw` 里三类数据的来源：

- `content`：尽量保留模型返回的内容块，但已转成 LangChain 结构。
- `tool_calls`：LangChain 从 `content` 提取出的统一格式，所以看起来和 `content` 重复。
- `response_metadata` / `usage_metadata`：整理后的模型标识、停止原因、token 用量。

本机实测响应里有个值得注意的细节：

```json
"model": "gpt-5.6-sol",
"model_provider": "anthropic"
```

说明自定义 `ANTHROPIC_BASE_URL` 网关实际转发到了别的模型，但仍按 Anthropic 协议应答，所以
`ChatAnthropic` 能正常适配。这也解释了为什么原生 `json_schema` 在这里不兑现约束。

---

## 5. 怎么看到更底层的请求？

设环境变量即可，SDK 自带（`structured_output.py` 已用 `os.environ.setdefault` 固化）：

```python
os.environ.setdefault("ANTHROPIC_LOG", "debug")
```

或临时开，不改代码：

```bash
ANTHROPIC_LOG=debug .venv/bin/python structured_output.py
```

实测输出（删节）：

```text
DEBUG Request options: {'method': 'post', 'url': '/v1/messages',
  'json_data': {'max_tokens': 1024, 'model': 'claude-opus-4-8',
   'tool_choice': {'type': 'tool', 'name': 'JobPosting'},
   'tools': [{'name': 'JobPosting', 'input_schema': {...}}]}}
DEBUG Sending HTTP Request: POST https://helm.easymeta.au/v1/messages
INFO  HTTP Request: POST ... "HTTP/1.1 200 OK"
DEBUG HTTP Response: ... Headers({'x-helm-request-id': '1df3a1ac-...', ...})
```

能看到三件之前看不到的事：LangChain 把 `JobPosting` 编译成的 `tools` + `tool_choice`
请求体、真实打到的网关地址、网关响应头。

**边界**：debug 日志**不打印响应 body**（只有响应头）。所以「未经 LangChain 处理的原始响应
JSON」这层，SDK 日志给不到，`include_raw` 的 `AIMessage` 已是最接近的东西。真要 wire-level
body 得挂 httpx2 钩子或 mitmproxy，学习目的不值得。

**安全**：请求 body 含业务输入和 schema，会进终端日志，生产别常开。

---

## 6. `method` 有几个？分别干什么？

`ChatAnthropic` 上只有 **2 个**真实选项，外加 1 个会告警的兼容别名。

| method | 底层机制 | 请求体 | 返回落在哪 |
|---|---|---|---|
| `function_calling`（默认） | 强制工具调用 | `tools=[...]` + `tool_choice={"type":"tool","name":"JobPosting"}` | `content` 的 `tool_use` 块 → `tool_calls[0]["args"]` |
| `json_schema` | Claude 原生结构化输出 | `output_config={"format": {...}}` | 普通 text 块，是一段 JSON 文本 |
| `json_mode` | 无（别名） | —— | 告警后转成 `json_schema` |

- `function_calling` 是「借用」工具调用机制骗模型填参数：schema 伪装成一个叫 `JobPosting`
  的工具，`tool_choice` 逼它必须调。这就是为什么 `raw.content` 是 `tool_use` 而非文本。
- `json_schema` 是官方为结构化输出专门做的通道，服务端约束解码，不绕工具。
- `json_mode` 是给从 OpenAI 迁过来的人的兼容垫片，Anthropic 侧没有对应机制，别用。
- 传其他值直接 `ValueError`。

**对本仓库的实际影响**：当前网关（转发到 `gpt-5.6-sol`）不兑现 `output_config.format` 约束，
`json_schema` 会返回自定义中文键导致校验失败。所以这里选 `function_calling` 不是偏好，是唯一能跑的。

**日后会踩的坑**：源码里 `function_calling` + `thinking` 启用时会走特殊分支
（`_get_llm_for_structured_output_when_thinking_is_enabled`）——强制 `tool_choice` 和
extended thinking 不能共存，LangChain 改成非强制并追加提示词。届时模型可能不调工具，解析会失败。

**验证方法**：把 method 换成 `json_schema` 再跑一次，debug 日志里 `tools` 会消失、换成 `output_config`。

---

## 附：本阶段核心要点（一句话）

`model.with_structured_output(Schema)` 让链直接输出经 Pydantic 校验的对象，省掉「提示模型输出 JSON → 手写 `json.loads` → 逐字段校验」。当前自定义网关不兑现 Anthropic 原生 `json_schema`，故显式用 `method="function_calling"`（也是本版本默认值）。

---

## 7. debug 日志里那个 `Request options` 是 Anthropic 官方格式吗？

是。`json_data` 就是 `POST /v1/messages` 的合法请求体，逐字段核对：

| 字段 | 结论 |
|---|---|
| `model` / `max_tokens` / `messages` | 三个必填项齐全，`claude-opus-4-8` 是有效 ID |
| `system` | 顶层字符串形式合法（也可以是 block 数组，用于加 `cache_control`） |
| `tools[].{name, description, input_schema}` | 标准自定义工具定义，`input_schema` 就是原始 JSON Schema |
| `tool_choice: {"type":"tool","name":"JobPosting"}` | 强制调用指定工具，即 §6 的 `function_calling` |
| `min_salary_k` 的 `anyOf + default: null` | Pydantic 生成的 Optional，非 strict 模式下 schema 可自由书写 |

外层的 `files` / `content` / `idempotency_key` / `X-Stainless-*` / `anthropic-user-profile-id`
都是 SDK 内部的 request options，**不会上线**；值为 `<anthropic.Omit object>` 表示「这个 header
不发送」。`idempotency_key` 带 `stainless-python-retry-` 前缀说明这次是 SDK 自动重试
（默认 `max_retries=2`，对 429/5xx/连接错误重试），排错时别误当成 body 格式问题。

可选加固（当前没做，够用就不动）：给 tool 加 `strict: true`（需 schema 带
`additionalProperties: false`）保证 `input` 严格符合 schema；或改用原生 `output_config.format`
——但 §6 已说明本网关不兑现后者。

---

## 8. `max_tokens` 最大能填多少？1M 是什么？

两个数字别混：

| 概念 | Opus 4.8 |
|---|---|
| **上下文窗口**（输入 + 输出总和） | 1M tokens ← 「支持 1M」指的是这个 |
| **`max_tokens`**（单次输出上限） | 最大 **128000** |

同族的 Fable 5 / Opus 5 / Opus 4.7 / 4.6 / Sonnet 5 / Sonnet 4.6 输出上限同为 128K；
Haiku 4.5 上下文只有 200K。

取值实践：

- **非流式**：别超过 ~16000。SDK 默认 10 分钟 HTTP 超时，大输出容易在超时里被截断。
- **要用大值必须流式**：`client.messages.stream(...)` + `.get_final_message()`。
- 本仓库抽取场景 `max_tokens=1024` 足够，调大只是让 `stop_reason: "max_tokens"` 更不可能发生。

**网关注意**：走自定义 `ANTHROPIC_BASE_URL` 时，上限以网关为准（§4 已知实际转发到别的模型）。
用 `client.models.retrieve("claude-opus-4-8")` 确认：返回的 `max_tokens` 是输出上限，
`max_input_tokens` 是上下文窗口（没有 `context_window` 这个字段）。

### 128000 是文件大小还是字符数？

都不是，是 **token 数**。

- 1 token ≈ 3–4 个英文字符，≈ 0.6–1 个汉字（常用汉字多为 1 token，生僻字/标点可能 2–3 个）。
- 128000 tokens 大致 = 40–50 万英文字符，或 8–13 万汉字。
- 与文件字节数无固定关系：同样 1MB，纯 ASCII 与 UTF-8 中文的 token 数差好几倍；PDF/图片另有算法。

要精确计数**别用 tiktoken**（那是 OpenAI 的分词器，数不准，且 Opus 4.7 起换过一次分词器），
用官方接口：

```python
client.messages.count_tokens(
    model="claude-opus-4-8",
    messages=[{"role": "user", "content": text}],
)  # 返回 .input_tokens
```

---

## 9. OpenAI 的请求格式长什么样？两家统一吗？

**不统一。** 结构上同构（都是「消息数组 + 工具定义 + 采样参数」），但字段名、嵌套层级、
返回结构全不一样。而且 OpenAI 自己就有两套并行接口。

### Chat Completions（`POST /v1/chat/completions`，老接口）

```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "你是招聘信息抽取器..."},
    {"role": "user",   "content": "我们招一名高级后端工程师..."}
  ],
  "max_completion_tokens": 1024,
  "tools": [{
    "type": "function",
    "function": {
      "name": "JobPosting",
      "description": "一条招聘信息里抽取出的关键字段。",
      "parameters": {"type": "object", "properties": {}, "required": []},
      "strict": true
    }
  }],
  "tool_choice": {"type": "function", "function": {"name": "JobPosting"}}
}
```

### Responses API（`POST /v1/responses`，新主推）

字段又换一轮：`messages` → `input`，`system` → `instructions`，
`max_completion_tokens` → `max_output_tokens`，工具定义拍平（不再套 `function` 那层）。

### 逐项差异

| 关注点 | Anthropic Messages | OpenAI Chat Completions |
|---|---|---|
| 系统提示 | **顶层 `system` 字段** | 塞进 `messages[0]`，role 为 `system`/`developer` |
| 首条消息 | 必须是 `user` | 无限制 |
| 输出上限 | `max_tokens`，**必填** | `max_completion_tokens`，可选（`max_tokens` 已废弃） |
| 工具定义 | 扁平 `{name, description, input_schema}` | 套娃 `{type:"function", function:{...}}` |
| schema 键名 | `input_schema` | `parameters` |
| 强制调工具 | `{"type":"tool","name":"X"}` | `{"type":"function","function":{"name":"X"}}` |
| 结构化输出 | `output_config.format` | `response_format.json_schema` / Responses 的 `text.format` |
| 返回内容 | `content` **块数组**（text/tool_use/thinking 混排） | `choices[0].message.content` + `.tool_calls` |
| 停止原因 | `stop_reason`（`end_turn`/`tool_use`/`refusal`…） | `finish_reason`（`stop`/`tool_calls`/`length`…） |
| 图片输入 | `{"type":"image","source":{"type":"base64",...}}` | `{"type":"image_url","image_url":{"url":"data:..."}}` |
| 思考 | `thinking: {type:"adaptive"}` | `reasoning_effort`（仅 o 系 / gpt-5 系） |

### 对本仓库的意义

两条线索串起来看：

1. **LangChain 就是干这个的**。`ChatAnthropic` 与 `ChatOpenAI` 各自把统一的
   `AIMessage` / `tool_calls` 翻译成两套协议——`with_structured_output(JobPosting)`
   一份代码换 provider 就能跑，代价正是 §4 那个「`raw` 不是真正的原始响应」。

2. **本仓库的网关在做协议转换**。它收 Anthropic 格式、转发到 `gpt-5.6-sol`（见 §4），
   中间必有一层 adapter。这解释了 §6 的现象：`tools` / `tool_choice` 能翻译（两家都有
   对应概念），但 `output_config.format` 翻不过去（OpenAI 侧叫 `response_format`，
   语义还不完全等价），所以 `json_schema` 在这里不兑现约束。

---

## 10. 国产模型（豆包 / 千问 / GLM / Kimi）的 API 参考谁设计的？

**以 OpenAI 为准，不是 Anthropic。**

事实上的行业标准是 OpenAI 的 Chat Completions——国内几家的**原生 / 默认**接口全是它的形状
（`messages` 数组、`tools[].function` 套娃、`choices[0].message`、`finish_reason`）：

| 厂商 | OpenAI 兼容端点 |
|---|---|
| 豆包（火山方舟 Ark） | `https://ark.cn-beijing.volces.com/api/v3/chat/completions` |
| 千问（阿里云百炼） | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` |
| GLM（智谱） | `https://open.bigmodel.cn/api/paas/v4/chat/completions` |
| Kimi（Moonshot） | `https://api.moonshot.cn/v1/chat/completions` |
| DeepSeek | `https://api.deepseek.com/chat/completions` |

所以国内 SDK 大多直接 `pip install openai` 改个 `base_url` 就能用。

### Anthropic 格式是后补的兼容层

这两年才加的，动机很单一：**让 Claude Code 能接自家模型**。路径上通常带 `/anthropic` 前缀：

- Kimi：`https://api.moonshot.cn/anthropic/v1/messages`
- 智谱：`https://open.bigmodel.cn/api/anthropic`
- 豆包 / MiniMax / DeepSeek 也都有对应端点

用法就是设 `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`——**和本仓库现在干的事一模一样**。

### 两个例外

1. **千问有自己的原生格式**（DashScope）：`{"input": {"messages": [...]}, "parameters": {...}}`，
   两层嵌套，跟谁都不像。OpenAI 兼容模式是另开的一条路——注意 URL 里那段 `compatible-mode`。
2. **豆包早期要传 endpoint ID**（`ep-2024xxxx`）而非模型名，现在支持直接填模型名，
   但老代码里还能见到。

### 对本仓库的意义

兼容层**只保核心字段**（`messages` / `tools` / `tool_choice` / `stream`），边缘功能基本翻译不过去：
prompt caching、`response_format` ↔ `output_config.format`、thinking、并行工具调用、logprobs
——行为各不相同甚至直接忽略。

这正是 §6 那个坑的通用版本：**`tools` / `tool_choice` 两家都有对应概念所以能翻译，
`output_config.format` 没有等价物所以静默失效。** 换任何一个国产网关都会遇到同类问题，
不是某个网关的 bug，是兼容层的固有边界。

判断方法同 §5：开 `ANTHROPIC_LOG=debug` 看实际发出去什么，再看返回里的 `model` 字段是谁
——本仓库就是这样抓到 `gpt-5.6-sol` 的（见 §4）。

## 11. 返回的 `tool_use` 里为什么"一定"有 `name` / `title` / `remote` 这些字段？

看一段实测返回：

```json
"content": [{
  "type": "tool_use",
  "id": "call_u26dXM72CRVTGKyA4XDWgRUV",
  "name": "JobPosting",
  "input": {
    "title": "高级后端工程师", "company": "", "location": "上海",
    "remote": true, "min_salary_k": 30,
    "skills": ["Python", "PostgreSQL", "Kubernetes"],
    "work_experience": 3
  }
}]
```

三类字段，三种不同强度的保证，别混为一谈：

| 字段 | 为什么在 | 强度 |
|---|---|---|
| `name: "JobPosting"` | `tool_choice` 指名要它，工具表里也只有它 | 请求参数锁死 |
| `title` / `company` / `location` / `remote` / `skills` | 在 schema 的 `required` 里 | schema 锁死（视 strict 而定） |
| `min_salary_k` / `work_experience` | 不在 `required`，有 `default: null`；原文恰好提到"30k 起""3-5 年" | 模型自愿填的 |

- `tool_choice` 换成 `"auto"`，模型可以选择不调工具、直接回文本，`content` 里就只剩 `text` 块，`tool_calls` 为空——`with_structured_output` 解析会失败（呼应 §6 结尾那个 thinking 的坑）。
- 可选字段的缺席才是正确行为，正是 §1 那两行 `assert` 守的契约。

### 坑：`required` 只保证"键存在"，不保证"值有意义"

上面返回里 `"company": ""` —— 原文压根没写公司名，但 `company` 被放进了 `required`，模型不能省略这个键，于是塞了个空串交差。**"没有信息"被扭曲成了"信息是空字符串"**，下游 `if not data.company` 和 `if data.company is None` 会踩到不同的雷。

修法与 `min_salary_k` 一致——凡是原文可能不提的，一律 Optional：

```python
company: str | None = Field(None, description="公司名称，文本没提到就留空")
```

同一段返回里 `work_experience: 3` 是另一个信息损失：原文"3-5 年"被压进单个 int，区间丢了。要么拆 `min_years` / `max_years`，要么直接存原文字符串。**schema 设计决定了信息能不能无损落地**，模型只能在你给的形状里尽力。

### `strict` 决定"一定"有多硬

本仓库这次请求是 `"strict": false`：

- `strict: true` —— **约束解码**，服务端在生成时把不合 schema 的 token 概率抹零，结构必然合法（代价：schema 要带 `additionalProperties: false`，且部分 JSON Schema 特性不支持）。
- `strict: false` —— 退化成**强提示 + 事后校验**，绝大多数时候对，极端情况仍可能返回不合 schema 的结构，靠 Pydantic 兜底报错。

要真正的"一定"，把 strict 打开（§7 末尾提到的可选加固就是这件事）。

---

## 12. 这些参数是 API 提供商支持才能写吗？

**是，而且是双向的约束。**

**① 请求里能写什么，由服务端契约定。** 请求体不是随便拼的 JSON。`tool_choice` / `strict` / `reasoning.effort` / `verbosity` 都是提供商在 API 文档里声明支持的字段，自己发明一个 `temperature_v2` 上去，只会被忽略或直接 400。§9 那张对照表里两家字段名不同，根源就在这——同一个"工具入参 schema"，Anthropic 叫 `input_schema`，OpenAI 叫 `parameters`。

**② "一定返回这些字段"的保证，也在服务端。** 约束解码是提供商在推理侧实现的，客户端做不到——客户端只能拿到结果后校验、失败重试。所以 §11 那个 `strict` 开关的效力，完全取决于网关/上游是否真的实现了它（§6 已经证明本网关连 `output_config.format` 都不兑现，`strict` 同理要实测）。

**③ LangChain 只是翻译层。** 本仓库写的是一份 Pydantic 模型：

```python
model.with_structured_output(JobPosting, method="function_calling")
```

内部把它编译成当前 provider 的工具格式塞进请求，再把返回的 `tool_use.input` 反序列化回 Pydantic 对象。换成 `ChatOpenAI`，同一份 `JobPosting` 会被编译成 §9 里那种 `parameters` 形状，业务代码一行不改——这是这层抽象唯一值钱的地方。

**代价**：provider 独有的能力（Anthropic 的 `thinking`、OpenAI 的 `verbosity`）得靠 `model_kwargs` 透传，抽象就漏出来了。加上 §4 说的"`raw` 已经不是真正的原始响应"——统一抽象换来的可移植性，代价永远是看不清底下发生了什么。

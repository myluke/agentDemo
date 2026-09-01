# 阶段 3 · 结构化输出 — 回顾笔记

配套代码：[`structured_output.py`](../structured_output.py)

> **provider 变更提示**：本篇初稿写于 demo 还用 `ChatAnthropic` 直连 `/v1/messages` 时。
> 现在 `structured_output.py` 走 `llm.py` 的 `openai_chat()` → **`ChatOpenAI`**，
> 打的是 `POST /v1/chat/completions`。§3–§8、§11 已按 OpenAI 协议改写；
> §9–§10、§13–§15 讲的是两家协议对比与国产网关通病，本身仍成立，保留。

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

注意 `raw.content` 在 `function_calling` 下是**空字符串**——模型这一跳没打算说人话，
结构化结果全在 `raw.tool_calls[0]["args"]` 里。换成 `json_schema` / `json_mode` 则相反：
`tool_calls` 是空列表，JSON 文本在 `content` 里。**先确认走的哪条通道，再去对应的地方捞数据。**

---

## 4. `raw` 是模型返回的原始数据吗？

**不是。** 它是 LangChain 标准化后的 `AIMessage`，不是 HTTP 响应的原始 JSON。

```text
网关原始 HTTP JSON
      ↓ ChatOpenAI 转换
LangChain AIMessage        ← include_raw=True 看到的是这层
      ↓ with_structured_output 解析
JobPosting 对象
```

`raw` 里三类数据的来源：

- `content`：尽量保留模型返回的内容块，但已转成 LangChain 结构。
- `tool_calls`：LangChain 从 `content` 提取出的统一格式，所以看起来和 `content` 重复。
- `response_metadata` / `usage_metadata`：整理后的模型标识、停止原因、token 用量。

本机实测（`base_url = https://helm.easymeta.au/v1`）：

```json
"model": "gpt-5.6-terra",
"model_provider": "openai"
```

`config.ini` 里配的模型名会被网关照单转发。注意这里的 `model_provider` 只是 LangChain
按客户端类型打的标签，**不代表背后真是 OpenAI 的机器**——网关转发到什么模型、兑现哪些
参数，只能靠实测（见 §6）。

---

## 5. 怎么看到更底层的请求？

设环境变量即可，SDK 自带（`structured_output.py` 已用 `os.environ.setdefault` 固化）。
**注意换 provider 就要换变量名**——`ChatOpenAI` 底下是 openai SDK，只认 `OPENAI_LOG`：

```python
os.environ.setdefault("OPENAI_LOG", "debug")   # 曾经是 ANTHROPIC_LOG
```

或临时开，不改代码：

```bash
OPENAI_LOG=debug .venv/bin/python structured_output.py
```

实测发出的请求体（`function_calling`，删节）：

```json
{
  "model": "gpt-5.6-terra",
  "max_completion_tokens": 1024,
  "reasoning_effort": "low",
  "parallel_tool_calls": false,
  "tool_choice": {"type": "function", "function": {"name": "JobPosting"}},
  "tools": [{"type": "function", "function": {
      "name": "JobPosting",
      "description": "一条招聘信息里抽取出的关键字段。",
      "parameters": {"type": "object", "properties": {...}, "required": [...]}}}],
  "stream": false
}
```
```text
POST https://helm.easymeta.au/v1/chat/completions
```

三个之前看不到的细节，都能在这里对上：

- `max_tokens=1024` 传进 `openai_chat()`，出去变成了 **`max_completion_tokens`**（§9 的差异表）。
- `reasoning_effort: "low"` 是 `llm.py` 里 `EFFORT` 的默认值，不是这个 demo 写的。
- `parallel_tool_calls: false` 是 `with_structured_output` 自己加的——只要一张表，
  不许模型并行调多次。

**比 SDK 日志更好用的办法**：`structured_output.py` 里已经挂了 httpx 钩子，
直接拿到响应 body（SDK 的 debug 日志只打响应头，不打 body）：

```python
model.root_client._client.event_hooks["response"].append(print_raw_response)
```

`root_client` 是底层 `openai.OpenAI`，`._client` 是它的 httpx 客户端。想看请求体就挂
`event_hooks["request"]`，`json.loads(request.content)` 即可。这是排查网关行为最直接的一层。

**安全**：请求 body 含业务输入和 schema，会进终端日志，生产别常开。

---

## 6. `method` 有几个？分别干什么？

`ChatOpenAI` 上是 **3 个**（langchain-openai 1.6.0，`base.py:3723`），走两条不同的通道：

| method | 请求体字段 | 结果落在哪 | 保证什么 |
|---|---|---|---|
| `function_calling` | `tools` + `tool_choice` 指名 | `tool_calls[0]["args"]`，`content` 为空 | 模型「尽量」照填，可能漏字段 |
| `json_schema` | `response_format.json_schema` | `content` 是 JSON 文本，`tool_calls` 为空 | 服务端约束解码，语法上不可能违规 |
| `json_mode` | `response_format: {"type":"json_object"}` | 同上 | **只保证是合法 JSON，不保证符合 schema** |

- `function_calling` 是「借用」工具调用机制骗模型填参数：schema 伪装成一个叫 `JobPosting`
  的工具，`tool_choice` 逼它必须调。**那个函数根本不存在**，args 就是终点，永不执行
  ——这也是它和阶段 8 真工具调用的唯一区别（详见 [stage8-notes §「回头看阶段 3」](stage8-notes.md)）。
- `json_schema` 是官方为结构化输出专门做的通道，不绕工具，两者正交（可以同时挂真工具）。
- `json_mode` 是 `json_schema` 出现前的过渡产物，schema 得自己写进提示词，现在没理由用。
- 传其他值直接 `ValueError`。

### 坑一：默认值被覆写了

**`ChatOpenAI` 把 `method` 默认值改成了 `json_schema`**，只有基类 `BaseChatOpenAI` 才是
`function_calling`（`base.py:2497` vs `base.py:3723`）。所以 demo 里那个
`method="function_calling"` 不是装饰，是必须显式写的——不传就默认走进下面这个坑。

### 坑二：本网关不兑现 `response_format`

实测（`gpt-5.6-terra`）：

| method | 结果 |
|---|---|
| `function_calling` | ✅ `tool_calls` 正常回填，Pydantic 校验通过 |
| `json_schema` | ❌ `ValidationError: Invalid JSON`，`content` 是一段 Markdown 招聘启事 |
| `json_mode` | ⚠️ 是合法 JSON 了，但 `company: null` 撞上 `str` 必填，仍校验失败 |

`json_schema` 的失败形态值得看清楚：网关**没报错**，只是把 `response_format` 静默忽略了，
模型当成普通对话请求自由发挥，回了段 `**招聘：高级后端...**`。
**参数被无视和参数被拒绝，表现完全不同**——前者要到 Pydantic 炸了才发现。

`json_mode` 那档说明另一件事：语法保证和 schema 保证是两码事（详见 §14）。

### 坑三：`json_schema` 会改写你的 Optional 语义

`strict=True` 时 LangChain 生成的 schema 里，`min_salary_k` 的 `default: null` 被丢掉，
字段被强塞进 `required`、外加 `additionalProperties: false`：

```json
"required": ["title", "company", "remote", "min_salary_k"], "strict": true
```

「没提到就留空」于是变成「必须显式吐 `null`」。§1 那两行 assert 仍能过，但契约变了。

**验证方法**：挂 §5 那个 request 钩子，换 method 再跑，看 `tools` 和 `response_format` 谁出现。

---

## 附：本阶段核心要点（一句话）

`model.with_structured_output(Schema)` 让链直接输出经 Pydantic 校验的对象，省掉「提示模型输出 JSON → 手写 `json.loads` → 逐字段校验」。当前网关不兑现 OpenAI 的 `response_format`，而 `ChatOpenAI` 的默认 method 恰恰是 `json_schema`，**所以必须显式写 `method="function_calling"`**。

---

## 7. 发出去的请求体是 OpenAI 官方格式吗？

是，`POST /v1/chat/completions` 的合法请求体，逐字段核对（实测 body 见 §5）：

| 字段 | 结论 |
|---|---|
| `model` / `messages` | 两个必填项，模型名由 `config.ini` 决定，网关照单转发 |
| `max_completion_tokens` | 新字段名。`max_tokens` 已被 OpenAI 废弃，LangChain 自动改写 |
| `tools[].{type:"function", function:{name, description, parameters}}` | 标准工具定义，注意是**套娃**结构，schema 键叫 `parameters`（Anthropic 那边扁平、叫 `input_schema`，见 §9） |
| `tool_choice: {"type":"function","function":{"name":"JobPosting"}}` | 强制调用指定工具，即 §6 的 `function_calling` |
| `parallel_tool_calls: false` | `with_structured_output` 自己加的：只要一张表，不许并行调多次 |
| `reasoning_effort: "low"` | 来自 `llm.py` 的 `EFFORT`，不是这个 demo 写的 |
| `min_salary_k` 的 `anyOf + default: null` | Pydantic 生成的 Optional，非 strict 模式下 schema 可自由书写 |

**SDK 内部字段不会上线**：openai SDK 的 debug 日志里那些 `X-Stainless-*` 头、
`<openai.Omit object>`（表示「这个 header 不发送」）都是 request options 层的东西。
带 `stainless-python-retry-` 前缀的 `idempotency_key` 说明是 SDK 自动重试
（默认 `max_retries=2`，对 429/5xx/连接错误重试），排错时别误当成 body 格式问题。

可选加固（当前没做）：`with_structured_output(..., strict=True)` 会给 tool 加
`strict: true` + `additionalProperties: false`，保证入参严格符合 schema。
但**这同样是服务端能力，本网关既然连 `response_format` 都不兑现，`strict` 也得实测**
（§12 展开）。

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

**这张表说的是 Claude 官方模型**，本仓库走网关转发（§4），上限以网关和实际后端为准，
只能实测。另外 `openai_chat(max_tokens=1024)` 发出去会变成 `max_completion_tokens`
（§5、§7）——名字变了，语义不变，仍是单次输出上限。

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

   **本仓库就现场演过一次**：从 `ChatAnthropic` 换成 `ChatOpenAI`，
   `JobPosting` 和链的写法一个字没动，变的只是底下的请求形状
   （`input_schema`→`parameters`、`max_tokens`→`max_completion_tokens`）。
   这篇笔记要大改，业务代码不用——抽象值钱的地方正在这里。

2. **网关只是转发，兑现哪些参数得实测**。§6 的结论是：`tools` / `tool_choice`
   这类「两家都有对应概念」的能力翻译得过去，`response_format` 这类靠服务端约束解码的
   直接被静默忽略。这不是某个字段名的问题，是能力层级的问题（§15 有完整的降级顺序）。

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
结构化输出那套（Anthropic 的 `output_config.format` / OpenAI 的 `response_format`）
没有等价物所以静默失效。** 换任何一个国产网关都会遇到同类问题，
不是某个网关的 bug，是兼容层的固有边界。

判断方法同 §5：开 `OPENAI_LOG=debug`（或挂 httpx 钩子）看实际发出去什么，
再看返回里的 `model` 字段是谁。

## 11. 返回的 `tool_calls` 里为什么"一定"有 `name` / `title` / `remote` 这些字段？

看一段实测返回（LangChain 标准化后的 `raw.tool_calls`）：

```json
[{
  "name": "JobPosting",
  "id": "call_C2aplw6S2YqAcdNLuXfwrRoU",
  "type": "tool_call",
  "args": {
    "title": "高级后端工程师", "company": "", "location": "上海",
    "remote": true, "min_salary_k": 30,
    "skills": ["Python", "PostgreSQL", "Kubernetes"],
    "work_experience": 3
  }
}]
```

（OpenAI 原始响应里是 `choices[0].message.tool_calls[].function.arguments`，
一段 **JSON 字符串**；LangChain 帮你 `json.loads` 成了上面的 `args`。）

三类字段，三种不同强度的保证，别混为一谈：

| 字段 | 为什么在 | 强度 |
|---|---|---|
| `name: "JobPosting"` | `tool_choice` 指名要它，工具表里也只有它 | 请求参数锁死 |
| `title` / `company` / `location` / `remote` / `skills` | 在 schema 的 `required` 里 | schema 锁死（视 strict 而定） |
| `min_salary_k` / `work_experience` | 不在 `required`，有 `default: null`；原文恰好提到"30k 起""3-5 年" | 模型自愿填的 |

- `tool_choice` 换成 `"auto"`，模型可以选择不调工具、直接回文本，`tool_calls` 为空——`with_structured_output` 解析会失败。这正是 §6 里 `json_schema` 那档的失败形态：**模型自由发挥、客户端才炸**。
- 可选字段的缺席才是正确行为，正是 §1 那两行 `assert` 守的契约。

### 坑：`required` 只保证"键存在"，不保证"值有意义"

上面返回里 `"company": ""` —— 原文压根没写公司名，但 `company` 被放进了 `required`，模型不能省略这个键，于是塞了个空串交差。**"没有信息"被扭曲成了"信息是空字符串"**，下游 `if not data.company` 和 `if data.company is None` 会踩到不同的雷。

修法与 `min_salary_k` 一致——凡是原文可能不提的，一律 Optional：

```python
company: str | None = Field(None, description="公司名称，文本没提到就留空")
```

同一段返回里 `work_experience: 3` 是另一个信息损失：原文"3-5 年"被压进单个 int，区间丢了。要么拆 `min_years` / `max_years`，要么直接存原文字符串。**schema 设计决定了信息能不能无损落地**，模型只能在你给的形状里尽力。

### `strict` 决定"一定"有多硬

本仓库这次请求没传 `strict`（即 `null`，等价于关闭）：

- `strict: true` —— **约束解码**，服务端在生成时把不合 schema 的 token 概率抹零，结构必然合法（代价：schema 要带 `additionalProperties: false`，且部分 JSON Schema 特性不支持）。
- `strict: false` —— 退化成**强提示 + 事后校验**，绝大多数时候对，极端情况仍可能返回不合 schema 的结构，靠 Pydantic 兜底报错。

要真正的"一定"，把 strict 打开（§7 末尾提到的可选加固就是这件事）——
**前提是服务端真的实现了它**，本网关连 `response_format` 都不兑现，别想当然。

---

## 12. 这些参数是 API 提供商支持才能写吗？

**是，而且是双向的约束。**

**① 请求里能写什么，由服务端契约定。** 请求体不是随便拼的 JSON。`tool_choice` / `strict` / `reasoning.effort` / `verbosity` 都是提供商在 API 文档里声明支持的字段，自己发明一个 `temperature_v2` 上去，只会被忽略或直接 400。§9 那张对照表里两家字段名不同，根源就在这——同一个"工具入参 schema"，Anthropic 叫 `input_schema`，OpenAI 叫 `parameters`。

**② "一定返回这些字段"的保证，也在服务端。** 约束解码是提供商在推理侧实现的，客户端做不到——客户端只能拿到结果后校验、失败重试。所以 §11 那个 `strict` 开关的效力，完全取决于网关/上游是否真的实现了它（§6 已经证明本网关连 `response_format` 都不兑现，`strict` 同理要实测）。

**③ LangChain 只是翻译层。** 本仓库写的是一份 Pydantic 模型：

```python
model.with_structured_output(JobPosting, method="function_calling")
```

内部把它编译成当前 provider 的工具格式塞进请求，再把返回的工具入参反序列化回 Pydantic 对象。**本仓库已经换过一次**：`ChatAnthropic` → `ChatOpenAI`，`JobPosting` 一行没改，底下从 `input_schema` 变成了 §9 那种 `parameters` 套娃形状——这是这层抽象唯一值钱的地方。

**代价**：provider 独有的能力（Anthropic 的 `thinking`、OpenAI 的 `verbosity`）得靠 `model_kwargs` 透传，抽象就漏出来了。加上 §4 说的"`raw` 已经不是真正的原始响应"——统一抽象换来的可移植性，代价永远是看不清底下发生了什么。

---

## 13. 国产模型都支持 `tool_choice` 强制调用吗？

**不能默认支持。** §6 说过 `method="function_calling"` 底层就是
`tool_choice={"type":"function","function":{"name":"JobPosting"}}`（强制调指定函数）——
这在国内各家参差不齐，**思考模式模型是重灾区**。

| 厂商 | 指定函数 / `required` |
|---|---|
| DeepSeek | `deepseek-chat`(V3) ✅；`deepseek-reasoner` / V4（默认思考模式）❌ 直接 400 `does not support this tool_choice` |
| Kimi | `kimi-k3` ✅ 支持 auto/none/required；其余模型不支持 `required`，传了报错 |
| 通义千问 | OpenAI 兼容模式文档列了全套取值，但思考模式 / VL 模型有限制，按具体模型确认 |
| 智谱 GLM | 官方文档没有 `tool_choice` 取值表，只能实测 |

**最阴的坑**：DeepSeek 在你**没传** `tool_choice` 时也可能报这个错——
`reasoning_effort` + `tools` 会让服务端内部推断出一个 `tool_choice`。
排错时别在客户端请求体里找，找不到的。

**波及范围**：LangChain / AutoGen / CrewAI 绑定结构化输出时都会发送具体函数名的
`tool_choice`，所以是整片框架一起挂，不是某个库的 bug。

---

## 14. 那退回 `json_object` 就都支持了？

前半句对，后半句不对。**这是两档能力，别混为一谈：**

| | `json_object` | `json_schema`（strict） |
|---|---|---|
| 保证什么 | 语法是合法 JSON | 字段名 / 类型 / 必填**严格符合** schema |
| 谁来保证 | 服务端 | 服务端约束解码 |
| 国内覆盖 | 基本都有 | 很窄 |

- **DeepSeek**：`response_format` 只有 `text` / `json_object` 两个取值，
  `json_schema` 直接拒（返回 "unavailable now"）。schema 约束只存在于 beta 端点
  （`base_url="https://api.deepseek.com/beta"`）的 tool calling `strict: true`，
  且有已知 bug——返回的 `function.arguments` 第一个属性名少个收尾双引号，解析直接炸。
- **通义千问**：`json_schema` 只有 `qwen-plus-latest` 和少数 2025 快照支持，还限北京地域。

**所以 `json_object` 模式下，「约定返回什么字段」靠的是提示词，不是 API 强制。**
`with_structured_output(..., method="json_mode")` 正是干这个：LangChain 只发
`response_format: {"type":"json_object"}`，**schema 得你自己写进提示词**，
拿回文本再用 Pydantic 校验。

本仓库实测就撞上了（§6 那张表第三行）：返回 `{"title":"高级后端工程师","company":null,...}`
——语法完全合法，但 `company` 是 `null` 而 schema 里它是必填 `str`，Pydantic 直接报
`Input should be a valid string`。**语法有保证，schema 没有，得自己校验 + 重试。**

---

## 15. `json_object` 对模型版本有要求吗？小模型是不是不支持？

有要求，但**是「版本快照」的要求，不是「模型大小」的要求**。

千问官方划的线是一个日期：

| 模型 | 支持情况 |
|---|---|
| `qwen-max-2024-09-19` 及之后的快照 | ✅（之前的 ❌） |
| `qwen-plus-2024-09-19` 及之后 | ✅ |
| `qwen-turbo-latest`、`qwen2.5` 系列 | ✅ ← **turbo 是小模型，照样支持** |
| `qwen-long` 全部快照 | ✅ |

所以不是「小模型不行」，是「2024 年 9 月之前的老快照不行」。现在随手拿 `-latest`
或近两年的快照，`json_object` 基本都有。

### 三个与模型档次无关的坑

1. **思考模式**——最大雷区。千问文档在不同版本里说法自相矛盾（有的说不支持，
   有的说「不报错但结构化输出可能失效」）；DeepSeek 那边同样是思考模型出问题。
   **静默失效比报错更难查。**
2. **prompt 里没有 "json" 字样** → 400，报错原文：
   `'messages' must contain the word 'json' in some form`。千问、DeepSeek 都有这条硬性检查。
3. **设了 `max_tokens`** → JSON 输出中途被截断 → 解析失败。开结构化输出时别设，
   或设得足够大（呼应 §8）。

### 对本仓库的意义

把 §6、§13、§14 串起来看，是同一条规律的三次现身——
**能力越靠近服务端约束解码，跨 provider 的可移植性越差**：

```text
tools / tool_choice=auto   两家都有等价概念  → 翻译得过去
tool_choice 指定函数        语义相近但实现分裂 → 部分模型 400
json_object                语法层保证，门槛低 → 基本都有
json_schema / strict       服务端约束解码     → 几乎翻译不过去
```

本仓库的网关不兑现 `response_format` 不是孤例，是这条规律在最右端的必然结果——
**换成 OpenAI 协议直连之后照样不兑现**（§6 实测），可见问题从来不在协议翻译，
而在后端有没有实现约束解码。

降级顺序：

```text
function_calling → json_mode（schema 写进提示词）→ PydanticOutputParser
```

最后那档完全不依赖服务端特性：`PydanticOutputParser` 把 schema 转成一段格式说明塞进
提示词，模型吐文本，本地解析 + 校验。任何能说话的模型都能用，代价是最不可靠。

判断当前档位能不能用，方法还是 §5 那套：`OPENAI_LOG=debug` 或 httpx 钩子看实际发出去什么，
再看回来的东西落在 `tool_calls` 还是 `content`。

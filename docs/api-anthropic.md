# Anthropic (Claude) API 接口速查

基址 `https://api.anthropic.com`，所有请求带两个头：

```
x-api-key: sk-ant-...
anthropic-version: 2023-06-01
```

部分接口另需 `anthropic-beta: <beta 名>`（下表标注）。本仓库通过
`ANTHROPIC_BASE_URL` 指向自建网关，网关只转发它实现了的那部分端点。

---

## 一句话概览

Anthropic 的设计和 OpenAI 很不一样：**几乎所有生成能力都压在 `/v1/messages`
一个端点上**。工具调用、视觉、PDF、思考、结构化输出、缓存都是它的参数，不是独立接口。
其余端点是配套设施（批处理、文件、模型列表）和 Agent 平台。

| 分组 | 端点 | 作用 |
|---|---|---|
| 对话生成 | `/v1/messages` | 唯一的生成入口 |
| 计费预估 | `/v1/messages/count_tokens` | 发之前先数 token |
| 批处理 | `/v1/messages/batches` | 异步跑一批，半价 |
| 文件 | `/v1/files` | 传一次，多轮复用 |
| 模型 | `/v1/models` | 查有哪些模型、上下文多大 |
| 技能 | `/v1/skills` | 给模型挂可复用的技能包 |
| Agent 平台 | `/v1/agents`、`/v1/sessions` 等 | 托管式 Agent（Managed Agents，beta） |
| 组织管理 | `/v1/organizations/*` | 成员、密钥、用量（需 Admin key，beta） |

**没有 `/v1/embeddings`**——Anthropic 不提供向量化服务，官方建议搭配 Voyage AI。
这就是本仓库阶段 6 的 RAG 只能用本地 embedding 的原因，见
[stage6-notes.md](stage6-notes.md)。

---

## `/v1/messages` — 对话生成

**作用**：给一串消息，返回模型回复。所有能力都是它的参数。

```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-opus-5",
    "max_tokens": 1024,
    "system": "你是客服助手。",
    "messages": [{"role": "user", "content": "会员到期后数据保留多久？"}]
  }'
```

响应的 `content` 是**内容块数组**（不是一个字符串），所以要先看 `type` 再取值：

```json
{
  "content": [{"type": "text", "text": "保留 180 天。"}],
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 25, "output_tokens": 12}
}
```

### 常用参数一览

| 参数 | 作用 | 说明 |
|---|---|---|
| `system` | 系统提示 | 顶层字段，**不是** messages 里的一条 |
| `stream: true` | 流式返回 | SSE；长输出必开，否则容易 HTTP 超时 |
| `tools` | 工具调用 | 模型返回 `tool_use` 块，你执行后回填 `tool_result` |
| `thinking` | 扩展思考 | 新模型用 `{"type":"adaptive"}`；`budget_tokens` 已废弃 |
| `output_config.effort` | 推理档位 | `low`…`max`，默认 `high`；调低最省钱 |
| `output_config.format` | 结构化输出 | 用 JSON Schema 约束回复格式 |
| `cache_control` | 提示缓存 | 命中部分约省 90%，见下 |
| `stop_reason` | 停止原因 | `end_turn` / `max_tokens` / `tool_use` / `refusal` |

### 工具调用长什么样

```json
{"tools": [{
  "name": "get_weather",
  "description": "查询指定城市的天气",
  "input_schema": {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"]
  }
}]}
```

模型不直接执行工具，只返回一个 `tool_use` 块告诉你「我想调 `get_weather("北京")`」；
**你在自己的代码里执行**，再把结果作为 `tool_result` 发回去，模型接着说话。
这就是本仓库阶段 7 要练的东西。

### 提示缓存

同一段长前缀重复发送时，标记它可以缓存：

```json
{"system": [{
  "type": "text",
  "text": "<一大段固定的产品手册>",
  "cache_control": {"type": "ephemeral"}
}]}
```

缓存按**前缀精确匹配**：前缀里任何一个字节变了，后面全部失效。所以固定内容放前面，
变动内容（时间戳、用户问题）放后面。验证是否命中看
`usage.cache_read_input_tokens` 是否大于 0。

---

## `/v1/messages/count_tokens` — 数 token

**作用**：不真的调用模型，只返回这次请求会消耗多少输入 token。用来估价、防超限。

```bash
curl https://api.anthropic.com/v1/messages/count_tokens \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-opus-5","messages":[{"role":"user","content":"你好"}]}'
# → {"input_tokens": 9}
```

不要用 `tiktoken` 估 Claude 的 token——那是 OpenAI 的分词器，数不准。

---

## `/v1/messages/batches` — 批处理

**作用**：一次提交最多几万条请求，异步跑，**价格打五折**。适合离线任务：批量分类、
批量摘要、跑评测集。不适合要即时响应的场景。

```bash
# 1. 提交
curl https://api.anthropic.com/v1/messages/batches \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
  -d '{"requests": [
    {"custom_id": "req-1", "params": {"model":"claude-opus-5","max_tokens":100,
     "messages":[{"role":"user","content":"翻译：hello"}]}},
    {"custom_id": "req-2", "params": {"model":"claude-opus-5","max_tokens":100,
     "messages":[{"role":"user","content":"翻译：world"}]}}
  ]}'

# 2. 轮询直到 processing_status 变成 "ended"
curl .../v1/messages/batches/{id} -H "x-api-key: ..."

# 3. 取结果
curl .../v1/messages/batches/{id}/results -H "x-api-key: ..."
```

**关键**：结果**顺序不保证**，必须靠 `custom_id` 对应回去，绝不能按下标取。

---

## `/v1/files` — 文件

**作用**：把 PDF、图片传一次拿到 `file_id`，之后多轮对话直接引用，不用每次重传 base64。

```bash
curl https://api.anthropic.com/v1/files \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
  -F "file=@report.pdf"
# → {"id": "file_abc123", ...}
```

引用时内容块类型要和文件类型对上（PDF/文本用 `document`，图片用 `image`）：

```json
{"role": "user", "content": [
  {"type": "document", "source": {"type": "file", "file_id": "file_abc123"}},
  {"type": "text", "text": "总结这份报告的三个要点"}
]}
```

也可以不用 Files API，直接内联 base64（小文件更省事）：

```json
{"type": "document", "source": {
  "type": "base64", "media_type": "application/pdf", "data": "<base64 串>"
}}
```

---

## `/v1/models` — 模型列表

**作用**：查当前可用模型及其能力，不用把型号写死在代码里。

```bash
curl https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01"
```

返回每个模型的 `id`、`display_name`、`max_input_tokens`（上下文窗口）、
`max_tokens`（输出上限）、`capabilities`。本仓库探测网关支持哪些模型用的就是它。

---

## `/v1/skills` — 技能

**作用**：把「一套指令 + 脚本 + 资源」打成包挂给模型，比如让它会生成 `.pptx`、
`.xlsx`。配合代码执行工具使用。

```json
{
  "model": "claude-opus-5",
  "container": {"skills": [{"skill_id": "skill_abc", "version": "latest"}]},
  "tools": [{"type": "code_execution_20260521", "name": "code_execution"}],
  "messages": [{"role": "user", "content": "把这些数据做成 PPT"}]
}
```

注意：Skills 和下面的 Managed Agents 是**两回事**，别混用。

---

## Managed Agents（beta）— 托管 Agent

需要 `anthropic-beta: managed-agents-2026-04-01`。

**作用**：Anthropic 帮你跑 Agent 循环，并托管一个沙箱容器（可以跑 bash、读写文件、
执行代码）。你只管配置和收事件，不用自己写 while 循环、不用自己准备机器。

固定两步：**先建 Agent（一次），再开 Session（每次运行）**。

| 端点 | 作用 |
|---|---|
| `POST /v1/agents` | 创建 Agent 配置（模型、system、工具都在这层） |
| `POST /v1/sessions` | 用某个 Agent 开一次会话，分配一个沙箱容器 |
| `GET /v1/sessions/{id}/events/stream` | SSE 订阅这次会话的事件流 |
| `POST /v1/sessions/{id}/events` | 发消息 / 回填工具结果 |
| `POST /v1/sessions/{id}/resources` | 挂文件或 GitHub 仓库进沙箱 |
| `/v1/environments` | 沙箱环境配置（网络、预装包） |
| `/v1/vaults` | 存密钥，出网时替换，沙箱里看不到明文 |
| `/v1/memory_stores` | 跨会话的长期记忆 |
| `/v1/deployments` | 定时触发（cron），比如「每晚跑一次报告」 |

```bash
# 1. 建 Agent（只需一次，存下 agent_id）
curl https://api.anthropic.com/v1/agents \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: managed-agents-2026-04-01" \
  -d '{"model":"claude-opus-5","system":"你是代码审查助手。","tools":[...]}'

# 2. 每次运行开一个 Session
curl https://api.anthropic.com/v1/sessions \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: managed-agents-2026-04-01" \
  -d '{"agent":"agent_abc123"}'
```

**和本仓库阶段 8 的关系**：阶段 8 用 LangGraph 自己编排 Agent 循环，机器是你的；
Managed Agents 是把循环和机器都交给 Anthropic。两条路解决同一个问题，选哪条看你
想不想自己运维。

---

## `/v1/organizations/*`（beta）— 组织管理

**作用**：管人和钱，不发消息。需要 **Admin API key**（`sk-ant-admin...`），
普通 key 会被拒。

| 端点 | 作用 |
|---|---|
| `/v1/organizations/users` | 成员增删改查 |
| `/v1/organizations/invites` | 邀请 |
| `/v1/organizations/workspaces` | 工作区（按项目隔离用量和密钥） |
| `/v1/organizations/api_keys` | API key 管理 |
| `/v1/organizations/rate_limits` | 限流报告 |
| `/v1/organizations/usage_report`、`cost_report` | 用量和费用（只能裸 HTTP，SDK 未封装） |

---

## 常见坑

- **`content` 是数组不是字符串**：直接 `response.content` 拿到的是块列表，
  要 `block.type == "text"` 才有 `.text`。
- **没有 embeddings**：见开头。
- **`system` 是顶层字段**：不要塞进 `messages` 里当一条消息（新模型允许把
  `role: "system"` 放进 messages 中途插入操作指令，但那是另一个用途）。
- **prefill 已被移除**：新模型（Opus 5、Sonnet 5、4.6+ 系列）不再支持用一条
  assistant 消息开头来「引导」输出格式，会直接 400。要控格式用 `output_config.format`。
- **批处理结果乱序**：靠 `custom_id`，别按下标。
- **错误要分类处理**：429 和 5xx 该重试，400/404 重试没用。SDK 默认重试 2 次。

---

**一句话**：Anthropic 的 API 是「一个 `/v1/messages` + 一圈配套设施」；
OpenAI 是「一堆专用端点」。对比见 [api-openai.md](api-openai.md)。

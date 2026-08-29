# OpenAI API 接口速查

基址 `https://api.openai.com`，请求头：

```
Authorization: Bearer sk-...
Content-Type: application/json
```

`/v1/embeddings` 这类路径已经是行业事实标准，很多第三方网关（包括各种代理、
本地推理服务 Ollama / LM Studio / vLLM）都照抄 OpenAI 的接口形状，所以认识它
不只是为了用 OpenAI。

---

## 一句话概览

和 Anthropic「所有能力压在一个端点」相反，**OpenAI 是按能力拆成一堆专用端点**。

| 分组 | 端点 | 作用 |
|---|---|---|
| 对话生成（新） | `/v1/responses` | 当前推荐入口，支持工具、有状态对话 |
| 对话生成（旧） | `/v1/chat/completions` | 事实标准，兼容生态最广 |
| **向量化** | `/v1/embeddings` | **文本转向量，RAG 的地基** |
| 语音 | `/v1/audio/speech`、`/transcriptions` | TTS、转写 |
| 图像 | `/v1/images/generations`、`/edits` | 文生图、改图 |
| 视频 | `/v1/videos` | Sora 生成视频 |
| 实时 | `/v1/realtime` | 低延迟语音对话（WebRTC / WebSocket） |
| 文件 | `/v1/files` | 上传文件供其它接口引用 |
| 向量库 | `/v1/vector_stores` | 托管式向量库，自带切分和检索 |
| 批处理 | `/v1/batches` | 异步批量，半价 |
| 审核 | `/v1/moderations` | 判断内容是否违规（免费） |
| 微调 | `/v1/fine_tuning/jobs` | 训练自己的模型 |
| 会话 | `/v1/conversations` | 服务端存对话历史 |
| 沙箱 | `/v1/containers` | Code Interpreter 的容器 |
| 评测 | `/v1/evals` | 跑评测集 |
| 模型 | `/v1/models` | 模型列表 |
| 组织管理 | `/v1/organization/*` | 成员、项目、密钥、审计日志 |

> 2026 年 8 月 26 日 Assistants API 已下线，迁移到 `/v1/responses`。

---

## `/v1/chat/completions` — 对话（经典）

**作用**：给一串消息，返回回复。虽然官方推荐新项目用 `/v1/responses`，但这个端点
是**兼容性最好的那个**——绝大多数第三方服务模仿的都是它。

```bash
curl https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.6",
    "messages": [
      {"role": "system", "content": "你是客服助手。"},
      {"role": "user", "content": "会员到期后数据保留多久？"}
    ]
  }'
```

```json
{"choices": [{"message": {"role": "assistant", "content": "保留 180 天。"},
              "finish_reason": "stop"}],
 "usage": {"prompt_tokens": 25, "completion_tokens": 12}}
```

### 和 Anthropic 的三处形状差异

| | OpenAI | Anthropic |
|---|---|---|
| 系统提示 | messages 里 `role: "system"` 的一条 | 顶层 `system` 字段 |
| 取回复 | `choices[0].message.content`（字符串） | `content[]` 内容块数组 |
| 停止原因 | `finish_reason` | `stop_reason` |

写兼容层时这三处最容易翻车。

---

## `/v1/responses` — 对话（新）

**作用**：Chat Completions 的进化版，多了 Agent 原语——内置工具、多模态输入、
服务端保存对话状态。

```bash
curl https://api.openai.com/v1/responses \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
    "model": "gpt-5.6",
    "input": "查一下今天北京天气",
    "tools": [{"type": "web_search"}]
  }'
```

有状态是它和 Chat Completions 最大的区别——**不用每次重发全部历史**：

```json
{"model": "gpt-5.6", "input": "那明天呢？", "previous_response_id": "resp_abc123"}
```

对照本仓库阶段 5：LangGraph 的 checkpointer 是**你自己在客户端存历史**；
`previous_response_id` 是**让服务端替你存**。前者可控可迁移，后者省事但绑定厂商。

---

## `/v1/embeddings` — 向量化 ⭐

**作用**：把文本转成一串定长浮点数（向量），语义越近向量越近。**RAG 的地基。**

```bash
curl https://api.openai.com/v1/embeddings \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-3-small", "input": "我家的猫"}'
```

```json
{"data": [{"embedding": [0.021, -0.043, 0.118, "...共 1536 个数"], "index": 0}],
 "usage": {"prompt_tokens": 4, "total_tokens": 4}}
```

支持批量（`input` 传数组），建库时一次传几十条比逐条调快得多：

```json
{"model": "text-embedding-3-small", "input": ["第一块文本", "第二块文本"]}
```

| 模型 | 维度 | 场景 |
|---|---|---|
| `text-embedding-3-small` | 1536 | 默认选它，便宜够用 |
| `text-embedding-3-large` | 3072 | 精度要求高时 |

**为什么重要**：关键词搜索里「猫」和「喵星人」毫不相干，向量空间里它们很近。
这是 RAG 能召回「说法不同但意思一样」的内容的根本原因。

**注意 Anthropic 没有这个端点**——所以本仓库阶段 6 的 RAG 用了本地哈希实现顶替，
详见 [stage6-notes.md](stage6-notes.md)。要换成真语义检索，就是调这个接口。

---

## `/v1/vector_stores` — 托管向量库

**作用**：把上面「切分 + 向量化 + 存储 + 检索」四步打包成托管服务。你只管传文件，
它自动切分、算向量、建索引。

```bash
# 1. 建库
curl https://api.openai.com/v1/vector_stores \
  -H "Authorization: Bearer $KEY" -d '{"name": "产品手册"}'

# 2. 塞文件（file_id 来自 /v1/files）
curl https://api.openai.com/v1/vector_stores/vs_abc/files \
  -H "Authorization: Bearer $KEY" -d '{"file_id": "file_xyz"}'

# 3. 直接检索
curl https://api.openai.com/v1/vector_stores/vs_abc/search \
  -H "Authorization: Bearer $KEY" -d '{"query": "会员到期后数据保留多久"}'
```

**和本仓库阶段 6 的对应**：`rag_basic.py` 里那五步是自己搭的，好处是每一步都能调
（chunk_size、overlap、k 全在你手里），也能换任何向量库。这个端点是把五步交出去，
省事但参数由平台定。**先手搓一遍再决定要不要托管**，否则出问题不知道该调哪儿。

---

## `/v1/audio/*` — 语音

**作用**：文字转语音（TTS）和语音转文字（ASR）。

```bash
# 转写：音频 → 文字
curl https://api.openai.com/v1/audio/transcriptions \
  -H "Authorization: Bearer $KEY" \
  -F file=@meeting.mp3 -F model=whisper-1

# 合成：文字 → 音频
curl https://api.openai.com/v1/audio/speech \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"tts-1","voice":"alloy","input":"你好，欢迎使用喵星速递。"}' \
  --output hello.mp3
```

还有 `/v1/audio/translations`（转写并翻译成英文）。

---

## `/v1/images/*` — 图像

```bash
curl https://api.openai.com/v1/images/generations \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"gpt-image-1","prompt":"一只戴宇航头盔的橘猫","size":"1024x1024"}'
```

`/v1/images/edits` 传原图 + 蒙版做局部重绘。

---

## `/v1/files` — 文件

**作用**：上传文件，拿到 `file_id` 供其它接口引用。注意 `purpose` 字段决定用途。

```bash
curl https://api.openai.com/v1/files \
  -H "Authorization: Bearer $KEY" \
  -F purpose=assistants -F file=@manual.pdf
```

常见 `purpose`：`batch`（批处理输入）、`fine-tune`（微调数据）、
`assistants`（供向量库/对话引用）。

---

## `/v1/batches` — 批处理

**作用**：异步跑一大批请求，**半价**，24 小时内出结果。

和 Anthropic 的差别：**输入是一个 JSONL 文件**（要先传 `/v1/files`），
不是直接在 body 里放数组。

```bash
# 1. 先把 requests.jsonl 传上去（purpose=batch）
# 2. 提交，指定这批打给哪个端点
curl https://api.openai.com/v1/batches \
  -H "Authorization: Bearer $KEY" \
  -d '{"input_file_id":"file_abc","endpoint":"/v1/chat/completions",
       "completion_window":"24h"}'
```

`endpoint` 可选 `/v1/responses`、`/v1/chat/completions`、`/v1/embeddings`、
`/v1/moderations`、`/v1/images/generations`、`/v1/videos` 等。
单文件上限 5 万条 / 200MB；embeddings 批最多 5 万条输入。

**建库场景很实用**：几万个文块要算向量，走批处理省一半钱。

---

## `/v1/moderations` — 内容审核

**作用**：判断文本或图片是否违规，**免费**。做 UGC 产品时在入口过一道。

```bash
curl https://api.openai.com/v1/moderations \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"omni-moderation-latest","input":"要检查的内容"}'
# → {"results":[{"flagged": false, "categories": {...}, "category_scores": {...}}]}
```

---

## `/v1/realtime` — 实时语音

**作用**：低延迟的语音对语音，走 WebRTC / WebSocket / SIP 长连接，不是普通 HTTP。
做语音助手、电话机器人用它——传统「ASR → LLM → TTS」三段式延迟太高。

---

## 其余端点

| 端点 | 作用 |
|---|---|
| `/v1/videos` | Sora 生成、延长、二次创作视频 |
| `/v1/conversations` | 服务端存对话历史，配合 `/v1/responses` |
| `/v1/containers` | Code Interpreter 的沙箱容器管理 |
| `/v1/fine_tuning/jobs` | 提交微调任务、查进度 |
| `/v1/evals` | 建评测集、跑评测 |
| `/v1/models` | 列出可用模型 |
| `/v1/completions` | 遗留的补全接口，新项目别用 |
| `/v1/organization/*` | 成员、项目、密钥、审计日志（需 Admin key） |

---

## 国内厂商的兼容现状：双轨制

千问、Kimi、智谱、DeepSeek、豆包、MiniMax 这些基本都「兼容」，但要分清**兼容哪一套**。
现在是两条协议线并行：

| | OpenAI 格式 | Anthropic 格式 |
|---|---|---|
| 端点 | `/v1/chat/completions` | `/v1/messages` |
| 地位 | **主线**，所有厂商的默认接口 | 副线，Claude Code 火了之后补的 |
| 为什么做 | 生态里的工具（LangChain、Dify、各种客户端）都先接 OpenAI，照抄等于零成本接入 | 让用户能把 Claude Code 指向自家模型 |
| 地址特征 | 就是厂商的主 API 地址 | 路径里通常带 `anthropic` |

Anthropic 兼容端点举例：

```bash
# 智谱
export ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic
export ANTHROPIC_AUTH_TOKEN=<你的 key>
# Kimi、DeepSeek、Qwen 各有对应地址，查各自文档的「Claude Code」章节
```

**关键**：同一家厂商，这是**两个不同的地址**，不是一个端点两种解析。别把 OpenAI
风格的 base_url 填进 `ANTHROPIC_BASE_URL`——请求体形状对不上，直接报错。

### 「兼容」的水分在哪

厂商说的兼容，通常只保证**对话那一个端点**。周边端点缺得很常见：

| 端点 | 国内厂商覆盖情况 |
|---|---|
| `/v1/chat/completions` | 全都有 |
| `/v1/models` | 基本都有 |
| `/v1/embeddings` | **看厂商**——千问、智谱有；DeepSeek 无（404）；Kimi 无明确官方文档 |
| `/v1/batches` | 少数有 |
| `/v1/audio`、`/v1/images` | 各搞各的，路径和参数经常不一样 |

本仓库遇到的正是这种情况：网关的 `/v1/models` 正常，`/v1/embeddings` 返回 404。
**兼容声明只是起点，用之前先实测**：

```bash
curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/v1/embeddings" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"text-embedding-3-small","input":"hi"}'
```

### 国内可用的 embedding

Anthropic 本来就没有 embedding，但国产厂商里有两家做得不错——**这意味着本仓库阶段 6
的 RAG 完全可以换成真语义检索，不用干等网关**：

| 厂商 | 模型 | 端点 | 备注 |
|---|---|---|---|
| 通义千问 | `text-embedding-v4` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 维度可选 64–2048，单条最长 8192 token，单次最多 10 条 |
| 智谱 | `embedding-3` | `https://open.bigmodel.cn/api/paas/v4` | 维度 256–2048 可调，约 0.5 元/百万 token |
| DeepSeek | 无 | — | 只做 chat，向量得另找 |

换法就是 `rag_basic.py` 里那一行（对话仍走现有的 `ChatAnthropic`，两边各用各的——
LangChain 里 chat model 和 embeddings 本来就是独立组件）：

```python
from langchain_openai import OpenAIEmbeddings

store = InMemoryVectorStore.from_documents(chunks, OpenAIEmbeddings(
    model="text-embedding-v4",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=os.environ["DASHSCOPE_API_KEY"],
))
```

换上之后，「账号注销后资料还在吗」这类**换了说法**的提问才能召回到「会员到期后数据
保留 180 天」——本地哈希实现做不到，见 [stage6-notes.md](stage6-notes.md)。

### 这件事的启示

**选 SDK 看端点形状，不是看模型是谁家的。** 本仓库用 `langchain-anthropic` 能跑通
当前网关，是因为网关吐的是 Anthropic 形状，跟背后到底是不是 Claude 无关。同理，
上面那段 `OpenAIEmbeddings` 指向阿里云也能用——因为阿里提供了 OpenAI 形状的端点。

## 和 Anthropic 的整体对照

| 能力 | OpenAI | Anthropic |
|---|---|---|
| 对话 | `/v1/responses` 或 `/v1/chat/completions` | `/v1/messages` |
| 工具调用 | 上述端点的 `tools` 参数 | `/v1/messages` 的 `tools` 参数 |
| **向量化** | `/v1/embeddings` | **无**（官方建议配 Voyage AI） |
| 托管向量库 | `/v1/vector_stores` | 无 |
| 语音 / 图像 / 视频 | 各自独立端点 | 无（Claude 只能**读**图和 PDF，不能生成） |
| 批处理 | `/v1/batches`（输入是 JSONL 文件） | `/v1/messages/batches`（输入直接放 body） |
| 数 token | 无独立端点 | `/v1/messages/count_tokens` |
| 托管 Agent | `/v1/responses` + `/v1/conversations` | Managed Agents（`/v1/agents` + `/v1/sessions`） |
| 微调 | `/v1/fine_tuning` | 无公开端点 |
| 内容审核 | `/v1/moderations`（免费） | 无（安全内建在模型里） |

**取舍很清楚**：OpenAI 是全家桶，什么模态都有，端点多；Anthropic 专注文本和 Agent，
把能力都塞进一个端点，接口面小但每个参数更深。做多模态产品绕不开 OpenAI，
做纯文本 Agent 两边都行。

---

## 常见坑

- **`/v1/responses` 和 `/v1/chat/completions` 不通用**：请求字段（`input` vs
  `messages`）和响应结构都不同，切换要改代码。
- **兼容网关只是长得像**：很多第三方服务宣称「OpenAI 兼容」，但往往只实现
  `/v1/chat/completions` 和 `/v1/models`，embeddings、批处理经常缺——本仓库遇到的
  正是这种情况（`/v1/embeddings` 返回 404）。**用之前先探测，别假设**。
- **embedding 模型不能混用**：建库和查询必须用同一个模型，否则两组向量不在同一空间，
  算出来的距离没有意义。
- **批处理要先传文件**：和 Anthropic 直接放 body 不同，这里得先过一次 `/v1/files`。

---

**一句话**：OpenAI 按能力拆端点、模态全；Anthropic 一个 `/v1/messages` 打天下。
对照见 [api-anthropic.md](api-anthropic.md)。

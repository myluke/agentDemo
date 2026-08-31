# Implementation Notes

技术决策记录，按日期倒序。记「为什么、边界、契约与安全语义、坑」；
架构现状与生效规则见 [CLAUDE.md](CLAUDE.md)。

---

## 2026-08-31 — 补充向量存储与 FAISS/Milvus 边界

**做了什么**：在阶段 6 笔记中补充向量记录、近邻检索和 ANN 索引的职责，并区分 FAISS、Milvus、Chroma、pgvector 与内存向量存储的定位和适用场景。

**为什么这么做**：FAISS 常被笼统称作“向量数据库”，但它实际是进程内向量检索库；Milvus 才是提供持久化、metadata 过滤、服务化和分布式能力的向量数据库。明确边界后，能避免把 embedding、索引算法和数据库能力混为一谈，也避免教学 demo 过早引入独立基础设施。

**边界**：所有这些工具只负责存储和近邻搜索，不能替代 embedding 模型；已有 PostgreSQL 或 Elasticsearch 时应优先复用 pgvector 或 dense_vector/kNN，规模和运维需求超出已有系统后再引入 Milvus 等独立服务。

---

## 2026-08-31 — LangSmith 可观测性独立为阶段 7

**做了什么**：将 LangSmith tracing 从“各 demo 顺带演示”提升为独立阶段 7，原工具调用和 Agent 顺延为阶段 8、9；路线图增加配置、trace 层级、标签/metadata、故障与耗时定位、隐私边界及完成标准。

**为什么这么做**
- tracing 不只是环境变量开关；要真正用于调试，必须会读父子 run、区分模型与检索耗时，并从错误节点还原输入输出。
- 在工具调用和 Agent 循环之前学习可观测性，后续面对多步执行时已有定位手段，不必靠终端日志猜测。
- 单独使用 `OPENAI_LOG=debug` 只能观察底层 SDK/HTTP 日志，不能替代 LangChain 运行图、步骤级耗时和 token 统计。

**边界 / 安全**
- tracing 是旁路观测能力，关闭后不得改变链的业务结果；自检不能依赖 LangSmith 网页或远端 trace 已上传。
- Prompt、响应、检索片段和 metadata 都可能离开本机；密钥不得写入 tags/metadata，个人或业务敏感数据上线前必须考虑脱敏、采样、访问权限和保留策略。
- `LANGSMITH_TRACING=true` 只负责启用追踪；远端上传还依赖有效的 API key、endpoint/project 配置和网络。

---

## 2026-08-30 — 凭据集中到 llm.py，全量切换 OpenAI 协议

**做了什么**：新增 `llm.py` 统一构造模型客户端并读凭据；`hello.py` / `multi_step_chain.py` / `structured_output.py` / `parallel_branch.py` / `chat_memory.py` / `rag_basic.py` / `rag_hybrid.py` 全部由 `ChatAnthropic` 换成 `openai_chat()`（`ChatOpenAI` + 网关 `/v1`）；requirements 去掉 `langchain-anthropic`。

**为什么这么做**

- 同一段「api_key 二选一 + base_url」在 6 个文件里各抄一遍，换网关要改 6 处。集中到一处后，demo 只声明「我要哪个模型」，凭据是基础设施不是教学内容。
- 网关同时兑现两套协议，但混着用会让「换模型」这件事分裂成两条路径。统一走 OpenAI 协议后，`openai_chat("gpt-5.4")` 和 `openai_chat("gpt-5.4-mini")` 是同一个调用，各阶段只差模型名。

**边界与坑**

- **配置优先级 config.ini > 环境变量**：`config.ini` 不入库（`.gitignore`），模板见 `config.ini.example`。不建 config.ini 也能跑，回落到原来的 `ANTHROPIC_*` 环境变量（变量名保留，因为网关就是这么发的凭据）。
- **ini 值带引号必须剥**：configparser 不剥引号，`base_url = "https://..."` 会原样带引号拼进 URL，httpx 报 `UnsupportedProtocol: missing http://`。`_conf()` 里 `.strip().strip("\"'")` 兜住这个坑。
- **base_url 的 `/v1`**：Anthropic 协议直连根路径，OpenAI 协议要 `/v1`。这个后缀拼在 `openai_chat()` 内部，调用方不该关心。
- **structured_output.py 的调试钩子换了层级**：`ChatAnthropic` 是 `model._client._client`，`ChatOpenAI` 要走 `model.root_client._client`（root_client 是底层 `openai.OpenAI`，再取它的 httpx 客户端）。调试日志环境变量同步 `ANTHROPIC_LOG` → `OPENAI_LOG`。
- **`reasoning_effort` 档位表变了**：Anthropic 是 `low|medium|high|xhigh|max`，OpenAI 侧只到 `high`，注释已同步；`chat_memory.py` 用的 `low` 两边都有效。
- **默认模型 `llm.MODEL`**：`openai_chat()` 不传 model 就用它（`config.ini` 的 `model` 键，默认 `gpt-5.4`），换主力模型改一处。只有真需要小模型的场合才显式传名——`rag_basic` 的复述、`parallel_branch` 的分类器、`rag_hybrid` 的 reranker 用 `gpt-5.4-mini`，这是有意的成本选择，不能被默认值吞掉。
- **默认推理档位 `llm.EFFORT`**（`config.ini` 的 `reasoning_effort` 键，默认 `low`）：不传就是模型自己的默认档（偏高＝更慢更贵），这些 demo 都是小活，统一压到 low；要深想的场合调用时显式覆盖。
- 七个 demo 逐个实跑，自检断言全过。

## 2026-08-30 — RAG 混合检索与重排

**做了什么**：新增 `rag_hybrid.py`，在基础 RAG 上演示 BM25 关键词检索、向量检索、RRF（Reciprocal Rank Fusion）融合和 rerank；更新 `rag_basic.py`，抽出两路共用的字符 bigram 切词函数；同步路线图和阶段 6 笔记。

**为什么这么做**
- 纯向量检索对同义表达友好，但会弱化专有名词、编号和罕见 token；BM25 的 TF/IDF 恰好擅长精确词匹配。两路并行可以覆盖互补的失败模式。
- 向量相似度和 BM25 分数没有可比的量纲，直接加权相加需要为每批语料调权重；RRF 只看名次，免除分数归一化和权重调参，适合教学和作为生产默认起点。
- 召回阶段取较大的候选集，目标是“不漏答案”；再用 cross-encoder 或 LLM reranker 精排，目标是“把最有用的少数片段交给模型”，减少上下文稀释和 token 消耗。
- 当前环境没有 `langchain-community` 的 BM25Retriever、也没有本地 cross-encoder 推理服务，因此用零依赖 BM25 和已有 Claude Haiku 结构化输出演示相同的接口形状；生产应优先使用 bge-reranker-v2-m3 等本地 cross-encoder。

**边界 / 契约 / 安全**
- `rag_hybrid.py` 复用基础 RAG 的内存语料和 `LocalEmbeddings`，只演示排序机制；它仍然是单进程、重启丢失、教学级字面 embedding，不是可直接承载业务的知识库。
- BM25、向量路和融合的候选数（当前 5、RRF 后 4、精排后 2）只是样本参数；生产用真实问题集分别评测 recall@k、MRR、nDCG、答案忠实度和延迟再调参。
- 文档内容是不可信输入。重排 prompt 明确要求把候选当数据而不是执行指令；生产生成 prompt 还应保留来源、文档版本和引用，并对 prompt injection 做隔离测试。
- 权限过滤必须在 BM25 和向量检索前或检索库内部按 metadata 下推，不能先召回再在模型层“希望它别泄露”；tenant/user 权限是服务端鉴权逻辑，不是 prompt 约束。

**坑**
- `bigrams` 同时用于哈希向量和 BM25，避免两路因切词不同产生虚假的对比；它仍不是中文分词器，换真实 embedding/BM25 服务时应按模型和语料选择 tokenizer。
- RRF 不能修复两路都没召回答案的问题；解析质量、chunk 边界、metadata 过滤仍是上游硬门槛。
- LLM reranker 成本和延迟高于 cross-encoder，且结构化输出只保证编号格式，不保证排序判断正确；候选编号越界时代码会过滤并保留前几项兜底。

---

## 2026-08-29 — LCEL 基础 RAG

**做了什么**：新增 `rag_basic.py`，完整演示加载、递归切分、向量化、内存向量检索和 grounded generation；检索器作为 Runnable 直接接入 LCEL。新增 `langchain-text-splitters` 和 `numpy` 依赖，并完成阶段 6 文档同步。

**为什么这么做**
- 使用 `RecursiveCharacterTextSplitter` 而不是手写切片：它优先在自然边界断开，`chunk_overlap` 避免答案跨切口丢失。
- 使用 core 自带的 `InMemoryVectorStore`：本阶段只学 RAG 数据流，不提前引入 Chroma/数据库及其生命周期。
- 当前 `ANTHROPIC_BASE_URL` 网关的 `/v1/embeddings` 返回 404，Gemini embedding 网关不可达；因此实现最小 `LocalEmbeddings`（字符 bigram 哈希词袋）以跑通标准 `Embeddings` 接口，而不是伪造可用的远端服务。
- 提示词强制“只依据资料，缺失则明确说不知道”，降低模型越过检索上下文自行补全的风险。

**边界 / 契约**
- `LocalEmbeddings` 衡量字面片段重叠，不理解同义词；它只用于教学，生产应替换成真实语义 embedding。替换时 vector store、retriever 和 LCEL 链无需改动。
- Python 的内置 `hash()` 跨进程种子不同，但同一进程内建库与查询一致；`InMemoryVectorStore` 本来也不跨进程持久化。若持久化向量，必须同时使用稳定哈希或真正 embedding 模型。
- `InMemoryVectorStore` 进程退出即丢，适合小型 demo；生产按数据量和过滤需求换持久化向量库。
- `k=3` 是教学样本的召回参数，不是通用最优值；真实系统需用评测集调 chunk size、overlap、k，并测召回率与回答忠实度。
- “只用资料”是提示约束而非安全边界；外部文档仍是不可信输入，生产 RAG 要处理 prompt injection、访问控制和来源引用。

**坑**
- `InMemoryVectorStore` 的余弦相似度实现依赖 `numpy`，缺失时在第一次检索抛 `ImportError`，因此必须显式列入依赖。
- 检索命中不代表生成一定正确；自检确定性验证最关键的召回环节，真实运行另行观察“资料缺失”问题不被模型猜答。

---
## 2026-08-29 — 记忆 demo 使用低推理档位

**做了什么**：`chat_memory.py` 的 `ChatAnthropic` 显式设置 `reasoning_effort="low"`。

**为什么这么做**：本 demo 只验证消息累积和线程隔离，不需要深度推理；`low` 比默认 `high` 更快、更省 token，同时不改变记忆机制。

**边界**：`reasoning_effort` 控制模型推理投入，不控制 `InMemorySaver`、消息历史或 `thread_id` 隔离；复杂任务应按实际质量评估提高档位。

## 2026-08-29 — LangGraph checkpointer 多轮记忆

**做了什么**：新增 `chat_memory.py`，用 `MessagesState` + `StateGraph` + `InMemorySaver` 实现按 `thread_id` 隔离的多轮对话记忆；加入 `langgraph` 依赖，并完成阶段 5 文档同步。

**为什么这么做**
- `langchain-core` 1.6.1 的 `RunnableWithMessageHistory` 已从 1.3.3 起弃用，官方明确指向 LangGraph；core 内没有未弃用的等价 LCEL wrapper，因此本阶段按决策破例采用 LangGraph 的 checkpointer。
- 选裸 `StateGraph` 而不是 `create_react_agent`：只展示状态累积、消息历史和线程隔离，不提前混入工具调用或 Agent 循环；后两者分别留给阶段 7、8。
- `MessagesState` 自带 `add_messages` reducer；节点只需把累计消息喂给模型并返回新的 AI 消息，checkpointer 负责跨轮保存状态。

**边界 / 契约**
- `graph.invoke` 必须传 `configurable.thread_id`；同一 `thread_id` 共享历史，不同 `thread_id` 逻辑隔离。
- `InMemorySaver` 只存进当前 Python 进程的内存，进程退出即丢；生产环境应换持久化 saver（如 Postgres/SQLite），并处理连接、迁移和生命周期。
- `thread_id` 只是状态分区键，不是鉴权边界；真实服务必须在服务端校验当前用户是否有权访问该 thread，不能直接信任外部传入的 ID。
- 本阶段是单节点、单步 workflow，不包含工具、循环、自主决策；不把「记住名字」等模型输出当作事实验证。

**坑**
- 忘传 `thread_id` 会使 checkpointer 无法定位会话并直接报错。
- 必须复用同一个已挂载 checkpointer 的 compiled graph；换新 `InMemorySaver` 或进程后，内存历史自然消失。

---

## 2026-08-29 — 按任务拆分分类与回复模型

**做了什么**：`parallel_branch.py` 为分类器增加 `claude-haiku-4-5`，只吐枚举标签的情绪/类别链使用 `fast`；生成自然语言回复的分支继续使用 `claude-opus-4-8` 的 `model`。

**为什么这么做**
- 分类任务输出短、结构固定，Haiku 足够；回复任务需要更好的自然语言质量，保留 Opus。
- 两类任务分开绑定模型，避免用高能力模型承担简单分类的额外成本和延迟。

**边界**
- Haiku 不是语义正确性的保证；结构化输出只约束格式和枚举取值，实际分类仍需用真实样本评估。

## 2026-08-29 — 并行分类改用结构化输出

**做了什么**：`parallel_branch.py` 的情绪和类别分类器改用 `with_structured_output`，分别通过 `Sentiment` / `Category` 的 `Literal` 枚举约束标签，并把 Pydantic 对象映射为字符串后再进入 `RunnableBranch`。

**为什么这么做**
- 原先依赖“只回一个词”的提示词，模型返回 `"投诉。"` 或 `"类别：投诉"` 时会让精确路由静默走兜底。
- `Literal` 让表外标签在结构化解析阶段被校验拒绝，下游 `x["category"] == "投诉"` 的契约更可靠。
- `method="function_calling"` 沿用阶段 3 的网关兼容结论；当前网关不兑现 `json_schema` 约束。

**边界 / 安全**
- 结构化输出约束的是字段格式和枚举取值，不等于保证模型对含糊反馈的语义判断正确；模型能力、提示词和输入质量仍会影响分类结果。
- 自检只验证路由谓词和 Pydantic 枚举校验，不替代真实模型评估。

## 2026-08-28 — 开启模型请求调试日志

**做了什么**：`structured_output.py` 在导入模型客户端前设置 `ANTHROPIC_LOG=debug`，运行 demo 时会输出 SDK 发出的请求参数、目标 URL、状态码与响应头。

**边界 / 安全**
- SDK debug 日志不打印 HTTP 响应 body；响应内容仍通过 `include_raw=True` 查看解析前的 `AIMessage`。
- 请求 body 会出现在终端日志中，可能含业务输入和 schema，生产不应常开；外部已设置 `ANTHROPIC_LOG` 时用 setdefault 不覆盖。

---

## 2026-08-28 — 并行分类 & 条件分支

**做了什么**：新增 `parallel_branch.py`，用 `RunnableParallel` 并发判断情绪+类别，再用 `RunnableBranch` 按类别路由到投诉/咨询/兜底回复。整链 `analyze | RunnablePassthrough.assign(reply=route)`。

**为什么这么做**
- 情绪和类别两次判断互不依赖，`RunnableParallel` 并发跑，一次完整链 invoke 内发起两个并发模型请求，总耗时≈较慢的那条（串行则约等于两者相加）。
- 末段用 `.assign(reply=route)` 而非 `analyze | route`：后者只返回回复字符串，会丢掉并行阶段的 sentiment/category；前者沿用阶段 2 语义，把回复追加进同一字典，中间态与回复都可见。

**边界 / 契约**
- 输入必须含 `feedback`；输出含 `sentiment`、`category`、`feedback`、`reply` 四键。
- `RunnableParallel` 每条子链都收到完整输入字典，故用 `itemgetter("feedback")` 只取原文；写 `RunnablePassthrough()` 会把整个输入字典塞进 `feedback`，导致模板 `{feedback}` 看到字典文本。
- `RunnableBranch` 按书写顺序检查条件，首个命中即停；顺序即业务优先级；全不命中走兜底。
- 分类器契约是只回指定标签；输出经 `str.strip()` 归一化去掉换行，但**有意不解析同义词/标点**——若模型返回 `"投诉。"` 会走兜底（教学 demo 不做过度解析）。
- 这是确定性 workflow，路由规则写死，不是自主决策的 Agent。

**坑**
- 分类输出末尾换行会让 `x["category"] == "投诉"` 精确比较失败而误走兜底，故必须 `.strip()`。
- 使用 `RunnablePassthrough` 需在 import 显式引入，否则 `NameError`。
- 自检直接检查真实 `route` 的条件谓词，但不调用各回复分支；`py_compile` 和该自检都不覆盖「真实模型分类是否正确」，须真实运行眼看分类命中（本次已验证：崩溃→投诉、会员到期→咨询）。

---

## 2026-08-28 — 招聘信息结构化输出

**做了什么**：新增 `structured_output.py`，用 `with_structured_output(JobPosting)` 将自由文本直接抽取成经 Pydantic 校验的对象。

**为什么这么做**
- Pydantic schema 同时定义字段、类型和含义，省掉提示模型输出 JSON 后再手写解析与校验。
- 显式使用 `method="function_calling"`（也是本版本默认值）：当前自定义 gateway 未兑现 Anthropic 原生 `json_schema` 约束，实测会返回自定义中文键并导致校验失败，而 tool calling 能按 schema 稳定返回。

**边界 / 契约**
- 输入必须含 `posting`；输出是 `JobPosting` 实例，而不是字符串或裸字典。
- `min_salary_k` 是可选字段；其余字段必填。原文缺少公司名时，模型可返回空字符串，但不得编造。
- 结构化输出保证形状和类型，不保证内容事实正确；信任边界上的业务数据仍需独立验证。
- 如果 gateway 后续完整支持 Anthropic 原生 structured output，可切回 `method="json_schema"`。

---

## 2026-08-28 — 两步观点反驳链

**做了什么**：新增 `multi_step_chain.py`，依次生成观点、再反驳该观点，并一次返回话题与两个步骤的结果。

**为什么这么做**
- 用两个 `RunnablePassthrough.assign` 保存中间输出，直观展示“前一步输出成为后一步输入”。
- 完整链只调用一次；内部仍会产生两次模型请求，避免为了打印中间结果而把第一步重复调用。

**边界 / 契约**
- 输入必须含 `topic`；输出包含 `topic`、`opinion`、`rebuttal`。
- 两步串行执行，第二步依赖第一步；任一步失败都会使整条链失败。
- 这是固定流程的 workflow，不是会自主选择步骤或工具的 Agent。

---

## 2026-08-28 — LangChain Hello World 骨架

**做了什么**：`hello.py` 用 LCEL 链 `prompt | model | StrOutputParser` 调 `claude-opus-4-8`。

**为什么这么做**
- 用 `langchain-anthropic` 的 `ChatAnthropic` 而非直接 SDK：演示 LangChain 本身，
  这是 demo 的目的。简单场景 LangChain 是负担，但这里就是要展示框架。
- 凭证 `api_key=ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY`、`base_url=ANTHROPIC_BASE_URL`：
  本机走自定义网关 + AUTH_TOKEN，不是 Anthropic 默认端点，故不能依赖 SDK 默认的
  `ANTHROPIC_API_KEY` 自动发现。

**边界 / 契约**
- 无 `.env`，凭证假定已在 shell 环境中；缺失时 `os.environ[...]` 直接抛 KeyError（有意，
  让失败早且明确）。
- 单次 `invoke`，无流式、无重试、无对话记忆——超出 demo 范围。

**坑**
- `ANTHROPIC_BASE_URL` 已设时，若仍用 `ANTHROPIC_API_KEY` 路径会打到默认端点鉴权失败；
  必须显式传 AUTH_TOKEN。

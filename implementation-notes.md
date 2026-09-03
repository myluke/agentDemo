# Implementation Notes

技术决策记录，按日期倒序。记「为什么、边界、契约与安全语义、坑」；
架构现状与生效规则见 [CLAUDE.md](CLAUDE.md)。

---

## 2026-09-03 — `s06_rag_chroma.py`：向量库换 Chroma，兼修 `hash()` 加盐坑

**做了什么**：新增 `s06_rag_chroma.py`（阶段 6 番外，不进阶段表），复用
`s06_rag_basic` 的 `LocalEmbeddings` / `chunks` / `format_docs`，只把第 4 步的
`InMemoryVectorStore` 换成 `Chroma(persist_directory="chroma_db")`。同时把
`LocalEmbeddings._vec` 的 `hash(g)` 改成 `zlib.crc32(g.encode())`（这是对
`s06_rag_basic.py` 的唯一改动）。requirements 加 `langchain-chroma==1.1.0` /
`chromadb==1.5.9`，`.gitignore` 加 `chroma_db/`。

**为什么加这个 demo**：阶段 6 的注释一直写着「换 Chroma/PGVector 只改这一行」，
但没有实物。摆一个真换过的版本，读者能直接看到 `Embeddings` 与 `VectorStore`
两个接口一分开的收益：换库只动建库那行，`as_retriever()` 之后的链一个字不用改。
顺带带出内存库演示不了的东西——**持久化**。demo 的文档只有 6 块、嵌入是本地哈希，
重算无感；真实项目嵌入要调外部 API，按 token 收费、有速率限制，几万块文档重算
是实打实的钱和分钟。所以文件里写了「集合非空就跳过嵌入」的分支，这个分支在内存库
里根本无从写起。

**`hash()` 加盐坑的来龙去脉**：原实现 `v[hash(g) % self.dim] += n` 在内存库下
完全正确——建库和查询在同一进程，盐相同，同一 bigram 永远落同一个桶。改成落盘后
第二次运行开始检索全空：CPython 对 `str` 的 hash 默认随机加盐（PYTHONHASHSEED，
PEP 456，防哈希碰撞 DoS），**新进程的盐不同，同一 bigram 落到完全不同的维度**，
查询向量与库里文档向量几乎正交，点积趋近 0。要命的是它不报错，只是永远搜不到，
是典型的静默失效。凡是要落盘、要跨进程复现的哈希都不能用内置 `hash()`。

**为什么选 crc32**：只要「确定性 + 均匀分桶」两条，不要密码学强度（这里没有攻击者
构造碰撞的场景）。`zlib.crc32` 在标准库里、纯 C 实现比 `hashlib` 快一个量级、
直接返回 int 不用再从摘要里切字节。`hashlib.md5(...).digest()` 也对，但要多绕
一层字节转整数，且 md5 在某些合规扫描里会误报。固定 `PYTHONHASHSEED=0` 同样能修，
但那是要求调用方配环境变量，把库的正确性外包给运行环境，不接受。

**为什么 `chroma_db/` 不入库**：向量是源文档 + 嵌入实现的派生物，随时可重新生成，
和 `__pycache__/` 一个性质。入库还有两个坏处：SQLite 二进制文件 diff 不可读，
每次跑 demo 都产生噪声改动；换嵌入实现后库里是旧向量，反倒会误导。

**边界**：只判集合空不空，不判内容版本——源文档改了不会自动重建。真实项目的做法是
给每块算内容哈希当 id、用 upsert 覆盖变更块，文件里留了 `ponytail:` 注释标记。
`s06_rag_hybrid.py` 未动，仍走内存库 + BM25。

---

## 2026-09-03 — 课程文件统一加 `sNN_` 阶段前缀

**做了什么**：11 个教程 demo 用 `git mv` 加阶段号前缀——`hello.py` → `s01_hello.py`，
`multi_step_chain` → `s02_`，`structured_output` → `s03_`，`parallel_branch` → `s04_`，
`chat_memory` → `s05_`，`rag_basic` / `rag_hybrid` → 同为 `s06_`（同属阶段 6），
`langsmith_tracing` → `s07_`，`tools` → `s08_`，`agent_graph` → `s09_`，
`web_agent` → `s10_`（ROADMAP 的番外）。三条跨 demo import 链同步改名；
CLAUDE.md / ROADMAP.md / README.md / AGENTS.md / agent-questions.md / `docs/*.md`
的文件名与相对链接全量更新。

**为什么**：文件名不带序号时，`ls` 出来是字母序，看不出学习顺序；查「阶段 7 是哪个
文件」得回 ROADMAP 对照。前缀让目录列表本身就是路线图。

**为什么是 `s` 前缀而不是纯数字（`01_hello.py`）**：这些 demo **互相 import**——
`s06_rag_hybrid` → `s06_rag_basic`、`s09_agent_graph` → `s08_tools`、
`s10_web_agent` → `s09_agent_graph`。Python 标识符不能以数字开头，`01_hello` 不是
合法模块名，`import 01_hello` 直接 SyntaxError（只能 `importlib` 绕，为了个文件名
不值得）。`s` 前缀让编号和可 import 两者兼得。

**`llm.py` 不编号**：它不是某一阶段的教学内容，是所有阶段共用的凭据与客户端工厂，
没有对应的阶段号可给。不编号本身就是「这是基础设施，不是课程」的信号。

**顺带解决的同名冲突**：根目录的 `tools.py` 曾与 `harness/tools.py` 同名不同物，
`harness/harness.py` 必须用 `sys.path.append`（而非 `insert(0)`）才能保证
`import tools` 命中本地那个。根文件更名 `s08_tools.py` 后冲突消失，但 `append`
的语义（根只需「能被找到」以 import `llm`）仍然更准，保留不改，注释改写成历史说明。

**边界**：`harness/` 目录内一律不动——它是主线的对照组，不进阶段表，没有阶段号。
`harness/tools.py` 保持原名，`harness/harness.py` 的 `from tools import ...` 保持
指向本地。`config.ini*` 同样不动。本条以下的历史条目里出现的旧文件名不做替换，
那是当时的事实记录。

---

## 2026-09-03 — harness/：不用框架裸写一遍 HTTP agent loop

**做了什么**：新增 `harness/`（`tools.py` ~110 行 + `harness.py` ~165 行 + README），
只用 `requests` + 标准库实现 agent 循环、工具注册分发、结果回灌、compaction、
危险工具确认门五件套。零新依赖，不动 requirements。ROADMAP「为什么用框架」节末尾
加了指向；**不进阶段表**（同 web_agent.py 的番外定位）。

**为什么这么做**

- ROADMAP 那节论证「框架买到的不是能力，是不用你写」，但一直只有文字。裸写一份
  同形状的实物摆在旁边，读者能直接对比：`ToolNode` 展开就是「遍历 tool_calls、
  execute、拼 `{"role":"tool"}`」十行，`bind_tools` 展开就是手写一份 JSON Schema。
  形状没变，省的是抄写。
- **schema 与执行体同源**：注册表一张表同时存 `fn`/`description`/`parameters`/
  `dangerous`。分两处放迟早对不上——改了函数签名忘改 schema，模型按旧 schema 传参，
  炸在运行时。框架用类型注解自动推正是在解这个问题。
- **不做流式/并发/沙箱**：本 demo 讲 loop 的形状，SSE 会把主线淹没在解析里；
  并行 tool_calls 串行执行本来就合法，串行更好读。

**契约与安全语义**

- **错误也回灌**：`dispatch()` 用 `except Exception` 把异常转成 `"错误：..."` 字符串。
  模型看见「文件不存在」能换路径重试；抛异常则整个循环当场炸掉，它永远不知道
  发生了什么。坏 JSON 参数（模型偶发）同样当工具错误回灌，不崩。
- **拒绝也回灌**：确认门被拒时**不执行**，但把「用户拒绝了此次工具调用」当作 tool
  结果塞回去。静默跳过会让模型以为工具没返回，抛异常同上。这是确认门的正确语义：
  拒绝是一个**结果**，不是一个故障。
- **EOF 按拒绝处理**：管道输入耗尽时 `input()` 抛 `EOFError`，接住并返回 False。
  没人回答 ≠ 默许，安全默认必须是拒绝。
- `run_shell` 无沙箱无白名单，安全边界只有那道确认门，README 写明仅本机学习用。

**两个坑（都真踩了）**

- **`sys.path` 必须用 append 不是 insert(0)**：`python harness/harness.py` 时
  `sys.path[0]` 是 `harness/`。按常规写 `insert(0, 仓库根)` 会把根排到前面，
  `import tools` 命中阶段 8 那个（顺带拖进 LangChain + rag_basic），不是本地的。
  根只需「能被找到」以 import `llm`，所以 append。已验证命中 `harness/tools.py`
  且 `sys.modules` 里无 langchain。
- **compaction 不能劈开 tool_calls 配对**：保留尾 8 条时，若切点恰好落在
  `role:"tool"` 上，它的 assistant(tool_calls) 父消息被切进摘要区 → 孤儿 tool
  消息 → 网关 400。定好 cut 后 `while messages[cut]["role"]=="tool": cut -= 1`
  往前退。反向不会发生（tool 结果永远紧跟其 assistant，切前缀不会留下无结果的 assistant）。

**测试时发现并修掉的一个真问题**：SYSTEM 最初写「run_shell 每次调用都需要用户
当场确认」，模型据此**先用文字问一遍**「是否运行？」，等于两道门，管道输入下还会
把 `y` 喂给对话而不是确认门，造成误拒。改成「不要用文字请求许可，直接调用，
本程序会拦下来」——**确认权归 harness 不归模型**，提示词不能把宿主的职责推给模型。

**边界**：无流式、无并发工具、无参数校验；compaction 是「摘要中间段」的朴素策略，
不做重要性排序。

---

## 2026-09-03 — web_agent.py：等待响应时显示「正在思考…」占位行

**做了什么**：提交后立即 `add('wait', '正在思考…')` 插入占位行（CSS 闪烁动画），
收到响应或请求失败时 `wait.remove()` 移除；`add()` 改为返回创建的 DOM 节点。

**为什么这么做**

- `/chat` 不是流式（见 2026-09-02 条目），`ask()` 秒级起步，等待期页面除了输入框
  变灰外零反馈，用户无法区分「在跑」和「挂了」。占位行是流式落地前的最小补丁。
- 用 `add()` 返回节点引用来移除，而不是查 DOM 或维护全局状态——占位行的生命周期
  就是这一次提交的闭包，引用天然随之存亡。
- **坑**：失败路径（catch）也必须 remove，否则请求出错时「正在思考」永远挂在页面上。

**边界**：占位只表示「请求在途」，不反映 Agent 内部进度；逐跳实时可见仍需
SSE/WebSocket，属于既定的下一步，不在本次范围。

---

## 2026-09-02 — 番外：web_agent.py，把阶段 9 的图挂到 HTTP 上

**做了什么**：新增 `web_agent.py`（FastAPI + 内嵌 HTML，约 130 行），
`GET /` 返回页面、`POST /chat` 跑一轮 Agent；requirements 补 `fastapi` / `uvicorn`；
CLAUDE.md 补运行命令；ROADMAP 加「番外」小节（阶段 1–9 状态不动，这不是新阶段）。

**为什么这么做**

- **复用 `agent_graph.ask()` 而不是重建图**：`ask()` 已经封好「invoke + 按 thread_id
  记忆 + 只返回本轮新增消息」。在 web 层再建一次图等于把阶段 9 抄一遍，而且两份图各有
  各的 InMemorySaver，终端和网页的记忆会分裂。复用链本身就是这个仓库的教学价值
  （阶段 6 retriever → 阶段 8 工具 → 阶段 9 图 → 番外的 HTTP 层），复制会把线索抹掉。
- **`hops()` 的分类照搬 `show()`**：终端里 `show()` 是 print，这里是 JSON，同一份
  「有 tool_calls / `type=="tool"` / `type=="ai" and content」三分支，两个出口。页面把
  中间跳也渲染出来是有意的——Agent 的教学重点是「它转了几圈、自己选了什么工具」，
  只显示最终答案就退化成一个普通问答框。
- **`/chat` 用同步 `def`**：`ask()` 内部是阻塞的网关 HTTP 调用（秒级）。FastAPI 见到
  普通 `def` 会丢进线程池，事件循环照常接别的请求；写成 `async def` 却在里面跑阻塞
  代码，一个人提问就卡死整个服务。「不会 await 就别写 async」在这里是硬规则。
- **不做流式**：SSE/WebSocket 留作下一步。先让「每一跳可见」成立，流式是体验优化，
  不改变本 demo 要展示的结构。

**契约**

- `POST /chat` 收 `{"text": str, "thread_id": str}`（pydantic 校验，缺字段或类型不对
  由 FastAPI 挡成 422），返回 hop 列表，元素三选一：
  `{"type":"call","name":...,"args":{...}}` / `{"type":"result","content":...}` /
  `{"type":"answer","content":...}`。顺序即 Agent 的执行顺序。
- `GET /` 返回内嵌 HTML 字符串（无 static 目录、无模板引擎、无前端框架）。

**thread_id 语义**

- 浏览器端 `crypto.randomUUID()` 生成，存页面变量不落 storage：**刷新即新会话**，
  两个标签页各记各的——阶段 5 的 thread 隔离在这里变成可操作的实物。
- 它仍是**分区键不是鉴权**（同阶段 5/9 的警告）：接口没有任何归属校验，谁都能填
  别人的 id 读到那个 thread 的上下文。真要上线，thread 归属必须服务端鉴权。
- 记忆在 `InMemorySaver` 里 = 进程内存：**服务重启即失忆**，且多 worker 会让记忆按
  进程分裂（所以 `uvicorn.run` 单进程、不开 `--reload`、不配 workers）。

**边界与坑**

- **仅本机学习用**：绑 `127.0.0.1`，无鉴权、无限流、无 CORS（同源，不需要）。
  暴露到公网等于把网关 key 的调用能力和别人的会话历史一起开放。
- **前端一律 `textContent` 赋值，不用 `innerHTML`**：用户输入和模型输出都是不可信
  文本，工具结果还可能带 RAG 语料里的内容（阶段 6 笔记里「文档是不可信输入」同款）。
  拼 HTML 就是一个现成的 XSS。
- **用 `<form onsubmit>` 而不是监听 keydown**：回车提交是原生行为，白拿。
- **import `agent_graph` 会连带跑 `tools` → `rag_basic` 的模块级建库**（切分 + 向量化），
  本地实现毫秒级，所以启动时会有一次静默的建库，属已知代价（见 2026-09-01 条）。

---

## 2026-09-01 — 阶段 7/8/9 一次交付：可观测性、工具调用、Agent

**做了什么**：新增 `langsmith_tracing.py`（阶段 7）、`tools.py`（阶段 8）、
`agent_graph.py`（阶段 9），路线图三阶段全部标 ✅；requirements 补 `langsmith`；
CLAUDE.md 补运行命令与 demo 间的 import 依赖。

**为什么这么做**

- **阶段 7 用 `collect_runs()` 而不是「配 key 看网页」**：路线图的完成标准要求
  「demo 带不依赖网络 UI 的最小自检」。`collect_runs()` 拿到的是**同一棵 run 树**
  （`LANGSMITH_TRACING` 只决定它上不上传），所以层级、耗时、token、错误节点这四件
  要学的东西全能在本地断言。要看网页版只需设三个环境变量，代码一行不改。
- **阶段 8 手写循环而不是直接上 `create_react_agent`**：ReAct 的全部内容就是
  「tool_calls → 执行 → ToolMessage 回灌」。先手写一遍看清消息形状，阶段 9 换成
  `ToolNode` 时才知道预制件替掉的是哪几行；反过来先上预制件，循环就成了黑盒。
- **demo 之间直接 import 复用**：`tools.py` 的 `search_policy` 直接 import
  `rag_basic` 的 retriever，`agent_graph.py` 直接 import `tools` 的 `TOOLS` 和已
  bind 的 model。这是有意的——教学价值恰恰在「阶段 6 的检索器原样成为阶段 8 的
  工具、阶段 8 的工具原样进阶段 9 的图」，复制一份会把这条线索抹掉。
  代价：import `rag_basic` 会执行它的模块级建库（切分 + 向量化），本地实现，
  毫秒级，可接受。

**边界与坑**

- **tracing 是旁路**：`LANGSMITH_TRACING` 默认在 `langsmith_tracing.py` 里
  `setdefault("false")`，没有 key 也跑得通；自检显式断言它是 `false`，
  「关掉上传业务结果照常」这件事本身就被测住了。
- **`run.error` 带完整 traceback**：打印时要截到第一行之前，否则 run 树被整段
  traceback 冲垮。walk() 里按 `Traceback` 切。
- **token 的位置**：只有 `run_type == "llm"` 的 run 有，且在
  `outputs["llm_output"]["token_usage"]`（`prompt_tokens` / `completion_tokens`）。
  chain 节点没有，别在父节点上找。
- **`max_turns` 不是可选装饰**：工具报错时模型很容易反复重试，没有上限就是无限
  循环烧 token。阶段 8 手写循环和阶段 9 的图都需要这个护栏（图那边靠
  `recursion_limit`，默认 25）。
- **`tool_call_id` 必须对上**：一次响应可能带多个 tool_call（并行调用），每个都要
  回一条 ToolMessage，模型靠 id 把结果和调用单配对，漏一条下一跳就报错。
- **system 提示不进 state**：`agent_graph.py` 的 `agent()` 每次现拼
  `[SYSTEM] + state["messages"]`。存进 state 会被 checkpointer 跟着消息历史反复
  持久化，且多轮后可能被截断策略误伤。
- **图成环的判据**：自检直接读 `graph.get_graph().edges` 断言存在
  `("tools", "agent")` 这条回边——没有它就退化成单向链，Agent 名存实亡。
- **网关行为已验证**：`bind_tools` 的 tool_call 格式、并行调用、闲聊时不调工具，
  三个 demo 实跑，自检断言全过。

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

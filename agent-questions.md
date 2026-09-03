# Agent 工程七问

> 记录于 2026-09-03。这是评估一个 Agent 系统成熟度的七个核心问题,
> 每题附本仓库对应的实践位置,便于对照复习。

## 1. Agent 是固定工作流,还是有规划、决策、循环执行能力?

- **固定工作流 (Workflow)**:步骤在代码里写死,LLM 只填空。可预测、易调试、成本可控。
  - 本仓库:阶段 2–4(`s02_multi_step_chain.py`、`s04_parallel_branch.py`)。
- **自主 Agent**:LLM 在循环中自行决定调哪个工具、何时停止(ReAct 模式:
  思考 → 行动 → 观察 → 再思考)。
  - 本仓库:阶段 8 `s08_tools.py` 手写 tool loop;阶段 9 `s09_agent_graph.py` LangGraph ReAct;
    `harness/harness.py` 裸写循环。
- **判断标准**:控制流由谁决定。写死在代码里 = workflow;由模型输出(tool_calls / 终止信号)决定 = agent。
- **工程共识**:能用 workflow 就不用 agent。自主性越高,可靠性越难保证。

## 2. 有没有状态管理、短期记忆、长期记忆?

- **状态管理**:单次运行内的结构化状态(消息列表、中间结果)。LangGraph 用 State + reducer。
- **短期记忆**:多轮对话历史。阶段 5 `s05_chat_memory.py` 用 LangGraph checkpointer
  按 `thread_id` 隔离会话;超长时用 `trim_messages` 截断或摘要压缩
  (`harness/` 的 `compact()` 是手写版摘要压缩)。
- **长期记忆**:跨会话持久化——向量库存事实、文件/DB 存用户偏好,检索时按需注入。
  本仓库尚未覆盖(checkpointer 落盘即最简形态)。

## 3. 工具调用失败后怎么重试、回退和人工接管?

- **重试**:区分可重试错误(超时、429、5xx)与不可重试(参数错、权限)。指数退避 + 上限次数。
- **回退 (fallback)**:换备用工具/备用模型/降级为纯文本回答;或把错误信息作为
  ToolMessage 回灌给模型让它自己调整参数重试(本仓库 tool loop 即此做法)。
- **人工接管 (human-in-the-loop)**:危险操作前设确认门。
  - 本仓库:`harness/` 危险工具 `[y/N]` 确认,拒绝也把拒绝结果回灌进历史;
    LangGraph 有 `interrupt` 原生支持。

## 4. 有没有 RAG、向量检索、Rerank 和知识库权限过滤?

- **基础 RAG**:切块 → 向量化 → top-k 检索 → 塞 prompt。阶段 6 `s06_rag_basic.py`。
- **混合检索**:向量(语义)+ BM25(关键词)并联,RRF 融合。`s06_rag_hybrid.py`。
- **Rerank**:粗召回 top-50 后用 cross-encoder 精排取 top-5,显著提准。`s06_rag_hybrid.py`。
- **权限过滤**:检索时按用户身份过 metadata filter(ACL),**必须在检索层做**,
  不能靠 prompt 叮嘱模型"别看无权文档"。本仓库未覆盖,生产必答项。

## 5. 如何做 Agent 评测、Tracing、成功率统计和成本监控?

- **Tracing**:记录每次运行的完整调用树(每步 LLM 输入输出、工具调用、耗时、token)。
  阶段 7 `s07_langsmith_tracing.py`:本地 `collect_runs` 拿 run tree,LangSmith 上传可选。
- **评测**:固定评测集 + 自动判分(精确匹配 / LLM-as-judge / 工具调用轨迹比对),
  每次改 prompt 或换模型跑回归。
- **成功率统计**:任务级(端到端完成率)与步骤级(单次工具调用成功率)分开统计。
- **成本监控**:token 用量 × 单价,按 trace 聚合;设告警阈值防死循环烧钱。

## 6. 是否做过 MCP、LangGraph、LangChain、LlamaIndex?

- **LangChain (LCEL)**:阶段 1–4、6–8 主线,链式编排、结构化输出、并行分支。
- **LangGraph**:阶段 5(checkpointer 记忆)、阶段 9(ReAct 图)。图 = 显式状态机,
  适合带循环/分支/中断的 agent。
- **裸写对照**:`harness/` 零框架重写同一循环,验证框架到底封装了什么。
- **MCP**:标准化工具/资源协议,让工具服务与 agent 解耦(client-server)。
  本仓库未实现,但 `harness/tools.py` 的 `@register` 注册表 + `dispatch()`
  就是 MCP tool listing/calling 的精神雏形。
- **LlamaIndex**:偏重 RAG/数据接入的框架,与 LangChain 定位重叠,理解概念即可。

## 7. 如何处理幻觉、超时、重复调用和死循环?

- **幻觉**:RAG 提供依据 + 要求引用来源;结构化输出收窄自由度;关键结论二次校验
  (LLM-as-judge 或规则);允许模型说"不知道"。
- **超时**:每次 LLM/工具调用设 timeout;整个任务设 wall-clock 上限。
- **重复调用**:对幂等工具做结果缓存;检测"同一工具+同一参数"连续出现即拦截;
  写操作要求幂等键。
- **死循环**:最大迭代步数硬上限(LangGraph `recursion_limit`;手写循环里的
  max turns);超限后降级为"总结现状交还用户"而非报错丢弃。

---

## 一句话总结

这七问覆盖 Agent 系统的完整生命周期:**架构选型(1)→ 状态与记忆(2)→
容错(3)→ 知识接入(4)→ 可观测与评测(5)→ 技术栈(6)→ 安全护栏(7)**。
面试时按"概念 → 权衡 → 本仓库/项目实践"三段作答。

"""LangSmith 可观测性演示：从 trace 回答「哪一步慢、哪一步错、模型实际看到了什么」。

前六阶段链越拼越长，出问题时只能 print 猜。tracing 补的是这一层：
每个 Runnable 跑一次就是一个 **run**，父子嵌套成一棵树，每个节点自带
输入、输出、耗时、token、错误。

三个开关别混为一谈：
- `LANGSMITH_TRACING=true`：把 run 树**上传**到 LangSmith 网页（要 API key + 网络）。
- `collect_runs()`：把同一棵 run 树**留在本地**内存里，不上传、不要 key。
  上传与否只影响你在哪看，链的业务结果完全一样——本文件的自检就卡这条。
- `OPENAI_LOG=debug`（阶段 3 用过）：OpenAI SDK 的 HTTP 日志，看的是单次请求的
  报文；它不知道「链」的存在，给不出父子层级和步骤耗时。两者互补，不互替。

关键点：
- `.with_config(run_name=...)` 给节点起名，否则树上全是 `RunnableSequence`。
- `tags` / `metadata` 在 invoke 时传，用来在 LangSmith 里筛选（如按环境、按版本）。
- run 树里 llm 节点的 `outputs["llm_output"]["token_usage"]` 就是 token 账单。
"""
import os

# 默认关闭上传：没有 key 也能跑通本文件。要看网页版就在环境里设 true + LANGSMITH_API_KEY。
os.environ.setdefault("LANGSMITH_TRACING", "false")

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.tracers.context import collect_runs
from langchain_core.tracers.schemas import Run

from llm import openai_chat

model = openai_chat(max_tokens=1024)

# 一条两步链，故意分两个模型调用，好在 trace 上看出「哪一步慢」。
# with_config(run_name=...) 是纯观测配置，不改行为——去掉它链照跑，只是树上没名字。
draft = (
    ChatPromptTemplate.from_messages([("human", "用一句话介绍「{topic}」。")])
    | model
    | StrOutputParser()
).with_config(run_name="draft")

polish = (
    ChatPromptTemplate.from_messages([("human", "把这句话改得更精炼：{text}")])
    | model
    | StrOutputParser()
).with_config(run_name="polish")

chain = (draft | polish).with_config(run_name="intro-writer")


def walk(run: Run, depth: int = 0) -> None:
    """打印 run 树：名字、类型、耗时、token、错误。这就是 LangSmith 网页上那棵树。"""
    cost = (run.end_time - run.start_time).total_seconds() if run.end_time else -1
    line = f"{'  ' * depth}{run.name} [{run.run_type}] {cost:.2f}s"

    # token 只有 llm 类型的 run 才有；结构见 ChatOpenAI 回填的 llm_output。
    usage = (run.outputs or {}).get("llm_output", {}).get("token_usage") if run.outputs else None
    if usage:
        line += f"  tokens in/out={usage['prompt_tokens']}/{usage['completion_tokens']}"
    if run.error:
        line += f"  ❌ {run.error.split(chr(10))[0].split('Traceback')[0]}"
    print(line)
    for child in run.child_runs:
        walk(child, depth + 1)


def trace(runnable, payload, **config) -> Run:
    """跑一次并把这次的 run 树留在本地，返回根 run。失败也返回（错误记在树上）。"""
    with collect_runs() as cb:
        try:
            runnable.invoke(payload, config=config)
        except Exception:
            pass  # 异常本身已记进 run.error，这里只为让 trace 能被检查
    return cb.traced_runs[0]


if __name__ == "__main__":
    # —— 成功的一次：看层级、耗时、token ——
    # tags / metadata 是筛选维度，在 LangSmith 里按它们过滤运行。
    # 安全边界：prompt、响应、metadata 都会随 tracing 上传，密钥和个人数据一律不放这里。
    root = trace(
        chain,
        {"topic": "向量数据库"},
        tags=["stage7", "demo"],
        metadata={"env": "local", "stage": 7},
    )
    print("=== 成功运行的 run 树 ===")
    walk(root)
    print(f"tags={root.tags}  metadata={root.extra['metadata']}\n")

    # —— 失败的一次：错误落在哪个节点上，一眼可见 ——
    # 插一个必炸的节点，模拟真实链里某一步解析/后处理挂掉。
    def boom(_):
        raise ValueError("下游解析失败（模拟）")

    broken = (draft | RunnableLambda(boom).with_config(run_name="post-process")).with_config(
        run_name="intro-writer-broken"
    )
    bad_root = trace(broken, {"topic": "向量数据库"}, tags=["stage7", "failure"])
    print("=== 失败运行的 run 树（❌ 标出错误节点）===")
    walk(bad_root)

    # —— 自检：全部离线，不依赖 LangSmith 网页或网络上传 ——
    # 1) 层级：根下面挂着 draft 和 polish 两个命名节点，这是「哪一步慢」的前提。
    names = [c.name for c in root.child_runs]
    assert names == ["draft", "polish"], f"层级不对：{names}"
    # 2) token：llm 节点确实带账单，才谈得上按步骤看成本。
    llm_runs = [r for r in root.child_runs[0].child_runs if r.run_type == "llm"]
    assert llm_runs and llm_runs[0].outputs["llm_output"]["token_usage"]["total_tokens"] > 0
    # 3) 错误定位：根记了错，但真正的错误节点是 post-process，不是 draft。
    failed = [r for r in bad_root.child_runs if r.error]
    assert [r.name for r in failed] == ["post-process"], f"错误节点定位错：{failed}"
    assert bad_root.child_runs[0].error is None, "draft 成功了，不该被标错"
    # 4) 旁路语义：tracing 关着（LANGSMITH_TRACING=false）业务结果照常——上面这几次
    #    invoke 全是在关闭上传的前提下跑出来的，能拿到 run 树本身就是证明。
    assert os.environ["LANGSMITH_TRACING"] == "false"
    print("\n[self-check] 层级/token/错误定位正确，且不依赖上传 ✓")

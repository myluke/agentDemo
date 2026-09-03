"""裸写的 agent harness：只有 requests + 标准库，没有 LangChain。

ROADMAP「为什么用框架？裸写不行吗？」那节的实物对照。框架把 agent loop 的形状
显式化了，代价是形状藏在对象背后；这里反过来——形状裸露在 HTTP/JSON 层，
你能看见每一跳到底发出去了什么。

五个零件，各自对应框架里的什么：

| 裸写的这段              | 框架里是                                        |
|-------------------------|-------------------------------------------------|
| `while` 主循环 + MAX_TURNS | LangGraph 的 tools→agent 回边 + 递归上限      |
| REGISTRY + tool_schemas() | `@tool` 装饰器 + `bind_tools`                 |
| dispatch + 拼 role:"tool" | `ToolNode`                                    |
| `compact()`             | checkpointer 旁的 `trim_messages` / 上下文管理  |
| `confirm()` 确认门      | Claude Code 的 permission prompt（**框架里没有**，得自己写） |

与阶段 8 `tools.py` 是同一个形状：那边靠 `AIMessage` / `ToolMessage` 对象，
这边连消息封装都没有，就是 dict 进 dict 出。看懂这份，再回头看 `agent_graph.py`
那张图，会发现 LangGraph 只是把这个 while 循环换了个说法。
"""
import json
import sys
from pathlib import Path

import requests

# 注意是 append 不是 insert(0)——仓库根有阶段 8 的 tools.py（会拖进 LangChain +
# rag_basic）。insert(0) 会把根排到 harness/ 前面，`import tools` 就被那个劫持了。
# append 只让根「能被找到」以 import llm，harness/ 仍排在前，tools 正确命中本地。
sys.path.append(str(Path(__file__).parent.parent))

from llm import API_KEY, BASE_URL, EFFORT, MODEL  # noqa: E402
from tools import REGISTRY, dispatch, tool_schemas  # noqa: E402

# BASE_URL 不含 /v1（llm.py 里是在 openai_chat 中拼的），这里自己补上
URL = BASE_URL + "/v1/chat/completions"
MAX_TURNS = 10  # 安全阀：模型可能反复要求调工具，没上限就是无限循环烧 token
KEEP_RECENT = 8  # compaction 保留的尾部消息条数
COMPACT_AT = 30  # 超过这个条数触发压缩

SYSTEM = {
    "role": "system",
    "content": (
        "你是一个本地命令行助手。可用工具：get_time（查当前时间）、"
        "read_file（读文件）、run_shell（执行 shell 命令）。"
        "run_shell 是危险操作，但**不要用文字向用户请求许可**——直接发起调用，"
        "本程序会自动拦下来让用户确认。若结果是「用户拒绝了此次工具调用」，"
        "不要重试同一条命令，直接告诉用户你没有执行。"
    ),
}


def call_api(messages: list[dict]) -> dict:
    """一次 POST，返回 choices[0].message（原样，含 content: null）。"""
    r = requests.post(
        URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": messages,
            "tools": tool_schemas(),
            "reasoning_effort": EFFORT,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def confirm(name: str, args: dict) -> bool:
    """危险工具的确认门。框架里没有这层，是 harness 自己的职责。"""
    if not REGISTRY.get(name, {}).get("dangerous"):
        return True
    print(f"  ⚠️  危险操作：{name}({json.dumps(args, ensure_ascii=False)})")
    try:
        return input("  执行？[y/N] ").strip().lower() == "y"
    except EOFError:
        # 管道输入耗尽时不能崩，也不能默许——没人回答就是没批准。
        print("  (无输入，按拒绝处理)")
        return False


def compact(messages: list[dict]) -> list[dict]:
    """历史过长时把中间段压成一条摘要。看得见的上下文管理。"""
    if len(messages) <= COMPACT_AT:
        return messages

    cut = len(messages) - KEEP_RECENT
    # 关键：切点不能落在 tool 消息上。tool 结果必须紧跟它的 assistant(tool_calls)，
    # 把父消息切进摘要区会留下孤儿 tool 消息，网关直接 400。往前退到配对之外。
    while cut > 0 and messages[cut]["role"] == "tool":
        cut -= 1

    head, middle, tail = messages[:1], messages[1:cut], messages[cut:]
    if not middle:
        return messages

    summary = call_api([
        {"role": "system", "content": "把下面的对话历史压缩成一段简明摘要，保留结论、数字和用户意图。"},
        {"role": "user", "content": json.dumps(middle, ensure_ascii=False)[:8000]},
    ])
    print(f"  (已压缩 {len(middle)} 条旧消息)")
    return head + [{"role": "user", "content": "[前文摘要] " + (summary.get("content") or "")}] + tail


def agent_turn(messages: list[dict]) -> list[dict]:
    """一轮对话：调模型 → 有 tool_calls 就执行回灌 → 再问，直到模型给出答案。"""
    messages = compact(messages)
    for _ in range(MAX_TURNS):
        msg = call_api(messages)
        messages.append(msg)  # assistant 消息原样回填（含 content: null），别自己重拼

        calls = msg.get("tool_calls")
        if not calls:  # 不再要工具 = 收工
            print(f"助手> {msg.get('content')}")
            return messages

        for call in calls:
            name = call["function"]["name"]
            raw = call["function"]["arguments"]
            try:
                args = json.loads(raw or "{}")
            except json.JSONDecodeError as e:
                # 模型偶尔吐坏 JSON。当成工具错误回灌，它自己会重来一次。
                result = f"错误：参数不是合法 JSON（{e}）：{raw}"
                args = {}
            else:
                print(f"  → 调用 {name}({json.dumps(args, ensure_ascii=False)})")
                if confirm(name, args):
                    result = dispatch(name, args)
                else:
                    # 拒绝也要回灌。让模型知道「被拒了」它才能换路或如实告诉用户；
                    # 静默跳过会让它以为工具没结果，抛异常则整个循环炸掉。
                    result = "用户拒绝了此次工具调用"
                print(f"  ← {result[:100]}{'…' if len(result) > 100 else ''}")
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],  # 必须对上，模型靠它把结果和调用单配对
                "content": result,
            })

    print(f"助手> （{MAX_TURNS} 轮仍未收敛，已强制收尾）")
    return messages


def main() -> None:
    messages = [SYSTEM]
    print("裸写 agent harness。输入 exit 退出。")
    while True:
        try:
            text = input("你> ").strip()
        except EOFError:
            break
        if text in ("exit", "quit"):
            break
        if not text:
            continue
        messages.append({"role": "user", "content": text})
        messages = agent_turn(messages)
    print("再见。")


if __name__ == "__main__":
    main()

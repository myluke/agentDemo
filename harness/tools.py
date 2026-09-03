"""工具注册表：不依赖任何框架，也不依赖凭据（不 import llm）。

对照阶段 8 的 `tools.py`：那边 `@tool` 装饰器从类型注解和 docstring 自动推 schema，
这边**手写** JSON Schema 塞进注册表。这就是框架替你省掉的那部分——省的是抄写，
不是能力，形状完全一样。

三张表合一（函数、schema、危险标记）是有意的：工具的「怎么执行」和「怎么描述给模型」
必须同源，分开放两处迟早对不上（改了参数忘改 schema，模型按旧 schema 传参，炸在运行时）。
"""
import datetime
import subprocess

REGISTRY: dict[str, dict] = {}


def register(description: str, parameters: dict, dangerous: bool = False):
    """把函数登记进 REGISTRY：执行体、给模型看的描述、要不要过确认门。"""
    def deco(fn):
        REGISTRY[fn.__name__] = {
            "fn": fn,
            "description": description,
            "parameters": parameters,
            "dangerous": dangerous,
        }
        return fn
    return deco


def tool_schemas() -> list[dict]:
    """注册表 → OpenAI `tools` 数组。dangerous 是本地概念，不发给模型。"""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for name, t in REGISTRY.items()
    ]


def dispatch(name: str, args: dict) -> str:
    """按名字执行工具，**异常一律转成错误字符串**而不是往上抛。

    这是工具循环的关键语义：模型看见「错误：文件不存在」能换个路径重试；
    抛异常则整个循环当场炸掉，模型永远不知道发生了什么。
    错误也是信息，也要回灌——同「用户拒绝」那条（见 harness.py 的确认门）。
    """
    tool = REGISTRY.get(name)
    if tool is None:  # 模型偶尔会幻觉出不存在的工具名
        return f"错误：没有名为 {name} 的工具"
    try:
        return str(tool["fn"](**args))
    except Exception as e:
        return f"错误：{type(e).__name__}: {e}"


NO_ARGS = {"type": "object", "properties": {}}


@register("获取当前的日期和时间。问到「现在几点」「今天几号」时用这个。", NO_ARGS)
def get_time() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@register(
    "读取一个文本文件的内容（最多前 2000 字符）。",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件路径"}},
        "required": ["path"],
    },
)
def read_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read(2000)


@register(
    "执行一条 shell 命令并返回输出。列目录、查进程等系统操作用这个。",
    {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}},
        "required": ["command"],
    },
    dangerous=True,  # → harness.py 里会拦下来问用户
)
def run_shell(command: str) -> str:
    # ponytail: 无沙箱、无命令白名单，安全边界全靠那道确认门；要上生产得换成受限执行器
    r = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=10
    )
    return (r.stdout + r.stderr).strip() or f"(无输出，退出码 {r.returncode})"


if __name__ == "__main__":
    # 1) schema 形状对得上 OpenAI 的 tools 数组，且 dangerous 没漏进去给模型。
    schemas = tool_schemas()
    assert len(schemas) == len(REGISTRY) == 3, schemas
    for s in schemas:
        assert s["type"] == "function" and {"name", "description", "parameters"} <= s["function"].keys()
        assert "dangerous" not in s["function"], "dangerous 是本地概念，不该发给模型"
    # 2) 零参数工具能跑通。
    assert dispatch("get_time", {}) and "错误" not in dispatch("get_time", {})
    # 3) 关键语义：工具内部出错时返回错误字符串**而不抛**，循环才能继续。
    out = dispatch("read_file", {"path": "/nope/does/not/exist"})
    assert out.startswith("错误："), out
    assert dispatch("不存在的工具", {}).startswith("错误："), "未知工具也该软失败"
    # 4) 危险标记在位——确认门靠它决定拦不拦。
    assert REGISTRY["run_shell"]["dangerous"] is True
    assert REGISTRY["get_time"]["dangerous"] is False
    print("[self-check] schema 形状/错误软失败/危险标记 ✓")

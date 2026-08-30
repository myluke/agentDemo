"""模型客户端与凭据的唯一出处。

凭据原先在 6 个 demo 里各抄一遍（api_key 二选一 + base_url），改网关要改 6 处。
这里集中读 config.ini，各 demo 只管说「我要哪个模型」。

配置优先级：config.ini > 环境变量。config.ini 不入库（见 .gitignore），
照着 config.ini.example 复制一份填进去即可；不建也行，环境变量照旧生效。
"""
import configparser
import os
from pathlib import Path

_cfg = configparser.ConfigParser()
_cfg.read(Path(__file__).parent / "config.ini", encoding="utf-8")


def _conf(key: str, *env_keys: str) -> str:
    """config.ini 的 [api] 段优先，回落到按顺序给的环境变量。"""
    val = _cfg.get("api", key, fallback="").strip().strip("\"'")  # ini 里带引号也照收
    return val or next((os.environ[k] for k in env_keys if os.environ.get(k)), "")


# api_key：网关自定义的 ANTHROPIC_AUTH_TOKEN 优先，没有再退回官方 ANTHROPIC_API_KEY
API_KEY = _conf("api_key", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
# base_url：Anthropic 原生协议直接用；OpenAI 协议要在后面补 /v1（见下）
BASE_URL = _conf("base_url", "ANTHROPIC_BASE_URL")
# 默认模型：绝大多数 demo 用它，换模型改这里（或 config.ini）一处即可
MODEL = _conf("model") or "gpt-5.4"
# 推理档位：low | medium | high。不传就是模型自己的默认（通常偏高＝更慢更贵），
# 这些 demo 都是小活，统一压到 low；个别要深想的场合调用时显式覆盖。
EFFORT = _conf("reasoning_effort") or "low"

if not API_KEY:
    raise RuntimeError("缺少 api_key：填 config.ini 的 [api] 段，或设 ANTHROPIC_AUTH_TOKEN")


def openai_chat(model: str = MODEL, reasoning_effort: str = EFFORT, **kwargs):
    """走 OpenAI 协议的客户端（中转站的 /v1 根路径）。model / 推理档位不传就用默认值。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        reasoning_effort=reasoning_effort,
        api_key=API_KEY,
        base_url=BASE_URL + "/v1",
        **kwargs,
    )

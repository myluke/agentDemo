# harness/ — 不用框架，裸写一个 agent

ROADMAP [「为什么用框架？裸写不行吗？」](../ROADMAP.md#为什么用框架裸写不行吗)
那节的实物对照。只有 `requests` + 标准库，零新依赖。

```bash
.venv/bin/python harness/harness.py   # REPL，输入 exit 退出
.venv/bin/python harness/tools.py     # 工具层自检
```

## 五个零件

| 零件 | 一句话 | 框架里是 |
|---|---|---|
| **循环** | `while` 转到模型不再要工具，`MAX_TURNS=10` 兜底 | LangGraph 的 tools→agent 回边 |
| **注册分发** | `@register` 登记函数 + schema + 危险标记，`dispatch()` 按名执行 | `@tool` + `bind_tools` |
| **结果回灌** | 执行结果包成 `{"role":"tool","tool_call_id":...}` 塞回消息数组 | `ToolNode` |
| **压缩** | 超 30 条时把中间段请模型压成摘要，保留 system + 尾 8 条 | `trim_messages` |
| **确认门** | 危险工具执行前 `[y/N]`，拒绝则回灌「用户拒绝了此次工具调用」 | **框架里没有**，得自己写 |

两条贯穿的语义：**错误也回灌、拒绝也回灌**。模型看见「错误：文件不存在」或
「用户拒绝」能换路重试或如实交代；抛异常则整个循环炸掉，静默跳过则它以为工具没结果。

对照阶段 8 `../s08_tools.py`：同一个形状，那边是 `AIMessage`/`ToolMessage` 对象，
这边连消息封装都没有，dict 进 dict 出。

**仅本机学习用**：`run_shell` 无沙箱、无命令白名单，安全边界就是那道确认门
（同 `s10_web_agent.py` 只绑 127.0.0.1 的定位）。

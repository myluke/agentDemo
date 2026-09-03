"""Web Agent 演示（番外）：给阶段 9 的图套一层 HTTP，让 Agent 的每一跳在浏览器里可见。

本文件**只加了一层 HTTP**。图、工具、记忆一行没重写：`ask()` 来自阶段 9 的
`s09_agent_graph`，而它内部又是阶段 8 的工具、阶段 6 的 retriever、阶段 5 的
checkpointer。九个阶段的零件原样搬上网页——这就是仓库一路复用下来的那条线。

唯一的真变化是 **thread_id 的来源**：阶段 5、9 里它是代码写死的 "demo"，这里改成
浏览器打开页面时 `crypto.randomUUID()` 生成一个。于是刷新即新会话、两个标签页各记
各的——阶段 5 讲的 thread 隔离，终于有了看得见的实物。

两个刻意的选择：

- **`/chat` 用同步 `def` 而不是 `async def`**：`ask()` 里是阻塞的 HTTP 调用（等网关
  返回，几秒起步）。FastAPI 见到普通 `def` 会把它丢进线程池，事件循环照常接别的请求；
  写成 `async def` 却在里面跑阻塞代码，一个人提问就卡住整个服务。「不会 await 就别写
  async」在这里是硬规则，不是风格偏好。
- **不做流式**：SSE / WebSocket 是下一步。先让「每一跳可见」这件事成立——中间的
  tool_call 和工具结果都渲染出来，Agent 就不再是一个只吐最终答案的黑盒问答框。

边界：无鉴权、无限流、只绑 127.0.0.1，本机学习用。thread_id 是**分区键不是鉴权**
（同阶段 5/9 的警告），谁都能填别人的 id；记忆在 InMemorySaver 里，进程重启即失忆。
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from s09_agent_graph import ask  # 阶段 9 的图，原样复用：不重建、不复制它的逻辑

app = FastAPI()


class Ask(BaseModel):
    """入参 schema。信任边界上的校验交给 pydantic，缺字段/类型不对由 FastAPI 挡成 422。"""

    text: str
    thread_id: str


def hops(messages: list) -> list:
    """把本轮消息翻成前端能渲染的「跳」——分类与 `s09_agent_graph.show()` 完全一致。

    终端里 show() 是 print，这里是 JSON：同一份分类逻辑，两个出口。
    """
    out = []
    for m in messages:
        if getattr(m, "tool_calls", None):
            out += [{"type": "call", "name": c["name"], "args": c["args"]} for c in m.tool_calls]
        elif m.type == "tool":
            out.append({"type": "result", "content": m.content})
        elif m.type == "ai" and m.content:
            out.append({"type": "answer", "content": m.content})
    return out


@app.post("/chat")
def chat(req: Ask) -> list:
    """同步 def：ask() 是阻塞调用，交给 FastAPI 的线程池，别堵事件循环（见顶部）。"""
    return hops(ask(req.text, req.thread_id))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


# 页面内嵌在这里：一个 demo 不值得为它建 static 目录、上模板引擎或前端框架。
PAGE = """
<title>Web Agent</title>
<style>
  body { max-width: 44rem; margin: 2rem auto; padding: 0 1rem; font-family: system-ui }
  #log > div { margin: .5rem 0; white-space: pre-wrap }
  .me { text-align: right; color: #06c }
  .call, .result { color: #999; font: .8rem/1.5 ui-monospace, monospace }
  .wait { color: #999; animation: blink 1s infinite alternate }
  @keyframes blink { to { opacity: .3 } }
  form { display: flex; gap: .5rem }
  input { flex: 1; padding: .5rem }
</style>
<div id="log"></div>
<form id="f"><input id="q" autofocus placeholder="问点什么…"><button>发送</button></form>
<script>
// 每个标签页一个 thread_id：刷新 = 新会话，开两个窗口 = 两份互不相干的记忆。
const tid = crypto.randomUUID();
const log = document.getElementById('log'), q = document.getElementById('q');

function add(cls, text) {
  const d = document.createElement('div');
  d.className = cls;
  d.textContent = text;   // 不用 innerHTML：用户输入和模型输出都是不可信文本
  log.appendChild(d);
  d.scrollIntoView();
  return d;   // 调用方可留着引用，用于稍后移除（如「正在思考」占位行）
}

document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();     // 用 <form> 是为了白拿原生的回车提交，不用自己监听按键
  const text = q.value.trim();
  if (!text) return;
  add('me', text);
  q.value = ''; q.disabled = true;
  // 占位行：/chat 不是流式，等待期整个页面否则毫无反馈。收到响应后移除。
  const wait = add('wait', '正在思考…');
  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, thread_id: tid }),
    });
    const data = await r.json();
    wait.remove();
    // 三种跳分开渲染：调用和结果弱化成灰色小字，答案正常展示。
    // 目的就是让「Agent 转了几圈、调了什么工具」留在页面上，而不是只剩最后一句话。
    for (const h of data) {
      if (h.type === 'call') add('call', `↳ 调用 ${h.name}(${JSON.stringify(h.args)})`);
      else if (h.type === 'result') add('result', `↳ 结果 ${h.content}`);
      else add('answer', h.content);
    }
  } catch (err) {
    wait.remove();   // 失败路径同样要清掉占位，否则「正在思考」会永远留在页面上
    add('result', `请求失败：${err}`);
  } finally {
    q.disabled = false; q.focus();
  }
};
</script>
"""

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

"""多步链演示：上一步的输出，自动喂给下一步。

流程：话题 → [第1步] 生成一个观点 → [第2步] 反驳这个观点
关键点：第2步的输入来自第1步的输出；一次普通 API 请求只能完成其中一步。
"""
import os

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

model = ChatAnthropic(
    model="claude-opus-4-8",
    max_tokens=1024,
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)

# 第1步：就 {topic} 生成一个鲜明的观点
step1_argue = (
    ChatPromptTemplate.from_messages(
        [
            ("system", "你是一个观点鲜明的辩手，用一句话给出你的观点。"),
            ("human", "关于「{topic}」，给我一个观点。"),
        ]
    )
    | model
    | StrOutputParser()  # 抠成纯字符串，才能喂给下一步
)

# 第2步：反驳「上一步生成的那个观点」
step2_rebut = (
    ChatPromptTemplate.from_messages(
        [
            ("system", "你是一个唱反调的辩手，用一句话反驳对方观点。"),
            ("human", "对方观点是：{opinion}。请反驳。"),
        ]
    )
    | model
    | StrOutputParser()
)

# 把两步接起来：
# 第一个 assign 运行 step1，并把结果保存到 "opinion"。
# 第二个 assign 读取这个 "opinion"，运行 step2，再把结果保存到 "rebuttal"。
# 最终会得到：{"topic": 原话题, "opinion": 第1步结果, "rebuttal": 第2步结果}。
full_chain = (
    RunnablePassthrough.assign(opinion=step1_argue)
    | RunnablePassthrough.assign(rebuttal=step2_rebut)
)

if __name__ == "__main__":
    topic = "AI 会取代程序员"

    # 只调用一次完整链；两次模型请求会在链内部依次完成。
    result = full_chain.invoke({"topic": topic})

    print(f"【话题】{result['topic']}")
    print(f"【第1步·观点】{result['opinion']}\n")
    print(f"【第2步·反驳】{result['rebuttal']}")

"""LangChain Hello World: prompt | model | parser（提示词 | 模型 | 解析器）。"""
import os

# ChatAnthropic：调用 Claude 模型的客户端
from langchain_anthropic import ChatAnthropic
# StrOutputParser：把模型返回的消息对象抽成纯字符串
from langchain_core.output_parsers import StrOutputParser
# ChatPromptTemplate：用模板拼「系统提示 + 用户输入」的对话
from langchain_core.prompts import ChatPromptTemplate

# 1) 创建模型客户端
model = ChatAnthropic(
    model="claude-opus-4-8",   # 用哪个模型
    max_tokens=1024,           # 回复最多生成多少 token
    # api_key：优先读自定义网关的 ANTHROPIC_AUTH_TOKEN，没有再退回官方的 ANTHROPIC_API_KEY
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    # base_url：接口地址，指向自定义网关（不是 Anthropic 默认地址）
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)

# 2) 用 | 把三步串成一条链（LCEL 语法）：模板 → 模型 → 取字符串
#    数据从左往右流：先套模板，再交给模型，最后解析成纯文本
chain = (
    ChatPromptTemplate.from_messages(
        [
            ("system", "你是一个简洁的助手，用一句话回答。"),  # 系统角色：定基调
            ("human", "{question}"),                          # 用户提问，{question} 是占位符
        ]
    )
    | model
    | StrOutputParser()
)

# 3) 只有直接运行本文件时才执行（被 import 时不跑）
if __name__ == "__main__":
    # invoke：把 {question} 填进模板并触发整条链，打印模型回答
    print(chain.invoke({"question": "用一句话解释什么是 LangChain？"}))

"""并行 & 分支演示：并发抽取，再按结果条件分流。

场景：一条用户反馈进来 →
  [并行] 同时判断「情绪」和「类别」（两次判断互不依赖，可并发）→
  [分支] 按类别路由到不同的回复策略（投诉 / 咨询 / 其它）。

关键点：
- RunnableParallel：多个子链并发执行，结果合并成一个字典（省掉串行等待）。
- RunnableBranch：按 (条件, 分支) 依次匹配，命中即走那条分支，末尾是兜底。
- 分类用阶段 3 的结构化输出：Literal 枚举在类型层面锁死标签，分支比较才安全。
"""
import os
from operator import itemgetter
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBranch, RunnableParallel, RunnablePassthrough
from pydantic import BaseModel, Field, ValidationError

_creds = dict(
    max_tokens=1024,
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)

# 回复要写人话，用 Opus；两个分类器只吐一个枚举标签，Haiku 足够且更快更便宜。
model = ChatAnthropic(model="claude-opus-4-8", **_creds)
fast = ChatAnthropic(model="claude-haiku-4-5", **_creds)


class Sentiment(BaseModel):
    """情绪分类结果。"""

    label: Literal["正面", "负面", "中性"] = Field(description="这条反馈的情绪")


class Category(BaseModel):
    """类别分类结果。"""

    label: Literal["投诉", "咨询", "其它"] = Field(description="这条反馈的类别")


def classifier(system: str, schema: type[BaseModel]):
    """造一个「读 {feedback}、返回 schema 里那个枚举标签」的小分类链。

    用 with_structured_output 而不是靠提示词约束格式：Literal 枚举参与工具
    schema，模型填不出表外的值，也就没有 "投诉。" / "类别：投诉" 这类漂移，
    下游 x["category"] == "投诉" 的精确比较才立得住。
    method 沿用 structured_output.py 的结论：当前网关不兑现 json_schema。
    """
    return (
        ChatPromptTemplate.from_messages(
            [("system", system), ("human", "{feedback}")]
        )
        | fast.with_structured_output(schema, method="function_calling")
        | (lambda x: x.label)  # 只把标签字符串带下去，后面的模板和条件都按字符串用
    )


# —— 并行段：情绪 + 类别 两次判断互不依赖，并发跑 ——
# dict 里每个值都是一条子链；RunnableParallel 会同时触发，结果合并成
# {"sentiment": ..., "category": ..., "feedback": 原文}。
analyze = RunnableParallel(
    sentiment=classifier("判断这条反馈的情绪。", Sentiment),
    category=classifier("判断这条反馈的类别。", Category),
    feedback=itemgetter("feedback"),  # 只取原文字符串带下去（RunnablePassthrough 会塞整个字典）
)


def reply(system: str):
    """按不同策略回复用户；输入是并行段合并出的那个字典。"""
    return (
        ChatPromptTemplate.from_messages(
            [
                ("system", system),
                ("human", "用户反馈：{feedback}\n（情绪：{sentiment}）"),
            ]
        )
        | model
        | StrOutputParser()
    )


# —— 分支段：按 category 路由 ——
# RunnableBranch 依次检查每个 (条件函数, 分支)；条件函数收到的是整个字典。
# 第一个返回 True 的就走对应分支；全不命中走最后的兜底分支。
route = RunnableBranch(
    (lambda x: x["category"] == "投诉", reply("你是客服，先共情致歉，再给一句解决方向。")),
    (lambda x: x["category"] == "咨询", reply("你是客服，直接、清楚地回答用户的疑问。")),
    reply("你是客服，礼貌回应并询问还有什么可以帮忙。"),  # 兜底：其它
)

# 整链：先并行分析，再把分支回复 assign 进结果字典（沿用阶段 2 的 .assign 语义：
# 保留 sentiment/category/feedback，再加一个 reply 字段），这样中间态和回复都看得见。
full_chain = analyze | RunnablePassthrough.assign(reply=route)

if __name__ == "__main__":
    for fb in [
        "你们的 App 又崩了，第三次了，太差劲！",
        "请问会员到期后数据还会保留多久？",
    ]:
        # 一次完整链 invoke 内并发发起「情绪」「类别」两个模型请求，总耗时≈较慢的那条，
        # 再按 category 走对应分支生成回复。
        result = full_chain.invoke({"feedback": fb})
        print(f"raw result:{result}\n")
        print(f"【反馈】{fb}")
        print(f"【情绪】{result['sentiment']}  【类别】{result['category']}")
        print(f"【回复】{result['reply']}\n")

    # 自检：直接内省 route 真实的条件谓词（route.branches 是 [(cond, 分支), ...]，
    # 末尾兜底不带 cond），确定性验证而不调模型。这样若把 route 里的类别标签打错，
    # 自检会立刻失败——测的是 route 本身，不是另写一个同结构的替身。
    complaint_cond = route.branches[0][0]
    inquiry_cond = route.branches[1][0]
    assert complaint_cond.invoke({"category": "投诉"}) is True
    assert complaint_cond.invoke({"category": "咨询"}) is False
    assert inquiry_cond.invoke({"category": "咨询"}) is True
    assert inquiry_cond.invoke({"category": "退款"}) is False  # 未列类别两条都不命中→走兜底

    # 自检：Literal 确实拒绝表外标签——这正是分支敢用 == 精确比较的依据。
    try:
        Category(label="投诉。")
    except ValidationError:
        pass
    else:
        raise AssertionError("Literal 未拦住表外标签")
    print("[self-check] 分支条件命中正确、枚举拒绝表外标签 ✓")

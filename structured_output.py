"""结构化输出演示：让模型直接返回一个对象，而不是一段字符串。

场景：从一句自由格式的招聘信息里，抽取出结构化字段。
关键点：用 `with_structured_output(Schema)` 后，链的输出直接是 Pydantic 对象，
省掉「让模型输出 JSON → 自己 json.loads → 校验字段」这一整套易错的手工活。
"""
import os
from typing import Optional

# 开启 Anthropic SDK 调试日志：打印发出的请求体、目标 URL 和响应头。
os.environ.setdefault("ANTHROPIC_LOG", "debug")

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

model = ChatAnthropic(
    model="claude-opus-4-8",
    max_tokens=1024,
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ["ANTHROPIC_API_KEY"],
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
)

def print_raw_response(response):
    response.read()
    print("\n=== HTTP 原始响应 ===")
    print(response.text)


model._client._client.event_hooks["response"].append(print_raw_response)

# schema 即契约：字段名、类型、Field 描述都会喂给模型，指导它怎么填。
class JobPosting(BaseModel):
    """一条招聘信息里抽取出的关键字段。"""

    title: str = Field(description="职位名称")
    company: str = Field(description="公司名称")
    location: str = Field(description="工作地点，城市即可")
    remote: bool = Field(description="是否支持远程")
    min_salary_k: Optional[int] = Field(
        default=None, description="月薪下限，单位千元；文本没提到就留空"
    )
    skills: list[str] = Field(description="要求的技能/关键词列表")
    ##工作年限
    work_experience: Optional[int] = Field(
        default=None, description="工作年限，单位年；文本没提到就留空"
    )


# 本版本还可选 method="json_schema"（Anthropic 原生），但当前自定义网关不兑现该约束，
# 会返回自定义键导致校验失败；故显式选用 function_calling（也是本版本默认值）。
# 两种方式都由 with_structured_output 负责生成 schema、解析并校验 Pydantic 对象。
extract_chain = (
    ChatPromptTemplate.from_messages(
        [
            ("system", "你是招聘信息抽取器，只依据给定文本填写字段，不要编造。"),
            ("human", "{posting}"),
        ]
    )
    | model.with_structured_output(JobPosting, method="function_calling",include_raw=True)
)

if __name__ == "__main__":
    posting = (
        "我们招一名高级后端工程师，base 上海，可远程。"
        "要求熟悉 Python、PostgreSQL 和 Kubernetes，月薪 30k 起。"
        "工作经验：3-5 年"
    )

    # 链的输出直接是 JobPosting 实例，可以像普通对象一样点字段。
    #job: JobPosting = extract_chain.invoke({"posting": posting})
    result = extract_chain.invoke({"posting": posting})

    print("解析后的对象：")
    print(result["parsed"].model_dump_json(indent=2))

    print("\n原始 AIMessage：")
    print(result["raw"].model_dump_json(indent=2))

    print("\n解析错误：")
    print(result["parsing_error"])
    job = result["parsed"]
    print(f"raw job: {job.model_dump_json(indent=2)}")
    print(f"【职位】{job.title} @ {job.company}")
    print(f"【地点】{job.location}（远程：{'是' if job.remote else '否'}）")
    print(f"【月薪下限】{job.min_salary_k}k" if job.min_salary_k else "【月薪下限】未提及")
    print(f"【技能】{', '.join(job.skills)}")
    print(f"【工作年限】{job.work_experience}年" if job.work_experience else "【工作年限】未提及")

    # 自检：拿一段没提薪资的文本，min_salary_k 必须为 None（可选字段的容错）。
    result2 = extract_chain.invoke({"posting": "招前端实习生，北京现场办公，会 React 即可。"})
    job2 = result2["parsed"]
    assert job2.min_salary_k is None, f"未提薪资应为 None，实得 {job2.min_salary_k}"
    assert job2.remote is False, f"现场办公 remote 应为 False，实得 {job2.remote}"
    print("\n[self-check] 可选字段容错通过 ✓")

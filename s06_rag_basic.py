"""检索增强生成（RAG）演示：先查资料，再让模型照着资料回答。

前五阶段模型只能靠「训练时学过的」和「你塞进提示词的」回答。RAG 补的是第三条路：
把外部知识切成小块存进向量库，提问时**只捞相关的几块**塞进提示词，模型照着答。

流水线五步（本文件按顺序实现）：
  加载 → 切分(splitter) → 向量化(embeddings) → 存/检索(vector store) → 喂给模型

关键点：
- 为什么切分：整篇文档塞进去既超上下文又稀释重点；切成块才能只捞相关的那几块。
- 为什么向量：关键词匹配「猫」搜不到「喵星人」，向量按语义近邻找。
- 检索器就是个 Runnable：retriever 能直接 `|` 进 LCEL 链，和前几阶段一样拼。
- 提示词里必须写「只用资料回答，没有就说不知道」，否则模型会拿训练记忆瞎补（幻觉）。

本仓库的网关不提供 /v1/embeddings，所以 embedding 用本地实现（见 LocalEmbeddings），
不装 torch、不调外部 API。换成真 embedding 服务时只替换这一个类，其余不动。
"""
import math
import re
from collections import Counter

from langchain_core.embeddings import Embeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from llm import openai_chat

# 凭据统一由 llm.py 读 config.ini / 环境变量，这里只管挑模型和采样参数
model = openai_chat(max_tokens=1024, temperature=0)  # temperature=0：照着资料复述，不要发挥


def bigrams(text: str) -> list[str]:
    """中文没有空格分词，用字符 bigram 当「词」：「免运费」→ ["免运", "运费"]。

    够用且零依赖（不引 jieba）。阶段 6 的向量化和 s06_rag_hybrid 的 BM25 共用它，
    两路检索切词一致，排序差异才只来自打分方式而不是切词方式。
    """
    s = re.sub(r"\s+", "", text.lower())
    return [s[i : i + 2] for i in range(len(s) - 1)] or [s]


class LocalEmbeddings(Embeddings):
    """把文本哈希成定长向量：字符 bigram 词袋 → 哈希分桶 → L2 归一化。

    真 embedding 模型（OpenAI text-embedding-3、bge 等）学的是语义，
    这个只按「字面片段重叠」算相似度——「喵星人」查不到「猫」。
    但 RAG 流水线要演示的是「切分→向量→检索→喂模型」这套形状，
    换成真服务时把这个类换掉即可，下游 vector store / retriever / 链都不用改。

    ponytail: 字面重叠而非语义，够跑通 demo；要真语义就换成
    OpenAIEmbeddings / HuggingFaceEmbeddings（同一个 Embeddings 接口）。
    """

    dim = 512

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for g, n in Counter(bigrams(text)).items():
            v[hash(g) % self.dim] += n
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]  # 归一化后点积=余弦相似度

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# —— 第 1 步：加载 —— 真实项目里这里是 PDF/网页/数据库；demo 直接用字符串，
# 免得引入一堆 loader 依赖，喧宾夺主。
DOC = """
喵星速递是一家宠物用品电商。会员分为普通会员和黑金会员两档。
普通会员每月免运费两次，黑金会员无限免运费，且享有全场九折。
会员到期后，账号数据（订单、收藏、地址）保留 180 天，超期自动清空且不可恢复。
退货政策：商品签收后 7 天内可无理由退货，生鲜类和已拆封的猫粮不支持无理由退货。
退款到账时间：原路退回，信用卡 3 到 5 个工作日，余额账户实时到账。
客服工作时间为每天 9 点到 21 点，超时留言次日 10 点前回复。
"""

# —— 第 2 步：切分 —— RecursiveCharacterTextSplitter 按 段落→句→字 逐级降级切，
# 尽量在自然边界断开，而不是硬切到半句话。chunk_overlap 让相邻块有重叠，
# 避免答案正好压在切口上被劈成两半。
splitter = RecursiveCharacterTextSplitter(chunk_size=60, chunk_overlap=15)
chunks = splitter.create_documents([DOC])

# —— 第 3、4 步：向量化 + 存 —— from_documents 内部就是 embed_documents 后建索引。
# InMemoryVectorStore 是 core 自带的内存实现，进程退出即丢；换 Chroma/PGVector
# 只改这一行，retriever 接口不变。
store = InMemoryVectorStore.from_documents(chunks, LocalEmbeddings())

# 检索器：k=3 表示每次问题捞最相近的 3 块。k 太小可能漏掉答案，太大稀释重点、费 token。
retriever = store.as_retriever(search_kwargs={"k": 3})


def format_docs(docs) -> str:
    """把检索到的块拼成一段纯文本喂给提示词。"""
    return "\n---\n".join(d.page_content for d in docs)


# —— 第 5 步：喂给模型 ——
# 「只依据资料回答，资料里没有就说不知道」是 RAG 提示词的命门：
# 不写这句，模型会用训练记忆补一个看起来合理的答案，也就是幻觉。
prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是客服助手。只依据下面的资料回答问题，"
            "资料里没有写的，直接回答「资料里没有提到」，不要猜测。\n\n资料：\n{context}",
        ),
        ("human", "{question}"),
    ]
)

# 整链：问题字符串进来 → 并行准备 context（检索+拼接）和 question（原样透传）→ 提示词 → 模型。
# retriever 本身是 Runnable，所以能直接 `|` 进来，和阶段 1-4 的拼法完全一致。
rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | model
    | StrOutputParser()
)

if __name__ == "__main__":
    for q in [
        "会员到期后数据还会保留多久？",
        "拆封过的猫粮能退吗？",
        "你们支持海外配送吗？",  # 资料里没有 → 该答「资料里没有提到」，验证不瞎编
    ]:
        print(f"【问】{q}")
        print(f"【检索到】{[d.page_content for d in retriever.invoke(q)]}")
        print(f"【答】{rag_chain.invoke(q)}\n")

    # —— 自检：测检索这一环（确定性、不调模型）——
    # 检索错了，后面模型再强也答不对，所以卡这一环最值。
    hits = format_docs(retriever.invoke("会员到期后数据保留多久"))
    assert "180 天" in hits, f"该检索到数据保留条款，实得：{hits}"
    hits = format_docs(retriever.invoke("退款多久到账"))
    assert "工作日" in hits, f"该检索到退款时效条款，实得：{hits}"
    # 切分确实切开了，且重叠没把块撑爆（chunk_size 是上限，允许略超以保全边界）
    assert len(chunks) > 1, "文档没被切分"
    print("[self-check] 检索命中相关块 ✓")

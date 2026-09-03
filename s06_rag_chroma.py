"""阶段 6 的存储后端对照：把向量库从内存换成 Chroma（落盘持久化）。

和 `s06_rag_basic.py` 是同一条 RAG 流水线，**只有第 4 步「存」换了实现**。

三件事值得讲清楚：

1. **为什么换库只改一行**：LangChain 把「怎么把文本变成向量」（`Embeddings`）和
   「向量存哪、怎么查」（`VectorStore`）拆成两个接口，二者只靠 `embed_documents` /
   `embed_query` 这两个方法通信。`LocalEmbeddings` 不知道下游是内存还是 Chroma，
   Chroma 也不关心向量是哈希算的还是 OpenAI 算的。再往下游，
   `store.as_retriever()` 返回的都是同一个 `Retriever` Runnable，
   所以 `retriever | format_docs | prompt | model` 那条链**一个字都不用改**。
   换 PGVector / Qdrant / Milvus 同理。

2. **持久化解决什么问题**：`InMemoryVectorStore` 进程退出即丢，每次跑都要把全部
   文档重新嵌入一遍。demo 里文档只有 6 行、嵌入是本地哈希，重算无感；真实项目里
   嵌入要调外部 API——**按 token 收费、有速率限制、几万块文档要跑几分钟**。
   落盘后第二次启动直接复用已有向量，省钱省时间。这就是下面「首次建库 / 复用落盘」
   分支存在的意义，也是内存库和持久库的本质区别。

3. **踩过的坑：`hash()` 不能用来做持久化哈希**。`LocalEmbeddings._vec` 原来用内置
   `hash(g)` 分桶，而 Python 对 str 的 hash 每个进程随机加盐（PYTHONHASHSEED），
   同一个 bigram 这次进程算出桶 17、下次算出桶 300。内存库建库和查询在同一进程，
   盐相同，看不出任何问题；一旦向量落盘，**下次进程的查询向量和库里的文档向量落在
   完全不同的维度上，点积趋近 0，检索静默失效**——不报错，只是永远搜不到东西。
   已改成 `zlib.crc32`（确定性、跨进程稳定，见 s06_rag_basic.py 该行注释）。
   凡是要落盘、要跨进程复现的哈希，都不能用内置 `hash()`。

运行两次感受区别：
    .venv/bin/python s06_rag_chroma.py   # 首次建库，嵌入 N 块
    .venv/bin/python s06_rag_chroma.py   # 复用已落盘的 M 条向量，跳过嵌入
删掉 chroma_db/ 目录即可回到首次状态。
"""
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

# 复用阶段 6 基础版的嵌入实现与切好的块——本仓库的 demo 刻意互相 import，
# 强调「换的只是存储后端，前三步一模一样」。注意 import 会执行 s06_rag_basic 的
# 模块级代码（建 ChatOpenAI 客户端、切分文档），这是预期行为。
from s06_rag_basic import LocalEmbeddings, chunks, format_docs
from llm import openai_chat

model = openai_chat(max_tokens=1024, temperature=0)

# 落盘目录：用 __file__ 拼绝对路径，从任何工作目录运行结果都一致。
# 这个目录已进 .gitignore——向量是可从源文档重新生成的派生物，不该入库。
PERSIST_DIR = Path(__file__).parent / "chroma_db"

# —— 第 4 步：存（唯一的改动）——
# 对照 s06_rag_basic.py 的：
#     store = InMemoryVectorStore.from_documents(chunks, LocalEmbeddings())
# 这里不用 from_documents，因为要先打开集合看看有没有旧数据，再决定要不要嵌入。
store = Chroma(
    collection_name="miao_faq",
    embedding_function=LocalEmbeddings(),
    persist_directory=str(PERSIST_DIR),
)

# 集合非空 = 上次运行已经把向量写盘了，这次直接查，一次嵌入都不用算。
# 内存库没有这个分支可写：它每次启动都是空的，只能全量重算。
# 注意这是「有没有」的粗判断，真实项目还要处理「源文档变了怎么办」——
# 通常给每块算个内容哈希当 id，用 upsert 覆盖变更块（本 demo 从简）。
# ponytail: 只判空不判内容版本；文档会变的场景加 id=内容哈希 + upsert。
existing = store.get(include=[])["ids"]  # 公开 API，比 store._collection.count() 稳
if existing:
    print(f"[store] 复用已落盘的 {len(existing)} 条向量，跳过嵌入")
else:
    store.add_documents(chunks)
    print(f"[store] 首次建库，嵌入 {len(chunks)} 块并写入 {PERSIST_DIR.name}/")

# 往下全部与 s06_rag_basic.py 同构——这正是要证明的：换库不影响下游。
retriever = store.as_retriever(search_kwargs={"k": 3})

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

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | model
    | StrOutputParser()
)

if __name__ == "__main__":
    for q in ["会员到期后数据还会保留多久？", "退款多久能到账？"]:
        print(f"【问】{q}")
        print(f"【答】{rag_chain.invoke(q)}\n")

    # —— 自检：与 s06_rag_basic.py 用同样两条断言 ——
    # 断言不变而存储换了，通过即证明「换库检索质量不变」；
    # 第二次运行时它查的是上一进程写盘的向量，同时也验证了 crc32 稳定哈希那个修复。
    hits = format_docs(retriever.invoke("会员到期后数据保留多久"))
    assert "180 天" in hits, f"该检索到数据保留条款，实得：{hits}"
    hits = format_docs(retriever.invoke("退款多久到账"))
    assert "工作日" in hits, f"该检索到退款时效条款，实得：{hits}"
    print("[self-check] Chroma 持久化后检索命中相关块 ✓")

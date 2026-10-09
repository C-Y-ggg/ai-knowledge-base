import redis
import os
import json
from sqlalchemy.orm import Session
from openai import OpenAI
from dotenv import load_dotenv
from . import models
from .llm_utils import get_embedding, get_rerank

load_dotenv()

# 连接 Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)


# ==================== 1. 上传文件逻辑 ====================
def create_knowledge_from_file(db: Session, file_name: str, file_path: str):
    db_knowledge = models.Knowledge(
        file_name=file_name,
        file_path=file_path,
        parse_status="pending"
    )
    db.add(db_knowledge)
    db.commit()
    db.refresh(db_knowledge)

    r.lpush("knowledge_queue", db_knowledge.id)
    return db_knowledge


# ==================== 2. 问答逻辑（RAG 核心） ====================
def chat_stream_with_knowledge_base(db: Session, query: str, history: list = None):
    """流式问答生成器（带引用溯源 + 重排序 + 优雅降级）"""
    if history is None:
        history = []

    # 1. 向量化问题
    query_vector = get_embedding(query)
    if not query_vector:
        yield f"data: {json.dumps({'content': '抱歉，我暂时无法理解您的问题。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # 2. 第一步：雷达扫描（粗筛，先捞出 20 条候选）
    top_chunks = db.query(models.Chunk).order_by(
        models.Chunk.embedding.cosine_distance(query_vector)
    ).limit(20).all()

    if not top_chunks:
        yield f"data: {json.dumps({'content': '抱歉，知识库中还没有相关内容，请先上传文档。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # 3. 第二步：重排序（精排，挑出最相关的 3 条）
    documents = [c.content for c in top_chunks]
    reranked_results = get_rerank(query, documents)

    # 🟢 核心改动 1：加入相关性阈值判断（拦截知识库外的问题）
    if reranked_results and reranked_results[0].get('relevance_score', 0) < 0.3:
        yield f"data: {json.dumps({'content': '抱歉，知识库中的现有文档无法回答这个问题。您可以尝试上传更相关的文档，或者换一种问法。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    final_chunks = []
    if reranked_results:
        for res in reranked_results[:3]:  # 真正限制为前 3 条
            original_index = res['index']
            if 0 <= original_index < len(top_chunks):  # 防御越界
                final_chunks.append(top_chunks[original_index])

    if not final_chunks:
        # 降级：rerank 出错、为空、或全部越界时，退回粗筛前 3 条
        final_chunks = top_chunks[:3]

    # 4. 构造带编号的上下文（基于精排后的 final_chunks）
    knowledge_ids = list({c.knowledge_id for c in final_chunks})
    knowledges = db.query(models.Knowledge).filter(
        models.Knowledge.id.in_(knowledge_ids)
    ).all()
    knowledge_map = {k.id: k for k in knowledges}

    context_parts = []
    sources = []
    for i, chunk in enumerate(final_chunks):
        knowledge = knowledge_map.get(chunk.knowledge_id)
        file_name = knowledge.file_name if knowledge else "未知文件"

        context_parts.append(f"[{i + 1}] {chunk.content}")
        sources.append({"index": i + 1, "file_name": file_name, "chunk_id": chunk.id})

    context = "\n\n".join(context_parts)

    # 5. 构造 Prompt
    history_text = ""
    for h in history:
        role = "用户" if h.get("role") == "user" else "AI助手"
        history_text += f"{role}：{h.get('content')}\n"

    prompt = f"""你是一个专业的AI助手。请严格根据以下提供的参考信息回答用户的问题。
如果在参考信息中找不到答案，请直接说“根据现有资料无法回答”，不要编造事实。
如果引用了某条信息，请在句子末尾用 [编号] 标注出来（例如：根据呈报表，主要填写了个人信息 [1]）。

【历史对话】：
{history_text if history_text else "（无历史对话）"}

【参考信息】：
{context}

【用户问题】：
{query}
"""

    # 6. 呼叫大厨，开启流式模式
    llm_client = OpenAI(
        api_key=os.getenv("ZHIPU_API_KEY"),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        timeout=15.0  # 加上超时，防止假死
    )

    try:
        response = llm_client.chat.completions.create(
            model="glm-5.3-flash",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            stream=True
        )

        for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                # 🟢 必须用 JSON 包装，前端才能正确解析出文字！
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

        # 流式输出结束后，发送来源信息（注意缩进，在 for 循环外面）
        yield f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'content': f'大厨炒菜失败: {e}'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
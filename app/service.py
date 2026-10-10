import redis
import os
import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import OpenAI
from dotenv import load_dotenv
from . import models
from .llm_utils import get_embedding, get_rerank

load_dotenv()

# 连接 Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)


# ==================== 上传文件逻辑 ====================
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


# ==================== RRF 融合算法 ====================
def rrf_fusion(vector_results: list, keyword_results: list, k: int = 60, top_n: int = 10):
    """
    RRF (Reciprocal Rank Fusion) 倒数排名融合算法

    参数说明：
    - vector_results: 向量检索返回的 Chunk 列表（已按相似度排序）
    - keyword_results: 关键词检索返回的 Chunk 列表（已按相关度排序）
    - k: 平滑参数，通常取 60。k 越大，排名靠后的文档得分衰减越慢。
    - top_n: 最终返回几条

    原理：
    对于每个文档，它的得分 = 它在向量路中的 1/(k+排名) + 它在关键词路中的 1/(k+排名)
    两路都排名靠前的文档，得分会叠加，脱颖而出。
    """
    scores = {}  # 记录每个 chunk_id 的总分
    chunks_map = {}  # 记录每个 chunk_id 对应的 Chunk 对象

    # 1. 向量检索的排名得分
    for rank, chunk in enumerate(vector_results):
        scores[chunk.id] = scores.get(chunk.id, 0) + 1.0 / (k + rank + 1)
        chunks_map[chunk.id] = chunk

    # 2. 关键词检索的排名得分
    for rank, chunk in enumerate(keyword_results):
        scores[chunk.id] = scores.get(chunk.id, 0) + 1.0 / (k + rank + 1)
        chunks_map[chunk.id] = chunk

    # 3. 按总分降序排序，取 Top N
    sorted_chunk_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_n]
    return [chunks_map[cid] for cid in sorted_chunk_ids]


# ==================== 问答逻辑（RAG 核心） ====================
def chat_stream_with_knowledge_base(db: Session, query: str, conversation_id: int = None, history: list = None):
    """流式问答生成器（混合检索 + 重排序 + 优雅降级）"""

    # 1. 如果传了 conversation_id，从数据库获取历史记录
    if conversation_id:
        past_messages = db.query(models.Message).filter(
            models.Message.conversation_id == conversation_id
        ).order_by(models.Message.id.asc()).all()

        history = [{"role": msg.role, "content": msg.content} for msg in past_messages[-10:]]

        # 第一条消息自动生成标题
        if len(past_messages) == 0:
            conv = db.query(models.Conversation).filter(models.Conversation.id == conversation_id).first()
            if conv:
                conv.title = query[:15] + ("..." if len(query) > 15 else "")
                db.commit()

        # 存用户消息
        user_msg = models.Message(conversation_id=conversation_id, role="user", content=query)
        db.add(user_msg)
        db.commit()
    else:
        history = history or []

    # 2. 向量化问题
    query_vector = get_embedding(query)
    if not query_vector:
        yield f"data: {json.dumps({'content': '抱歉，我暂时无法理解您的问题。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ==================== 混合检索（核心！） ====================
    # 第 1 路：向量检索（粗筛 20 条）
    vector_chunks = db.query(models.Chunk).order_by(
        models.Chunk.embedding.cosine_distance(query_vector)
    ).limit(20).all()

    # 第 2 路：关键词检索（粗筛 20 条）
    # 用 PostgreSQL 的 ILIKE 做模糊匹配。query 中的特殊字符需要转义。
    # 这里为了简单，直接使用 ILIKE。生产环境可用 to_tsquery 或 Elasticsearch。
    keyword_chunks = db.query(models.Chunk).filter(
        models.Chunk.content.ilike(f"%{query}%")
    ).limit(20).all()

    # RRF 融合两路结果，取 10 条作为候选
    top_chunks = rrf_fusion(vector_chunks, keyword_chunks, k=60, top_n=10)

    if not top_chunks:
        yield f"data: {json.dumps({'content': '抱歉，知识库中还没有相关内容，请先上传文档。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return
    # ============================================================

    # 3. 重排序（精排，挑出最相关的 3 条）
    documents = [c.content for c in top_chunks]
    reranked_results = get_rerank(query, documents)

    if reranked_results and reranked_results[0].get('relevance_score', 0) < 0.3:
        yield f"data: {json.dumps({'content': '抱歉，知识库中的现有文档无法回答这个问题。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    final_chunks = []
    if reranked_results:
        for res in reranked_results[:3]:
            original_index = res['index']
            if 0 <= original_index < len(top_chunks):
                final_chunks.append(top_chunks[original_index])

    if not final_chunks:
        final_chunks = top_chunks[:3]

    # 4. 构造上下文与 Prompt
    knowledge_ids = list({c.knowledge_id for c in final_chunks})
    knowledges = db.query(models.Knowledge).filter(models.Knowledge.id.in_(knowledge_ids)).all()
    knowledge_map = {k.id: k for k in knowledges}

    context_parts = []
    sources = []
    for i, chunk in enumerate(final_chunks):
        knowledge = knowledge_map.get(chunk.knowledge_id)
        file_name = knowledge.file_name if knowledge else "未知文件"
        context_parts.append(f"[{i + 1}] {chunk.content}")
        sources.append({"index": i + 1, "file_name": file_name, "chunk_id": chunk.id})

    context = "\n\n".join(context_parts)

    history_text = ""
    for h in history:
        role = "用户" if h.get("role") == "user" else "AI助手"
        history_text += f"{role}：{h.get('content')}\n"

    prompt = f"""你是一个专业的AI助手。请严格根据以下提供的参考信息回答用户的问题。
如果在参考信息中找不到答案，请直接说“根据现有资料无法回答”，不要编造事实。
如果引用了某条信息，请在句子末尾用 [编号] 标注出来。

【历史对话】：
{history_text if history_text else "（无历史对话）"}

【参考信息】：
{context}

【用户问题】：
{query}
"""

    # 5. 呼叫大厨
    llm_client = OpenAI(
        api_key=os.getenv("ZHIPU_API_KEY"),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        timeout=15.0
    )

    full_response = ""
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
                full_response += content
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

        # 存档AI回答
        if conversation_id and full_response:
            ai_msg = models.Message(conversation_id=conversation_id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()

        yield f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'content': f'大厨炒菜失败: {e}'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
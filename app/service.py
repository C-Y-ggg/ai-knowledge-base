import redis
import os
import json
from sqlalchemy.orm import Session
from openai import OpenAI
from dotenv import load_dotenv
from . import models
from .llm_utils import get_embedding, get_rerank

load_dotenv()

r = redis.Redis(host='localhost', port=6379, decode_responses=True)


def create_knowledge_from_file(db: Session, file_name: str, file_path: str):
    db_knowledge = models.Knowledge(file_name=file_name, file_path=file_path, parse_status="pending")
    db.add(db_knowledge)
    db.commit()
    db.refresh(db_knowledge)
    r.lpush("knowledge_queue", db_knowledge.id)
    return db_knowledge


def chat_stream_with_knowledge_base(db: Session, query: str, conversation_id: int = None, history: list = None):
    """流式问答生成器（支持数据库会话历史 + 引用溯源 + 重排序）"""

    # 1. 如果传了 conversation_id，从数据库获取历史记录
    if conversation_id:
        past_messages = db.query(models.Message).filter(
            models.Message.conversation_id == conversation_id
        ).order_by(models.Message.id.asc()).all()

        # 只取最近 10 条作为上下文
        history = [{"role": msg.role, "content": msg.content} for msg in past_messages[-10:]]

        # 如果该会话是第一条消息，自动生成标题
        if len(past_messages) == 0:
            conv = db.query(models.Conversation).filter(models.Conversation.id == conversation_id).first()
            if conv:
                conv.title = query[:15] + ("..." if len(query) > 15 else "")
                db.commit()

        # 把当前用户消息存进数据库
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

    # 3. 雷达扫描与重排序
    top_chunks = db.query(models.Chunk).order_by(
        models.Chunk.embedding.cosine_distance(query_vector)
    ).limit(20).all()

    if not top_chunks:
        yield f"data: {json.dumps({'content': '抱歉，知识库中还没有相关内容，请先上传文档。'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

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

    # 5. 呼叫llm，开启流式模式
    llm_client = OpenAI(
        api_key=os.getenv("ZHIPU_API_KEY"),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        timeout=15.0
    )

    full_response = ""  # 用于存库
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

        # 6. 存库：将 AI 的回答保存到数据库
        if conversation_id and full_response:
            ai_msg = models.Message(conversation_id=conversation_id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()

        yield f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'content': f'处理失败: {e}'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
from openai import OpenAI
import os
from dotenv import load_dotenv
import httpx

load_dotenv()

client = OpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url="https://api.siliconflow.cn/v1"
)

def get_embedding(text: str) -> list:
    try:
        response = client.embeddings.create(
            model="BAAI/bge-m3",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"❌ 呼叫翻译官失败: {e}")
        return []

def get_rerank(query: str, documents: list) -> list:
    """呼叫重排序模型，对检索结果进行二次精排，并返回带分数的结果"""
    if not documents:
        return []
    try:
        # 硅基流动的 Rerank 接口
        response = httpx.post(
            "https://api.siliconflow.cn/v1/rerank",
            headers={
                "Authorization": f"Bearer {os.getenv('SILICONFLOW_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "BAAI/bge-reranker-v2-m3",
                "query": query,
                "documents": documents,
                "top_n": 3  # 只返回最相关的 3 条
            },
            timeout=15.0
        )
        # 返回的结果包含 index（在原始列表中的索引）和 relevance_score（相关性分数）
        return response.json().get("results", [])
    except Exception as e:
        print(f"❌ 重排序失败: {e}")
        return []